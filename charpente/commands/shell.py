"""`charpente shell` -- a terminal (or one command) where the project's toolchain is the one on PATH."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import List

from .. import shellenv
from ..core import process
from ._common import CommandError, find_root, toolchain_for


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="charpente shell",
        description="Open a shell (or run one command) with the project's toolchain on PATH and CC/CXX/AR set to it.")
    parser.add_argument("--platform", help="Target platform (e.g. wasm32-wasi): the shell gets that cross toolchain")
    parser.add_argument("--toolchain", help="Toolchain to use (default: the platform's best)")
    parser.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    parser.add_argument("--print-env", action="store_true", help="Print the variables instead of starting a shell")
    parser.add_argument("--format", choices=shellenv.FORMATS, help="Format of --print-env (default: your shell's)")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Run this command instead of an interactive shell (after --)")
    parsed = parser.parse_args(args)

    command = parsed.command[1:] if parsed.command[:1] == ["--"] else parsed.command
    _target_os, toolchain = toolchain_for(parsed)
    changes = shellenv.overrides(toolchain, os.environ, root=find_root(), config=parsed.config,
                                 platform_name=toolchain.target or parsed.platform or "")
    if parsed.print_env:
        print(shellenv.render(changes, parsed.format or shellenv.default_format()))
        return 0

    env = dict(os.environ)
    env.update(changes)
    if command:
        program = shutil.which(command[0], path=env.get("PATH") or env.get("Path"))
        if program is None:
            raise CommandError("CH8017", detail=f"{command[0]!r} was not found on the shell's PATH")
        argv = [program, *command[1:]]
    else:
        argv = shellenv.find_shell(env)
        if not argv:
            raise CommandError("CH8017", detail="no shell was found (SHELL is not set and neither bash nor sh is on PATH)")
        print(f"charpente shell: {toolchain.name}" + (f" for {toolchain.target}" if toolchain.target else "")
              + " -- type `exit` to leave.", file=sys.stderr)
    return process.run(argv, capture=False, env=env).returncode
