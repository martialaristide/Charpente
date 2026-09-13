from __future__ import annotations

import argparse
import subprocess
import sys
from typing import List

from ..builder import build_target
from ._common import CommandError, load, resolve_target, toolchain_for_host


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente run", description="Build (if needed) and run a target.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--target", help="Target to run (default: the only one, if unambiguous)")
    parser.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    parser.add_argument("--no-build", action="store_true", help="Skip the build step")
    parser.add_argument("program_args", nargs=argparse.REMAINDER,
                        help="Arguments forwarded to the program")
    parsed = parser.parse_args(args)

    workspace = load(parsed.file)
    target = resolve_target(workspace, parsed.target)
    target_os, toolchain = toolchain_for_host()

    if not parsed.no_build:
        result = build_target(workspace, target, toolchain, target_os, config=parsed.config)
        if not result.ok:
            print(f"charpente: build failed: {result.error}")
            return 1
        output = result.output_path
    else:
        from ..builder import build_dir  # internal helper, fine to reach for within the package
        from .. import flags
        output = build_dir(workspace, parsed.config, target) / flags.output_filename(target, target_os, toolchain)
        if not output.exists():
            raise CommandError(f"{output} does not exist. Build first (drop --no-build).")

    print(f"Running {output}...")
    sys.stdout.flush()  # otherwise the child's own output can print before this line does
    completed = subprocess.run([str(output), *parsed.program_args], shell=False)
    return completed.returncode
