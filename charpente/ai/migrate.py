"""Migration help: an AI drafts a `.charpente` file from a CMakeLists.txt or Makefile. The draft is checked (parsed, linted) and never executed."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import List, Optional, Tuple

from ..lint import lint_source
from .context import Context
from .provider import AIProvider

SYSTEM_PROMPT = (
    "You convert a CMake or Make build description into a Charpente workspace file (`NAME.charpente`, Python). Answer with ONE ```python fenced block. "
    "The file starts with `from charpente import *` and uses: `with Workspace(\"name\", version=\"x.y.z\") as ws:`, `ws.configurations([\"Debug\", \"Release\"])`, "
    "`with Target(\"name\") as t:` then `t.kind(Kind.EXECUTABLE | Kind.STATIC_LIBRARY | Kind.SHARED_LIBRARY | Kind.TEST)`, `t.standard(\"c++17\")`, "
    "`t.sources([\"glob/*.cpp\"])`, `t.public_include_dirs([...])`, `t.include_dirs([...])`, `t.define([...])`, `t.uses(\"other\")`, "
    "`ws.requires(\"package@^1.2\")` for third-party libraries. Translate only what you can; put a `# TODO:` comment for anything you cannot express."
)
SOURCES = (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp")
_FENCE = re.compile(r"```(?:python|py)?[ \t]*\r?\n(?P<body>.*?)```", re.DOTALL | re.IGNORECASE)


def find_build_file(folder: Path) -> Optional[Path]:
    for name in ("CMakeLists.txt", "Makefile", "makefile", "GNUmakefile"):
        if (folder / name).is_file():
            return folder / name
    return None


def context_for(folder: Path, build_file: Path, limit: int) -> Context:
    context = Context(limit=limit)
    context.add(build_file.name, build_file.read_text(encoding="utf-8", errors="replace"))
    listing = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                     if p.suffix.lower() in SOURCES and "build" not in p.relative_to(folder).parts and ".git" not in p.relative_to(folder).parts)
    if listing:
        context.add("source files (names only)", "\n".join(listing[:200]))
    return context


def extract(answer: str) -> str:
    blocks = [m.group("body") for m in _FENCE.finditer(answer)]
    good = [b for b in blocks if "Workspace" in b]
    return (max(good, key=len) if good else "").strip("\n") + "\n" if good else ""


def check(text: str) -> Tuple[bool, List[str]]:
    """(usable, problems): it must parse as Python, define a Workspace, and pass the DSL lint without errors. It is never run."""
    problems: List[str] = []
    try:
        ast.parse(text)
    except SyntaxError as exc:
        return False, [f"not valid Python: line {exc.lineno}: {exc.msg}"]
    if "Workspace(" not in text or "Target(" not in text:
        return False, ["it does not declare a Workspace with at least one Target"]
    for issue in lint_source(text):
        problems.append(f"{issue.severity} [{issue.code}] line {issue.line}: {issue.message}")
    return not any(p.startswith("error") for p in problems), problems


def request(provider: AIProvider, context: Context) -> str:
    return extract(provider.complete(context.render() + "\n\nWrite the Charpente workspace file.", system=SYSTEM_PROMPT))
