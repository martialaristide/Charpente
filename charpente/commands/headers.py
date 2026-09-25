"""`charpente headers` -- which headers are the most expensive to touch?"""
from __future__ import annotations

import argparse
from typing import List

from ..builder import state_dir
from ..core.analysis import header_costs
from ..core.state import StateDB
from ._common import load


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="charpente headers",
        description="Rank headers by how much work changing them causes (from the last build's records).")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--top", type=int, default=15)
    parsed = parser.parse_args(args)

    workspace = load(parsed.file)
    db = state_dir(workspace) / "state.db"
    if not db.exists():
        print("No build records yet: run `charpente build` first.")
        return 0
    state = StateDB(db)
    try:
        costs = header_costs(state.records())
    finally:
        state.close()
    if not costs:
        print("No project headers were recorded (the last build used no headers outside the compiler's own).")
        return 0

    root = str(workspace.root)
    print(f"{'header':<60} {'included by':>12} {'rebuild cost':>13}")
    for cost in costs[:parsed.top]:
        shown = cost.path[len(root) + 1:] if cost.path.startswith(root) else cost.path
        if len(shown) > 58:
            shown = "..." + shown[-55:]
        print(f"{shown:<60} {cost.includers:>9} files {cost.rebuild_seconds:>10.1f} s")
    print("\nCost = total time of the compilations that would rerun if that header changed.")
    return 0
