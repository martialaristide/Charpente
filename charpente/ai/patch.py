"""Unified diffs as an AI proposes them: extracted from an answer, parsed, checked against the real files, applied in memory.

Models get line numbers and hunk lengths slightly wrong, so hunks are located by their *content* (the context and removed lines must match the
file exactly, ignoring trailing spaces), searching near the stated line; a hunk that matches nowhere, or in two equally good places, is refused
rather than guessed. Nothing here touches the disk: `apply_patches` returns the new file contents for the caller to show and, if approved, write.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .context import is_secret_file

SEARCH_WINDOW = 120
CRLF, LF = chr(13) + chr(10), chr(10)


class PatchError(Exception):
    """The proposed patch cannot be applied safely; the message says why."""


@dataclass
class Hunk:
    old_start: int
    lines: List[Tuple[str, str]] = field(default_factory=list)      # (" " | "-" | "+", text without the marker)

    @property
    def old_lines(self) -> List[str]:
        return [text for tag, text in self.lines if tag in (" ", "-")]

    @property
    def new_lines(self) -> List[str]:
        return [text for tag, text in self.lines if tag in (" ", "+")]


@dataclass
class FilePatch:
    path: str
    is_new: bool = False
    hunks: List[Hunk] = field(default_factory=list)


_FENCE = re.compile(r"```(?:diff|patch)?[ \t]*\r?\n(?P<body>.*?)```", re.DOTALL)
_HUNK = re.compile(r"^@@ -(?P<start>\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")


def extract_diff(answer: str) -> str:
    """The diff inside an answer: the first fenced block that looks like one, else the text from the first `--- ` line."""
    for match in _FENCE.finditer(answer):
        if "\n+++ " in "\n" + match.group("body") or match.group("body").lstrip().startswith("--- "):
            return match.group("body")
    start = re.search(r"^--- ", answer, re.MULTILINE)
    return answer[start.start():] if start else ""


def _clean_path(raw: str) -> str:
    path = raw.strip().split("\t")[0].strip()
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path.strip('"')


def parse(diff: str) -> List[FilePatch]:
    patches: List[FilePatch] = []
    current: Optional[FilePatch] = None
    hunk: Optional[Hunk] = None
    old_name = ""
    blanks = 0                                   # empty lines at the end of the current hunk: separators between diffs, not code

    def close() -> None:
        nonlocal blanks
        if hunk is not None and blanks:
            del hunk.lines[-blanks:]
        blanks = 0

    for raw in diff.replace(CRLF, LF).split(LF):
        if raw.startswith("--- "):
            close()
            old_name = raw[4:]
            hunk = None
            continue
        if raw.startswith("+++ "):
            new_name = raw[4:]
            if new_name.strip() == "/dev/null":
                raise PatchError("deleting files is not allowed in a proposed fix")
            path = _clean_path(new_name)
            current = FilePatch(path, is_new=old_name.strip() == "/dev/null")
            patches.append(current)
            hunk = None
            continue
        match = _HUNK.match(raw)
        if match:
            close()
            if current is None:
                raise PatchError("a hunk appears before any file header")
            hunk = Hunk(int(match.group("start")))
            current.hunks.append(hunk)
            continue
        if hunk is not None:
            if raw.startswith(chr(92)):
                continue                                              # "\ No newline at end of file"
            if raw[:1] in (" ", "+", "-"):
                hunk.lines.append((raw[0], raw[1:]))
                blanks = 0
            elif raw == "":
                hunk.lines.append((" ", ""))                            # some models drop the space of an empty context line
                blanks += 1
    close()
    if not patches or not any(p.hunks for p in patches):
        raise PatchError("no change found in the proposed diff")
    for patch in patches:
        for h in patch.hunks:
            if not any(tag in "+-" for tag, _ in h.lines):
                raise PatchError(f"a hunk of {patch.path} changes nothing")
    return patches


def _same(a: str, b: str) -> bool:
    return a.rstrip() == b.rstrip()


def _find(lines: List[str], wanted: List[str], hint: int) -> int:
    """Index in `lines` where `wanted` starts, nearest to `hint` (0-based); PatchError when absent or ambiguous."""
    if not wanted:
        return min(max(hint, 0), len(lines))
    candidates = [i for i in range(max(0, hint - SEARCH_WINDOW), min(len(lines) - len(wanted), hint + SEARCH_WINDOW) + 1)
                  if all(_same(lines[i + k], wanted[k]) for k in range(len(wanted)))]
    if not candidates:
        raise PatchError("a hunk does not match the file (the code it expects is not there)")
    candidates.sort(key=lambda i: abs(i - hint))
    if len(candidates) > 1 and abs(candidates[0] - hint) == abs(candidates[1] - hint):
        raise PatchError("a hunk matches in two places equally well; refusing to guess")
    return candidates[0]


def apply_hunks(text: str, hunks: List[Hunk]) -> str:
    ending = "\r\n" if "\r\n" in text else "\n"
    trailing = text.endswith(("\n", "\r\n"))
    lines = text.replace("\r\n", "\n").split("\n")
    if trailing:
        lines.pop()
    offset = 0
    for hunk in hunks:
        at = _find(lines, hunk.old_lines, hunk.old_start - 1 + offset)
        rebuilt: List[str] = []
        cursor = at
        for tag, line in hunk.lines:
            if tag == " ":
                rebuilt.append(lines[cursor])                      # keep the file's own text (spacing) for lines that do not change
                cursor += 1
            elif tag == "-":
                cursor += 1
            else:
                rebuilt.append(line)
        lines[at:at + len(hunk.old_lines)] = rebuilt
        offset += len(rebuilt) - len(hunk.old_lines)
    return ending.join(lines) + (ending if trailing or not text else "")


def _safe(root: Path, relative: str) -> Path:
    if not relative or relative.startswith(("/", "\\")) or ".." in Path(relative).parts or (len(relative) > 1 and relative[1] == ":"):
        raise PatchError(f"{relative!r} is outside the project")
    if ".git" in [p.lower() for p in Path(relative).parts] or is_secret_file(relative):
        raise PatchError(f"{relative} is not a file a fix may change")
    resolved = (root / relative).resolve()
    if root.resolve() not in resolved.parents:
        raise PatchError(f"{relative!r} is outside the project")
    return resolved


def apply_patches(root: Path, patches: List[FilePatch]) -> Dict[str, str]:
    """New content per project-relative path, computed in memory. Raises PatchError; never writes."""
    result: Dict[str, str] = {}
    for patch in patches:
        path = _safe(root, patch.path)
        if patch.is_new:
            if path.exists():
                raise PatchError(f"{patch.path} already exists but the patch says it is new")
            result[patch.path] = "".join(text + "\n" for h in patch.hunks for tag, text in h.lines if tag == "+")
            continue
        if not path.is_file():
            raise PatchError(f"{patch.path} does not exist")
        try:
            original = result.get(patch.path) or path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise PatchError(f"{patch.path} cannot be read as text") from exc
        result[patch.path] = apply_hunks(original, patch.hunks)
    return result


def write(root: Path, contents: Dict[str, str]) -> List[str]:
    """Write the new contents (paths re-validated); returns the paths written."""
    written = []
    for relative, text in contents.items():
        path = _safe(root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        written.append(relative)
    return written


def unified(root: Path, contents: Dict[str, str]) -> str:
    """A readable unified diff of `contents` against the files on disk (what the user reviews before approving)."""
    import difflib

    out: List[str] = []
    for relative, new in sorted(contents.items()):
        path = root / relative
        old = path.read_bytes().decode("utf-8").splitlines(keepends=True) if path.is_file() else []
        out.extend(difflib.unified_diff(old, new.splitlines(keepends=True), f"a/{relative}" if old else "/dev/null", f"b/{relative}"))
    return "".join(line if line.endswith("\n") else line + "\n" for line in out)
