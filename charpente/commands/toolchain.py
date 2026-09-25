"""`charpente toolchain list` -- every compiler Charpente can see, and who provided the detector."""
from __future__ import annotations

import argparse
import shutil
from typing import List

from ..core.toolid import ToolIdentities
from ..flags import family
from ..modules.runtime import get_registry
from ..platform import host_os


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente toolchain", description="Inspect the detected toolchains.")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="List detected toolchains")
    parser.parse_args(args)

    target_os = host_os()
    registry = get_registry()
    tools = ToolIdentities()
    found = 0
    first = True
    for extension in registry.all("toolchain"):
        for toolchain in extension.obj.detect(target_os, shutil.which):
            found += 1
            identity = tools.identify(toolchain.cxx_compiler, family(toolchain))
            marker = "*" if first else " "
            first = False
            print(f"{marker} {toolchain.name:<12} {toolchain.cxx_compiler}")
            print(f"    version: {identity.version or 'unknown'}   provided by: {extension.module}")
    if not found:
        print(f"No C/C++ toolchain found for {target_os.value}. Run `charpente doctor` for what to install.")
        return 1
    print("\n* = the default (first in preference order)")
    return 0
