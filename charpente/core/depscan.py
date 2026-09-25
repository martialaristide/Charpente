"""Discovering which header files a compilation actually read.

This is what makes incremental builds correct: after compiling `a.cpp` we
record every header it included, and from then on a change to any of them
invalidates that object -- no more stale binaries after editing a header.

Two formats are understood:

* GNU/Clang depfiles written by `-MMD -MF file.d` (a Makefile rule);
* MSVC / clang-cl `/showIncludes` notes printed on stdout.

Both parsers are pure functions over text.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

_SHOW_INCLUDES_RE = re.compile(r"^Note: including file:\s*(.+?)\s*$")


def _unescape_make(text: str) -> List[str]:
    """Split the dependency list of a Makefile rule into paths.

    Handles the escapes GCC/Clang emit: `\\ ` (space in a name), `\\#`,
    `$$` (a dollar sign) and `\\`-newline continuations. A backslash before
    any other character is kept as-is, because on Windows it is a path
    separator, not an escape.
    """
    text = text.replace("\\\r\n", " ").replace("\\\n", " ")
    tokens: List[str] = []
    current: List[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in " #":
            current.append(text[i + 1])
            i += 2
            continue
        if ch == "$" and i + 1 < n and text[i + 1] == "$":
            current.append("$")
            i += 2
            continue
        if ch in " \t\r\n":
            if current:
                tokens.append("".join(current))
                current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    if current:
        tokens.append("".join(current))
    return tokens


def _split_rule(text: str) -> Optional[str]:
    """The text after the rule's `target:` separator, or None when there is none.

    The separator is the first ':' followed by whitespace (or end of text);
    that skips the ':' of a Windows drive letter ('C:/dir/x.o: ...').
    """
    joined = text.replace("\\\r\n", " ").replace("\\\n", " ")
    i, n = 0, len(joined)
    while i < n:
        ch = joined[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == ":" and (i + 1 == n or joined[i + 1] in " \t\r\n"):
            return joined[i + 1:]
        i += 1
    return None


def parse_gnu_depfile(text: str, cwd: Optional[Path] = None) -> List[Path]:
    """Header (and source) paths listed by a `-MMD` depfile, in order,
    de-duplicated. Relative paths are resolved against `cwd`."""
    rest = _split_rule(text)
    if rest is None:
        return []
    return _dedupe(_to_paths(_unescape_make(rest), cwd))


def parse_show_includes(output: str, cwd: Optional[Path] = None) -> Tuple[List[Path], str]:
    """(included paths, the output with the `Note: including file:` lines removed).

    The compiler must run with the English message catalogue (the engine sets
    VSLANG=1033): the marker text is localised otherwise.
    """
    paths: List[str] = []
    kept: List[str] = []
    for line in output.splitlines():
        match = _SHOW_INCLUDES_RE.match(line)
        if match:
            paths.append(match.group(1))
        else:
            kept.append(line)
    return _dedupe(_to_paths(paths, cwd)), "\n".join(kept)


def _to_paths(tokens: Iterable[str], cwd: Optional[Path]) -> List[Path]:
    out: List[Path] = []
    for token in tokens:
        p = Path(token)
        if not p.is_absolute() and cwd is not None:
            p = cwd / p
        out.append(p)
    return out


def _dedupe(paths: List[Path]) -> List[Path]:
    seen = set()
    unique: List[Path] = []
    for p in paths:
        key = str(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique
