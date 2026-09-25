"""`charpente lint`, `charpente migrate`, `charpente options` -- looking at a workspace
file without building anything."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import List

from ..errors import ChError
from ..lint import lint_source
from ..migrate import migrate_source
from ..workspace_finder import find_workspace_file
from ._common import load


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente lint",
                                     description="Check a .charpente file for likely mistakes, without running it.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings too")
    parsed = parser.parse_args(args)

    path = find_workspace_file(explicit=parsed.file)
    if path.suffix.lower() == ".toml":
        load(str(path))                                 # the parser reports every problem itself
        print(f"{path.name}: valid.")
        return 0
    issues = lint_source(path.read_text(encoding="utf-8-sig"))
    for issue in issues:
        print(f"{path.name}:{issue.line}: {issue.severity} [{issue.code}] {issue.message}")
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = len(issues) - errors
    print(f"{path.name}: {errors} error(s), {warnings} warning(s). (The file was analysed, not run.)")
    return 1 if errors or (parsed.strict and warnings) else 0


def execute_migrate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente migrate",
                                     description="Rewrite v0.1.0 idioms as DSL v2 (shows a diff; --write applies it).")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--write", action="store_true", help="Apply the changes (keeps a .bak copy)")
    parsed = parser.parse_args(args)

    path = find_workspace_file(explicit=parsed.file)
    if path.suffix.lower() == ".toml":
        raise ChError("CH4005", usage="charpente migrate rewrites .charpente files; charpente.toml needs no migration.")
    old = path.read_text(encoding="utf-8-sig")
    result = migrate_source(old)
    if not result.changed:
        print(f"{path.name}: nothing to migrate.")
        return 0
    print(result.diff(path.name, old))
    for change in result.changes:
        print(f"  - {change}")
    if not parsed.write:
        print("\nDry run. Repeat with --write to apply.")
        return 0
    backup = Path(str(path) + ".bak")
    shutil.copyfile(path, backup)
    path.write_text(result.new_source, encoding="utf-8")
    print(f"\nWritten. The previous version is in {backup.name}.")
    return 0


def execute_options(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente options", description="List the workspace's options.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--opt", action="append", default=[], metavar="NAME=VALUE")
    parsed = parser.parse_args(args)
    workspace = load(parsed.file, parsed.opt)
    if not workspace.options:
        print("This workspace declares no options (see ws.option(...)).")
        return 0
    for name, spec in sorted(workspace.options.items()):
        value = workspace.option_values.get(name)
        choices = f"  choices: {', '.join(str(c) for c in spec.choices)}" if spec.choices else ""
        print(f"  {name} = {value!r}  ({spec.kind}, default {spec.default!r}){choices}")
        if spec.help:
            print(f"      {spec.help}")
    print("\nSet one with:  charpente build --opt NAME=VALUE")
    return 0
