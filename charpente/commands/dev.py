"""`charpente dev` -- watch the sources, rebuild on every change, and publish plugin builds for hot reload (experimental)."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List, Optional

from .. import dev as dev_mod
from ..builder import build_workspace
from ..dsl.model import Workspace
from ..errors import ChError
from ..workspace_finder import find_workspace_file
from ._common import load, toolchain_for
from ._session import Session, add_engine_args
from .build import print_result_lines


def _build_once(parsed: argparse.Namespace, workspace: Workspace, hot_dir: Path, only: Optional[List[str]], changed: List[str]) -> bool:
    target_os, toolchain = toolchain_for(parsed, workspace)
    begun = time.monotonic()
    with Session("dev", parsed, workspace, toolchain=toolchain.name, config=parsed.config) as session:
        result = build_workspace(workspace, toolchain, target_os, config=parsed.config, only=only, keep_going=True, jobs=parsed.jobs, bus=session.bus,
                                 use_cache=not parsed.no_cache, eco=getattr(parsed, "eco", False))
        print_result_lines(session, result, toolchain_name=toolchain.name)
        session.bus.emit("dev.rebuilt", changed=[str(Path(c).name) for c in changed], ok=result.ok, duration=time.monotonic() - begun)
        if result.ok:
            for name in dev_mod.plugin_targets(workspace, only):
                built = result.target(name)
                if built is None or built.output_path is None or not built.output_path.is_file():
                    continue
                published = dev_mod.publish(hot_dir, name, built.output_path)
                session.bus.emit("dev.plugin_published", target=name, generation=published.generation, path=str(published.path))
                if not session.machine:
                    print(f"  [hot]        {name}: generation {published.generation} published ({hot_dir / (name + '.json')})")
        session.flush()
        session.finish(result.ok, 0 if result.ok else 1)
    return result.ok


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente dev", description="Rebuild when files change; publish plugin builds for hot reload (experimental).")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--target", action="append", default=[], help="Only build these targets (and what they need); repeatable")
    parser.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    parser.add_argument("--hot-dir", help="Where plugin generations and manifests go (default: build/hot)")
    parser.add_argument("--poll", type=float, default=0.5, help="Seconds between checks for changes (default 0.5)")
    parser.add_argument("--cycles", type=int, default=0, help="Stop after this many rebuilds caused by changes (default: run until Ctrl+C)")
    parser.add_argument("--no-initial-build", action="store_true", help="Wait for the first change instead of building now")
    add_engine_args(parser)
    parsed = parser.parse_args(args)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)                  # a long-running loop must show progress when its output is a pipe

    workspace = load(parsed.file, parsed.opt)
    entry = find_workspace_file(explicit=parsed.file)
    only = parsed.target or None
    hot_dir = Path(parsed.hot_dir).resolve() if parsed.hot_dir else Path(workspace.root) / "build" / "hot"
    plugins = dev_mod.plugin_targets(workspace, only)
    print(f"Watching {workspace.name}" + (f"; plugins published to {hot_dir}: {', '.join(plugins)}" if plugins else "; no plugin targets (nothing to hot-reload, rebuilds only)")
          + ". Ctrl+C to stop.", flush=True)
    current = [workspace]                                            # the watched file list follows the workspace as it is reloaded
    watcher = dev_mod.Watcher(lambda: dev_mod.watched_files(current[0], entry, only))          # before the first build: an edit made during it is not lost
    if not parsed.no_initial_build:
        _build_once(parsed, workspace, hot_dir, only, [])
    rebuilds = 0
    try:
        while not parsed.cycles or rebuilds < parsed.cycles:
            time.sleep(parsed.poll)
            changed = watcher.poll()
            if not changed:
                continue
            time.sleep(min(parsed.poll, 0.2))                       # an editor may still be writing several files: let it finish
            changed = sorted(set(changed) | set(watcher.poll()))
            print(f"\nChanged: {', '.join(Path(c).name for c in changed[:6])}" + (f" and {len(changed) - 6} more" if len(changed) > 6 else ""), flush=True)
            if str(entry) in changed:
                try:
                    workspace = current[0] = load(parsed.file, parsed.opt)
                except ChError as exc:
                    print(f"charpente: the workspace file has a problem, still watching: [{exc.code}] {exc.message}", flush=True)
                    continue
                watcher.state = dev_mod.snapshot(dev_mod.watched_files(workspace, entry, only))
            _build_once(parsed, workspace, hot_dir, only, changed)
            rebuilds += 1
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0
