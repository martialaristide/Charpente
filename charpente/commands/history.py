"""`charpente history` and `charpente diff-build` -- what the last builds did,
and how two of them differ."""
from __future__ import annotations

import argparse
import time
from typing import List

from ..builder import state_dir
from ..core import history
from ..errors import ChError
from ..units import human_size as _human_size
from ._common import load


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente history", description="List recent build sessions.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--limit", type=int, default=15)
    parsed = parser.parse_args(args)

    workspace = load(parsed.file)
    sessions = history.list_sessions(state_dir(workspace) / "history.db", parsed.limit)
    if not sessions:
        print("No build history yet: run `charpente build` first.")
        return 0
    print(f"{'#':>2}  {'session':<14}{'when':<17}{'command':<9}{'config':<8}{'result':<7}{'time':>7}  "
          f"{'run':>4} {'cache':>5} {'fresh':>5} {'warn':>4}")
    for i, s in enumerate(sessions, 1):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(s.started))
        print(f"{i:>2}  {s.id:<14}{when:<17}{s.command:<9}{s.config or '-':<8}{'ok' if s.ok else 'FAIL':<7}"
              f"{s.duration:>6.1f}s  {s.executed:>4} {s.cached:>5} {s.up_to_date:>5} {s.warnings:>4}")
    return 0


def execute_diff(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente diff-build",
                                     description="Compare two build sessions (time, binary size, warnings).")
    parser.add_argument("a", nargs="?", default="previous", help="Older session: id prefix, 'previous', or #")
    parser.add_argument("b", nargs="?", default="latest", help="Newer session: id prefix, 'latest', or #")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parsed = parser.parse_args(args)

    workspace = load(parsed.file)
    db = state_dir(workspace) / "history.db"
    first = history.find_session(db, parsed.a)
    second = history.find_session(db, parsed.b)
    if first is None or second is None:
        raise ChError("CH4005", usage="Need two known sessions; list them with `charpente history`, "
                                      "then `charpente diff-build A B`.")
    diff = history.diff_sessions(db, first, second)

    print(f"A: {first.id} ({first.command}, {first.duration:.1f}s)   B: {second.id} ({second.command}, "
          f"{second.duration:.1f}s)")
    sign = "+" if diff.duration_delta >= 0 else "-"
    print(f"Time: {sign}{abs(diff.duration_delta):.1f}s")
    print(f"Actions run: {first.executed} -> {second.executed}   from cache: {first.cached} -> {second.cached}")
    if diff.artifact_deltas:
        print("Artifact sizes:")
        for path, before, after in diff.artifact_deltas:
            change = after - before
            print(f"  {path}: {_human_size(before)} -> {_human_size(after)} "
                  f"({'+' if change >= 0 else '-'}{_human_size(abs(change))})")
    if diff.slower_actions:
        print("Slower actions:")
        for action, t_before, t_after in diff.slower_actions[:5]:
            print(f"  {action}: {t_before:.2f}s -> {t_after:.2f}s")
    print(f"Warnings: {first.warnings} -> {second.warnings}")
    for file, line, code, message in diff.new_warnings[:10]:
        print(f"  new: {file}:{line} {code} {message}")
    for file, line, code, message in diff.fixed_warnings[:10]:
        print(f"  fixed: {file}:{line} {code} {message}")
    return 0
