from __future__ import annotations

import argparse
import time
from typing import List, Set

from ..builder import build_workspace, dependency_closure
from ..core import process
from ..dsl.model import Kind
from ._common import load, toolchain_for_host
from ._session import Session, add_engine_args


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente test", description="Build and run test targets.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    parser.add_argument("--retries", type=int, default=0, metavar="N",
                        help="Re-run a failing test up to N times; one that then passes is reported "
                             "as FLAKY (it failed and passed with no change in between)")
    add_engine_args(parser, output=False)
    parsed = parser.parse_args(args)

    workspace = load(parsed.file)
    target_os, toolchain = toolchain_for_host()

    test_targets = [t for t in workspace.targets.values() if t.kind == Kind.TEST]
    if not test_targets:
        print("No test targets in this workspace (declare one with .kind(Kind.TEST)).")
        return 0

    # One build for all test targets and what they depend on (see run.py's
    # execute() for why the dependency closure is needed): independent test
    # targets build in parallel, and one failing does not hide the others.
    needed: Set[str] = set()
    for target in test_targets:
        needed |= dependency_closure(workspace, target.name)

    failures: List[str] = []
    flaky: List[str] = []
    with Session("test", parsed, workspace, toolchain=toolchain.name, config=parsed.config) as session:
        built = build_workspace(workspace, toolchain, target_os, config=parsed.config, only=needed,
                                keep_going=True, jobs=parsed.jobs, bus=session.bus,
                                use_cache=not parsed.no_cache)
        session.flush()
        if built.interrupted:
            raise KeyboardInterrupt

        for target in test_targets:
            target_result = built.target(target.name)
            if target_result is None or not target_result.ok or target_result.output_path is None:
                error = target_result.error if target_result else "unknown target build failure"
                print(f"  [BUILD FAILED] {target.name}: {error}")
                failures.append(target.name)
                continue

            session.bus.emit("test.started", target=target.name)
            begin = time.monotonic()
            code = process.run([str(target_result.output_path)], capture=False).returncode
            attempts = 0
            while code != 0 and attempts < parsed.retries:
                attempts += 1
                code = process.run([str(target_result.output_path)], capture=False).returncode
            elapsed = time.monotonic() - begin
            if code == 0 and attempts:
                flaky.append(target.name)
                session.bus.emit("test.flaky_detected", target=target.name)
                print(f"  [FLAKY] {target.name} (passed after {attempts} retr{'y' if attempts == 1 else 'ies'})")
                session.bus.emit("test.passed", target=target.name, duration=elapsed)
            elif code == 0:
                print(f"  [PASS] {target.name}")
                session.bus.emit("test.passed", target=target.name, duration=elapsed)
            else:
                print(f"  [FAIL] {target.name} (exit code {code})")
                session.bus.emit("test.failed", target=target.name, exit_code=code, duration=elapsed)
                failures.append(target.name)

        session.flush()
        total = len(test_targets)
        passed = total - len(failures)
        print(f"\n{passed}/{total} test target(s) passed.")
        if flaky:
            print(f"{len(flaky)} flaky: {', '.join(flaky)} -- fix or quarantine them, they hide real failures.")
        result = 0 if not failures else 1
        session.finish(not failures, result)
    return result
