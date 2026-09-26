from __future__ import annotations

import argparse
from typing import List

from ..builder import BuildResult, build_workspace
from ._common import load, toolchain_for
from ._session import Session, add_engine_args


def print_result_lines(session: Session, result: BuildResult, *, ai_diagnose: bool = False,
                       toolchain_name: str = "") -> None:
    """The per-target lines shown after a build (unchanged since v0.1.0), then a one-line summary."""
    session.flush()
    if session.machine:
        return
    for t in result.targets:
        if t.skipped:
            print(f"  [up to date] {t.target_name}")
        elif t.ok:
            print(f"  [ok]         {t.target_name} -> {t.output_path}")
        else:
            print(f"  [FAILED]     {t.target_name}: {t.error}")
            if ai_diagnose:
                _print_ai_diagnosis(t.target_name, toolchain_name, t.error)
    counts = {"executed": 0, "cached": 0, "up_to_date": 0}
    for t in result.targets:
        counts["executed"] += t.executed
        counts["cached"] += t.cached
        counts["up_to_date"] += t.up_to_date
    if result.interrupted:
        print("Build interrupted.")
    elif any(counts.values()):
        print(f"Done in {result.duration:.1f}s: {counts['executed']} run, {counts['cached']} from cache, "
              f"{counts['up_to_date']} up to date.")


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente build", description="Compile the workspace.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    parser.add_argument("--keep-going", action="store_true",
                        help="Keep building unrelated targets after a failure")
    parser.add_argument("--ai-diagnose", action="store_true",
                        help="On failure, ask the configured AI provider to diagnose the error "
                             "(never automatic: costs a request and sends the error text to "
                             "whichever provider is configured)")
    add_engine_args(parser)
    parsed = parser.parse_args(args)

    workspace = load(parsed.file, parsed.opt)
    target_os, toolchain = toolchain_for(parsed, workspace)

    with Session("build", parsed, workspace, toolchain=toolchain.name, config=parsed.config) as session:
        session.say(f"Building {workspace.name} ({parsed.config}, {toolchain.name})...")
        result = build_workspace(workspace, toolchain, target_os, config=parsed.config,
                                 keep_going=parsed.keep_going, jobs=parsed.jobs, bus=session.bus,
                                 use_cache=not parsed.no_cache)
        print_result_lines(session, result, ai_diagnose=parsed.ai_diagnose, toolchain_name=toolchain.name)
        code = 130 if result.interrupted else (0 if result.ok else 1)
        session.finish(result.ok, code)
    return code


def _print_ai_diagnosis(target_name: str, toolchain_name: str, error_text: str) -> None:
    from ..ai import diagnose, select_provider

    provider = select_provider()
    print(f"               (asking {provider.name} to diagnose...)")
    print("               " + diagnose(
        provider, target_name=target_name, toolchain_name=toolchain_name, error_text=error_text
    ).replace("\n", "\n               "))
