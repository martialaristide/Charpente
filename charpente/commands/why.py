"""`charpente why <target|file>` -- why would (or did) this be rebuilt?

Without --last it asks the engine, right now, what would run and prints the
reasons: a changed header, a changed flag, a different compiler version, a
deleted output... With --last it reads the history of the previous build.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Optional

from ..builder import state_dir
from ..core import history
from ..core.engine import Engine
from ..core.graph import ActionGraph, path_key
from ..core.planner import plan_workspace
from ..core.state import StateDB
from ..events import EventBus
from ._common import load, toolchain_for_host

MAX_LISTED = 25


def _select(graph: ActionGraph, subject: str, workspace_root: Path, targets: Dict[str, List[str]],
            state: StateDB) -> List[str]:
    """Action ids that `subject` (a target name or a file path) refers to."""
    if subject in targets:
        return list(targets[subject])
    candidates = [Path(subject), workspace_root / subject]
    keys = {path_key(p) for p in candidates}
    chosen: List[str] = []
    for aid, action in graph.actions.items():
        related = {path_key(p) for p in (*action.inputs, *action.outputs)}
        record = state.get_action(aid)
        if record is not None:
            related |= {path_key(p) for p in record.deps}
        if related & keys:
            chosen.append(aid)
    return chosen


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente why",
                                     description="Explain why a target or file is (or was) rebuilt.")
    parser.add_argument("subject", help="A target name, or a source/header/output file")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    parser.add_argument("--last", action="store_true",
                        help="Explain the previous build instead of predicting the next one")
    parsed = parser.parse_args(args)

    workspace = load(parsed.file)
    target_os, toolchain = toolchain_for_host()
    plan = plan_workspace(workspace, toolchain, target_os, config=parsed.config)
    base = state_dir(workspace)

    state = StateDB(base / "state.db")
    try:
        chosen = _select(plan.graph, parsed.subject, workspace.root, plan.target_actions, state)
        if not chosen:
            print(f"Nothing known about {parsed.subject!r}: it is neither a target of this workspace nor a "
                  f"file used by one of its build actions.")
            return 1

        if parsed.last:
            return _explain_last(base / "history.db", chosen, plan.graph)

        engine = Engine(state, EventBus(), root=workspace.root)
        decisions = engine.plan(plan.graph)
    finally:
        state.close()

    stale = [a for a in chosen if not decisions[a].fresh]
    for aid in stale[:MAX_LISTED]:
        action = plan.graph.actions[aid]
        print(f"{aid}  ({action.label()})")
        print("  would be rebuilt:")
        for reason in decisions[aid].reasons:
            print(f"    - {reason}")
    if len(stale) > MAX_LISTED:
        print(f"... and {len(stale) - MAX_LISTED} more stale actions.")
    fresh = len(chosen) - len(stale)
    if not stale:
        print(f"{parsed.subject}: everything is up to date ({len(chosen)} action(s) checked).")
    elif fresh:
        print(f"({fresh} other related action(s) are up to date.)")
    return 0


def _explain_last(db_path: Path, chosen: List[str], graph: ActionGraph) -> int:
    session: Optional[history.SessionInfo] = None
    for candidate in history.list_sessions(db_path, limit=20):
        if candidate.command in ("build", "run", "test", "package"):
            session = candidate
            break
    if session is None:
        print("No build history yet: run a build first.")
        return 1
    rows = {r["action"]: r for r in history.action_rows(db_path, session.id)}
    shown = 0
    for aid in chosen:
        row = rows.get(aid)
        if row is None:
            continue
        shown += 1
        print(f"{aid}: {row['status']} in the last build ({row['duration']:.2f}s)")
        for reason in row["reasons"]:
            print(f"    - {reason}")
    if not shown:
        print(f"Nothing was run for this in the last build ({session.id}): it was up to date.")
    return 0

