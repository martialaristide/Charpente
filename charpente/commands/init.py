from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from ..core import process
from ..errors import ChError
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


def _list() -> int:
    from ..modules.runtime import get_registry

    print("Templates (charpente init NAME --template T):")
    print()
    for extension in sorted(get_registry().all("template"), key=lambda e: e.name):
        template = extension.obj
        info = getattr(template, "info", None)
        note = "" if info is None or info.verified else "  [not verified]"
        print(f"  {template.name:<18} {template.description}{note}")
    return 0


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente init", description="Scaffold a new workspace.")
    parser.add_argument("name", nargs="?", help="Workspace and target name")
    parser.add_argument("--dir", default=None, help="Directory to create the workspace in (default: the current directory; "
                                                    "with --template, a new folder named NAME)")
    parser.add_argument("--template", metavar="T", help="Start from a template (`charpente init --list` shows them)")
    parser.add_argument("--list", action="store_true", help="List the templates")
    parser.add_argument("--install", action="store_true", help="Run `charpente pkg install` in the new project when it needs it")
    parsed = parser.parse_args(args)
    if parsed.list:
        return _list()
    if not parsed.name:
        parser.error("the following arguments are required: name")

    name = validate(parsed.name, "Workspace name")
    if parsed.template:
        return _from_template(parsed.template, name, parsed.dir, parsed.install)

    root = Path(parsed.dir or ".").resolve()
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


def _from_template(template_name: str, name: str, directory: Optional[str], install: bool) -> int:
    from ..modules.runtime import get_registry

    extension = get_registry().get("template", template_name)
    if extension is None:
        known = ", ".join(sorted(e.name for e in get_registry().all("template")))
        raise ChError("CH4009", name=template_name, known=known)
    template = extension.obj
    root = Path(directory).resolve() if directory else (Path.cwd() / name).resolve()
    written = template.generate(root, name)
    info = getattr(template, "info", None)
    print(f"Created {name} from the {template_name!r} template in {root} ({len(written)} files).")
    if info is not None and info.unverified:
        print(f"Note: {info.unverified}")
    if info is not None and info.install:
        if install:
            result = process.run([sys.executable, "-m", "charpente", "pkg", "install"], cwd=str(root), timeout=1800)
            print(result.output)
            if result.returncode != 0:
                return result.returncode
        else:
            print("\nThis project uses packages: run `charpente pkg install` first (it downloads and checksums them).")
    from ..templates import render, values_for

    values = values_for(name)
    for step in info.next if info is not None else ():
        print(f"  {render(step, values)}")
    return 0
