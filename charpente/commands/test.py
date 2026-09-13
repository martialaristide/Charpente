from __future__ import annotations

import argparse
import subprocess
from typing import List

from ..builder import build_target
from ..dsl.model import Kind
from ._common import load, toolchain_for_host


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente test", description="Build and run test targets.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    parsed = parser.parse_args(args)

    workspace = load(parsed.file)
    target_os, toolchain = toolchain_for_host()

    test_targets = [t for t in workspace.targets.values() if t.kind == Kind.TEST]
    if not test_targets:
        print("No test targets in this workspace (declare one with .kind(Kind.TEST)).")
        return 0

    failures = []
    for target in test_targets:
        build_result = build_target(workspace, target, toolchain, target_os, config=parsed.config)
        if not build_result.ok:
            print(f"  [BUILD FAILED] {target.name}: {build_result.error}")
            failures.append(target.name)
            continue

        run_result = subprocess.run([str(build_result.output_path)], shell=False)
        if run_result.returncode == 0:
            print(f"  [PASS] {target.name}")
        else:
            print(f"  [FAIL] {target.name} (exit code {run_result.returncode})")
            failures.append(target.name)

    total = len(test_targets)
    passed = total - len(failures)
    print(f"\n{passed}/{total} test target(s) passed.")
    return 0 if not failures else 1
