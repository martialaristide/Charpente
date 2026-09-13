from __future__ import annotations

import argparse
import subprocess
from typing import List

from ..builder import build_workspace, dependency_closure
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
        # Build the test target's dependency_closure(), not just the target
        # itself -- see run.py's execute() for why.
        closure = dependency_closure(workspace, target.name)
        workspace_result = build_workspace(workspace, toolchain, target_os,
                                           config=parsed.config, only=closure)
        target_result = workspace_result.target(target.name)
        if target_result is None or not target_result.ok:
            error = target_result.error if target_result else "unknown target build failure"
            print(f"  [BUILD FAILED] {target.name}: {error}")
            failures.append(target.name)
            continue

        run_result = subprocess.run([str(target_result.output_path)], shell=False)
        if run_result.returncode == 0:
            print(f"  [PASS] {target.name}")
        else:
            print(f"  [FAIL] {target.name} (exit code {run_result.returncode})")
            failures.append(target.name)

    total = len(test_targets)
    passed = total - len(failures)
    print(f"\n{passed}/{total} test target(s) passed.")
    return 0 if not failures else 1
