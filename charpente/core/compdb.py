"""compile_commands.json: the JSON Compilation Database that clangd, clang-tidy,
CLion, VS Code and most C/C++ tooling read to understand how each file is built.

Generated from the *planned* compile actions, so it is available even when a
build fails half-way, and rewritten only when its content changes (touching
the file needlessly makes language servers reload).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from .graph import ActionGraph


def entries(graph: ActionGraph) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for action in graph.actions.values():
        if action.kind != "compile" or action.source is None:
            continue
        out.append({
            "directory": str(action.cwd or Path.cwd()),
            "file": str(action.source),
            "arguments": list(action.argv),
            "output": str(action.outputs[0]),
        })
    return sorted(out, key=lambda e: e["file"])


def render(graph: ActionGraph) -> str:
    return json.dumps(entries(graph), indent=2) + "\n"


def write(graph: ActionGraph, path: Path) -> bool:
    """Write the database to `path`. Returns True if the file changed."""
    text = render(graph)
    path = Path(path)
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".cc-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except OSError:
        return False
    return True
