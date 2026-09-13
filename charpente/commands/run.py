from __future__ import annotations

import argparse
import subprocess
import sys
from typing import List

from ..builder import build_workspace, dependency_closure
from ._common import CommandError, load, resolve_target, toolchain_for_host


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente run", description="Build (if needed) and run a target.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--target", help="Target to run (default: the only one, if unambiguous)")
    parser.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    parser.add_argument("--no-build", action="store_true", help="Skip the build step")
    parser.add_argument("program_args", nargs=argparse.REMAINDER,
                        help="Arguments forwarded to the program (put -- before "
                             "any that start with '-', e.g. `charpente run -- --foo`)")
    parsed = parser.parse_args(args)

    # argparse.REMAINDER keeps a leading "--" as a literal token instead of
    # treating it as the separator it's conventionally used as (cargo run --
    # --foo, npm run x -- --foo): without stripping it here, `charpente run
    # -- --foo` would pass "--" itself as the program's first argument.
    program_args = parsed.program_args
    if program_args and program_args[0] == "--":
        program_args = program_args[1:]

    workspace = load(parsed.file)
    target = resolve_target(workspace, parsed.target)
    target_os, toolchain = toolchain_for_host()

    if not parsed.no_build:
        # Build the target AND whatever it depends_on() for this config --
        # not just the target itself. `charpente build` builds the whole
        # workspace in dependency order, but `run` (and `package`, `test`)
        # build one target directly; without pulling in dependencies too, a
        # config that's never been through `charpente build` before would
        # try to link against a dependency library that doesn't exist yet
        # for that config.
        closure = dependency_closure(workspace, target.name)
        build_result = build_workspace(workspace, toolchain, target_os,
                                       config=parsed.config, only=closure)
        target_result = build_result.target(target.name)
        if target_result is None or not target_result.ok:
            error = target_result.error if target_result else "unknown target build failure"
            print(f"charpente: build failed: {error}")
            return 1
        output = target_result.output_path
    else:
        from ..builder import build_dir  # internal helper, fine to reach for within the package
        from .. import flags
        output = build_dir(workspace, parsed.config, target) / flags.output_filename(target, target_os, toolchain)
        if not output.exists():
            raise CommandError(f"{output} does not exist. Build first (drop --no-build).")

    print(f"Running {output}...")
    sys.stdout.flush()  # otherwise the child's own output can print before this line does
    completed = subprocess.run([str(output), *program_args], shell=False)
    return completed.returncode
