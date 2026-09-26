"""Unit tests written by an AI: proposed only after they compile and pass against the real target."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from ..dsl.model import Kind, Language, Target, Workspace
from .context import Context, is_secret_file
from .provider import AIProvider

SYSTEM_PROMPT = (
    "You write C++ unit tests for one target of a project built with Charpente. Output ONE self-contained source file in a ```cpp fenced block, "
    "nothing else in the block. The file has its own main() that returns 0 when every check passes and a non-zero value otherwise, printing each "
    "failed check (file, line, expression) to stderr. Use only the standard library and the headers shown; no test framework unless the sample test "
    "shown uses one. Test observable behaviour of the public API: normal cases, edge cases and errors. Do not test private details, do not read "
    "files, do not use the network, do not sleep."
)
_FENCE = re.compile(r"```(?:cpp|c\+\+|cxx|cc|c)?[ \t]*\r?\n(?P<body>.*?)```", re.DOTALL | re.IGNORECASE)
HEADER_SUFFIXES = (".h", ".hh", ".hpp", ".hxx", ".inl")
MAX_HEADERS = 4
HEADER_CHARS = 3500


def extract_code(answer: str) -> str:
    """The C++ in an answer: the largest fenced block, else the whole answer when it looks like code."""
    blocks = [m.group("body") for m in _FENCE.finditer(answer)]
    if blocks:
        return max(blocks, key=len).strip("\n") + "\n"
    return answer.strip() + "\n" if "main" in answer and "#include" in answer else ""


def public_headers(root: Path, workspace: Workspace, target: Target) -> List[Path]:
    """Headers of `target`: those in its public include directories, then those next to its sources."""
    base = target.location or root
    found: List[Path] = []
    folders = [base / d for d in [*target.public_include_dirs, *target.include_dirs]]
    for source in target.resolved_sources() if target.source_patterns else []:
        folders.append(source.parent)
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*")):
            if path.suffix.lower() in HEADER_SUFFIXES and path not in found and not is_secret_file(path.name):
                found.append(path)
    return found[:MAX_HEADERS]


def context_for(root: Path, workspace: Workspace, target: Target, limit: int) -> Context:
    from .context import workspace_summary

    context = Context(limit=limit)
    context.add("workspace", workspace_summary(workspace))
    context.add("target", f"{target.name}: {target.kind.value}, {target.language.value} {target.standard}; uses {', '.join(target.uses) or 'nothing'}")
    for header in public_headers(root, workspace, target):
        try:
            text = header.read_text(encoding="utf-8")[:HEADER_CHARS]
        except (OSError, UnicodeDecodeError):
            continue
        context.add(f"header {header.relative_to(root).as_posix() if root in header.parents else header.name}", text)
    for other in workspace.targets.values():
        if other.kind == Kind.TEST and not other.external and other.source_patterns:
            try:
                sample = other.resolved_sources()[0].read_text(encoding="utf-8")[:2500]
            except (OSError, UnicodeDecodeError, IndexError):
                continue
            context.add(f"sample of an existing test ({other.name})", sample)
            break
    return context


def request_tests(provider: AIProvider, context: Context, *, previous_code: str = "", failure: str = "") -> str:
    prompt = context.render()
    if previous_code:
        prompt += ("\n\n### your previous attempt\n```cpp\n" + previous_code + "```\n\n### what happened when it was built and run\n" + failure.strip()[-3000:]
                   + "\n\nFix the test file and answer again with the whole file.")
    else:
        prompt += "\n\nWrite the test file for the target described above."
    return extract_code(provider.complete(prompt, system=SYSTEM_PROMPT))


def ephemeral_target(workspace: Workspace, base: Target, source: Path) -> Target:
    """A TEST target (in memory only) that builds `source` against `base`."""
    location = workspace.location or Path.cwd()
    try:
        pattern = source.resolve().relative_to(location.resolve()).as_posix()
    except ValueError:
        pattern = str(source)
    target = Target(name=f"{base.name}_ai_test", kind=Kind.TEST, language=Language.CPP, standard=base.standard if base.language == Language.CPP else "c++17",
                    source_patterns=[pattern], uses=[base.name], location=workspace.location)
    workspace.targets[target.name] = target
    return target


def suggested_path(root: Path, base: Target) -> Optional[Path]:
    return root / "tests" / f"{base.name}_ai_test.cpp"
