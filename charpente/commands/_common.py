"""Shared plumbing for CLI commands: locate + load the workspace, uniform
error handling. Kept out of cli.py so each command stays a small, focused
`execute(args) -> int` function that commands/__init__.py can register."""
from __future__ import annotations

from typing import Optional

from ..dsl.loader import load_workspace
from ..dsl.model import OS, Target, Workspace
from ..errors import ChError
from ..platform import host_os
from ..toolchains import Toolchain, pick_default
from ..workspace_finder import find_workspace_file


class CommandError(ChError):
    """Raised to abort a command with a clean coded message -- cli.py catches
    every ChError at the top level and prints it without a traceback."""


def load(file_arg: Optional[str] = None) -> Workspace:
    """Locate then load the workspace. Errors (missing file, trust refusal,
    a failing .charpente file...) are already coded `ChError`s and propagate."""
    entry = find_workspace_file(explicit=file_arg)
    return load_workspace(str(entry))


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
