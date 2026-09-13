"""Shared plumbing for CLI commands: locate + load the workspace, uniform
error handling. Kept out of cli.py so each command stays a small, focused
`execute(args) -> int` function that commands/__init__.py can register."""
from __future__ import annotations

from typing import Optional

from ..dsl.loader import WorkspaceLoadError, load_workspace
from ..dsl.model import OS, Workspace
from ..dsl.trust import TrustDeniedError, TrustRequiredError
from ..toolchains import NoToolchainFoundError, Toolchain, pick_default
from ..platform import host_os
from ..workspace_finder import (
    AmbiguousWorkspaceError,
    WorkspaceNotFoundError,
    find_workspace_file,
)


class CommandError(Exception):
    """Raised to abort a command with a clean one-line message -- cli.py
    catches this at the top level and prints it without a traceback."""


def load(file_arg: Optional[str] = None) -> Workspace:
    try:
        entry = find_workspace_file(explicit=file_arg)
    except (WorkspaceNotFoundError, AmbiguousWorkspaceError) as e:
        raise CommandError(str(e)) from e
    try:
        return load_workspace(str(entry))
    except (TrustDeniedError, TrustRequiredError, WorkspaceLoadError) as e:
        raise CommandError(str(e)) from e


def toolchain_for_host() -> "tuple[OS, Toolchain]":
    target_os = host_os()
    try:
        return target_os, pick_default(target_os)
    except NoToolchainFoundError as e:
        raise CommandError(str(e)) from e


def resolve_target(workspace: Workspace, name: Optional[str]):
    if name:
        if name not in workspace.targets:
            raise CommandError(f"No target named {name!r} in workspace {workspace.name!r}. "
                               f"Known targets: {', '.join(sorted(workspace.targets)) or '(none)'}")
        return workspace.targets[name]
    if len(workspace.targets) == 1:
        return next(iter(workspace.targets.values()))
    if not workspace.targets:
        raise CommandError(f"Workspace {workspace.name!r} has no targets to run.")
    raise CommandError(
        f"Workspace {workspace.name!r} has {len(workspace.targets)} targets; "
        f"specify one with --target. Known targets: {', '.join(sorted(workspace.targets))}"
    )
