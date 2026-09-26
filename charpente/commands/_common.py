"""Shared plumbing for CLI commands: locate + load the workspace, uniform
error handling. Kept out of cli.py so each command stays a small, focused
`execute(args) -> int` function that commands/__init__.py can register."""
from __future__ import annotations

import argparse
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


def load(file_arg: Optional[str] = None, opts: Optional[List[str]] = None, *,
         materialize_packages: bool = True) -> Workspace:
    """Locate then load the workspace (`--opt name=value` sets workspace options).
    Errors (missing file, trust refusal, a failing .charpente file...) are already
    coded `ChError`s and propagate."""
    entry = find_workspace_file(explicit=file_arg)
    _lint_before_running(entry)
    workspace = load_workspace(str(entry), options=parse_options(opts) or None)
    if materialize_packages and workspace.requires:
        from ..pkg.materialize import materialize

        materialize(workspace)          # offline: adds a target per locked package (CH6005 if not installed)
    return workspace


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


def android_min_sdk(workspace: Optional[Workspace]) -> Optional[int]:
    """The highest `min_sdk` any target declares for Android: the API level everything is compiled against."""
    if workspace is None:
        return None
    levels = []
    for target in workspace.targets.values():
        for settings in [target.platform_settings, *[o.platform_settings for o in target.overlays]]:
            value = settings.get("android", {}).get("min_sdk")
            if isinstance(value, int):
                levels.append(value)
    return max(levels) if levels else None


def toolchain_for(parsed: argparse.Namespace, workspace: Optional[Workspace] = None) -> "tuple[OS, Toolchain]":
    """(target OS, toolchain) for `--platform` / `--toolchain` (native build when neither is given)."""
    from .. import cross

    target_os, toolchain = cross.select(getattr(parsed, "platform", None), getattr(parsed, "toolchain", None),
                                        android_api=android_min_sdk(workspace))
    if toolchain.target:
        from .. import platforms

        warning = platforms.warning_for(platforms.get(toolchain.target))
        if warning:
            print(f"charpente: warning: {warning}", file=sys.stderr)
    return target_os, toolchain


def program_argv(toolchain: Toolchain, output: "Path | str", args: "List[str] | None" = None) -> List[str]:
    """The command that runs a built program: directly when it is native, through the platform's
    runtime (wasmtime, node) when it is not, or CH8004 when this machine cannot run it."""
    if not toolchain.target:
        return [str(output), *(args or [])]
    from .. import platforms, runners

    return runners.command(str(output), toolchain.target, platforms.host(), program_args=list(args or []))


def toolchain_for_host() -> "tuple[OS, Toolchain]":
    target_os = host_os()
    return target_os, pick_default(target_os)


def resolve_target(workspace: Workspace, name: Optional[str]) -> Target:
    own = {n: t for n, t in workspace.targets.items() if not t.external}   # packages are never the default
    if name:
        if name not in workspace.targets:
            raise CommandError("CH1008", name=name, workspace=workspace.name,
                               known=", ".join(sorted(workspace.targets)) or "(none)")
        return workspace.targets[name]
    if len(own) == 1:
        return next(iter(own.values()))
    if not own:
        raise CommandError("CH1010", workspace=workspace.name)
    raise CommandError("CH1009", workspace=workspace.name, count=len(own), known=", ".join(sorted(own)))
