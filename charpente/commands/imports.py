"""`charpente import cmake` -- turn a CMake project into a `.charpente` file, with a report of what could not be translated."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from ..importers import cmake as cmake_import
from ..lint import lint_source
from ._common import CommandError


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente import", description="Import a project from another build system.")
    sub = parser.add_subparsers(dest="source", required=True)
    cm = sub.add_parser("cmake", help="Import a CMake project (asks CMake itself, through its File API)")
    cm.add_argument("folder", nargs="?", default=".", help="The folder with CMakeLists.txt (default: here)")
    cm.add_argument("--out", help="Where to write the .charpente file (default: <folder>/<name>.charpente)")
    cm.add_argument("--force", action="store_true", help="Overwrite the output file if it exists")
    cm.add_argument("--build-dir", help="Use this folder for CMake's configuration (kept); default: a temporary one")
    cm.add_argument("--cmake", default="cmake", help="The cmake program to use")
    cm.add_argument("--cmake-arg", action="append", default=[], metavar="ARG", help="An argument for the CMake configuration, e.g. -DWITH_X=ON (repeatable)")
    cm.add_argument("--print", action="store_true", dest="print_only", help="Print the result instead of writing a file")
    parsed = parser.parse_args(args)

    folder = Path(parsed.folder).resolve()
    imported = cmake_import.import_project(folder, out_build=Path(parsed.build_dir) if parsed.build_dir else None, cmake=parsed.cmake, args=parsed.cmake_arg)
    text = cmake_import.render(imported)
    problems = [i for i in lint_source(text) if i.severity == "error"]
    if problems:
        raise CommandError("CH8026", detail="the generated file does not pass the DSL lint: " + "; ".join(f"line {i.line}: {i.message}" for i in problems[:3]))
    if parsed.print_only:
        print(text, end="")
        return 0
    target = Path(parsed.out) if parsed.out else folder / f"{imported.name}.charpente"
    if target.exists() and not parsed.force:
        raise CommandError("CH8026", detail=f"{target} already exists (use --force to overwrite it, or --out to write elsewhere)")
    target.write_text(text, encoding="utf-8")
    translated = len(imported.targets)
    print(f"Wrote {target}: {translated} target(s).")
    print("Not translated / to check:")
    for item in imported.report:
        print(f"  - {item}")
    print("Next: `charpente lint`, then `charpente build`.")
    return 0
