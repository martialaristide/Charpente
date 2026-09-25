"""Shared plumbing for CLI commands: locate + load the workspace, uniform
error handling. Kept out of cli.py so each command stays a small, focused
`execute(args) -> int` function that commands/__init__.py can register."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from ..dsl.loader import load_workspace
from ..dsl.model import OS, Target, Workspace
from ..errors import ChError
from ..lint import lint_source
from ..platform import host_os
from ..toolchains import Toolchain, pick_default
from ..workspace_finder import find_workspace_file


class CommandError(ChError):
    """Raised to abort a command with a clean coded message -- cli.py catches
    every ChError at the top level and prints it without a traceback."""


def parse_options(pairs: Optional[List[str]]) -> Dict[str, str]:
    """`--opt name=value` (repeatable) -> {"name": "value"}."""
    out: Dict[str, str] = {}
    for pair in pairs or []:
        name, sep, value = pair.partition("=")
        if not sep or not name.strip():
            raise CommandError("CH4005", usage=f"--opt expects NAME=VALUE, got {pair!r}")
        out[name.strip()] = value
    return out


def load(file_arg: Optional[str] = None, opts: Optional[List[str]] = None) -> Workspace:
    """Locate then load the workspace (`--opt name=value` sets workspace options).
    Errors (missing file, trust refusal, a failing .charpente file...) are already
    coded `ChError`s and propagate."""
    entry = find_workspace_file(explicit=file_arg)
    _lint_before_running(entry)
    return load_workspace(str(entry), options=parse_options(opts) or None)


def _lint_before_running(entry: Path) -> None:
    """Point out likely mistakes in the file *before* it is executed (the analysis
    only parses it). Advisory and quiet when there is nothing to say;
    CHARPENTE_LINT=0 turns it off."""
    if entry.suffix.lower() == ".toml" or os.environ.get("CHARPENTE_LINT", "1") == "0":
        return
    try:
        issues = lint_source(entry.read_text(encoding="utf-8-sig"))
    except OSError:
        return
    for issue in [i for i in issues if i.severity == "warning" or i.code != "CH1101"][:8]:
        print(f"charpente: {issue.severity} [{issue.code}] {entry.name}:{issue.line}: {issue.message}",
              file=sys.stderr)


def toolchain_for_host() -> "tuple[OS, Toolchain]":
    target_os = host_os()
    return target_os, pick_default(target_os)


def resolve_target(workspace: Workspace, name: Optional[str]) -> Target:
    if name:
        if name not in workspace.targets:
            raise CommandError("CH1008", name=name, workspace=workspace.name,
                               known=", ".join(sorted(workspace.targets)) or "(none)")
        return workspace.targets[name]
    if len(workspace.targets) == 1:
        return next(iter(workspace.targets.values()))
    if not workspace.targets:
        raise CommandError("CH1010", workspace=workspace.name)
    raise CommandError("CH1009", workspace=workspace.name, count=len(workspace.targets),
                       known=", ".join(sorted(workspace.targets)))
