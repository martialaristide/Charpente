from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from ..safe_name import validate

_WORKSPACE_TEMPLATE = """\
from charpente import *

with Workspace("__NAME__") as ws:
    ws.configurations(["Debug", "Release"])

    with Target("__NAME__") as t:
        t.kind(Kind.EXECUTABLE)
        t.language(Language.CPP)
        t.standard("c++17")
        t.sources(["src/**/*.cpp"])
"""

_MAIN_CPP_TEMPLATE = """\
#include <cstdio>

int main() {
    std::printf("Hello from __NAME__!\\n");
    return 0;
}
"""


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente init", description="Scaffold a new workspace.")
    parser.add_argument("name", help="Workspace and target name")
    parser.add_argument("--dir", default=".", help="Directory to create the workspace in (default: current directory)")
    parsed = parser.parse_args(args)

    name = validate(parsed.name, "Workspace name")
    root = Path(parsed.dir).resolve()
    workspace_file = root / f"{name}.charpente"
    src_dir = root / "src"

    if workspace_file.exists():
        print(f"charpente: {workspace_file} already exists.")
        return 1

    src_dir.mkdir(parents=True, exist_ok=True)
    workspace_file.write_text(_WORKSPACE_TEMPLATE.replace("__NAME__", name), encoding="utf-8")
    main_cpp = src_dir / "main.cpp"
    if not main_cpp.exists():
        main_cpp.write_text(_MAIN_CPP_TEMPLATE.replace("__NAME__", name), encoding="utf-8")

    print(f"Created {workspace_file}")
    print(f"Created {main_cpp}")
    print(f"\nNext: cd {root} && charpente build && charpente run")
    return 0
