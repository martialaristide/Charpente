"""`charpente platforms` -- what can be built for, with its support tier and whether this machine can do it now."""
from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from .. import cross, platforms, toolchains
from ..errors import ChError
from ..platform import host_os


def _availability(platform: platforms.Platform, host: platforms.Platform, detected: List[toolchains.Toolchain]) -> str:
    """'native', the name of a toolchain that can cross-build it, or ''."""
    if platform.name == host.name:
        return "native" if detected else ""
    for toolchain in detected:
        if cross.can_target(toolchain, platform):
            return toolchain.name
    return ""


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente platforms", description="List target platforms.")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("--family", choices=["desktop", "mobile", "xr", "web", "embedded", "server"],
                        help="Only this family")
    parsed = parser.parse_args(args)

    try:
        host = platforms.host()
    except ChError:
        host = platforms.get("linux-x64")
    detected = toolchains.detect(host_os())
    rows: List[Dict[str, Any]] = []
    for platform in platforms.all_platforms():
        if parsed.family and platform.family != parsed.family:
            continue
        rows.append({"name": platform.name, "tier": platform.tier, "family": platform.family,
                     "buildable_here": _availability(platform, host, detected) or None,
                     "needs": platform.needs or None, "note": platform.note or None})
    if parsed.json:
        print(json.dumps({"host": host.name, "platforms": rows}, indent=1))
        return 0
    print(f"This machine: {host.name}\n")
    print(f"{'PLATFORM':<20} {'TIER':<7} {'FAMILY':<9} BUILDABLE HERE")
    for row in rows:
        here = row["buildable_here"] or ("-  needs " + row["needs"] if row["needs"] else "-  needs a cross toolchain "
                                          "(`charpente toolchain install zig`)")
        print(f"{row['name']:<20} Tier {row['tier']:<2} {row['family']:<9} {here}")
    print("\nTier 1: built and tested in CI. Tier 2: built in CI, tested occasionally. "
          "Tier 3: supported through a module, no CI guarantee.")
    return 0
