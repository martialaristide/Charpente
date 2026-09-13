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
    parser.add_argument("--ai-diagnose", action="store_true",
                        help="On failure, ask the configured AI provider to diagnose the error "
                             "(never automatic: costs a request and sends the error text to "
                             "whichever provider is configured)")
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
            if parsed.ai_diagnose:
                _print_ai_diagnosis(t.target_name, toolchain.name, t.error)
    return 0 if result.ok else 1


def _print_ai_diagnosis(target_name: str, toolchain_name: str, error_text: str) -> None:
    from ..ai import diagnose, select_provider

    provider = select_provider()
    print(f"               (asking {provider.name} to diagnose...)")
    print("               " + diagnose(
        provider, target_name=target_name, toolchain_name=toolchain_name, error_text=error_text
    ).replace("\n", "\n               "))
