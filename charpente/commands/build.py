from __future__ import annotations

import argparse
from typing import List

from ..builder import build_workspace
from ._common import CommandError, load, toolchain_for_host


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente build", description="Compile the workspace.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    parser.add_argument("--keep-going", action="store_true",
                        help="Keep building unrelated targets after a failure")
    parsed = parser.parse_args(args)

    workspace = load(parsed.file)
    target_os, toolchain = toolchain_for_host()

    print(f"Building {workspace.name} ({parsed.config}, {toolchain.name})...")
    result = build_workspace(workspace, toolchain, target_os,
                             config=parsed.config, keep_going=parsed.keep_going)
    for t in result.targets:
        if t.skipped:
            print(f"  [up to date] {t.target_name}")
        elif t.ok:
            print(f"  [ok]         {t.target_name} -> {t.output_path}")
        else:
            print(f"  [FAILED]     {t.target_name}: {t.error}")
    return 0 if result.ok else 1
