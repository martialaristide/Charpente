"""`charpente tui` -- the terminal interface (needs the optional `textual` package)."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from ..serve.rpc import RpcError
from ..serve.state import ServerState
from ._common import CommandError, find_root


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente tui", description="Terminal interface: targets, builds, tests, quality gate.")
    parser.add_argument("--file", help="The .charpente file (default: found from the current folder)")
    parser.add_argument("--root", help="Project folder (default: found from the current folder)")
    parser.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    parsed = parser.parse_args(args)
    try:
        from ..tui import CharpenteApp
    except ImportError as exc:
        raise CommandError("CH8018") from exc
    state = ServerState(Path(parsed.root).resolve() if parsed.root else find_root(), parsed.file)
    try:
        state.load()
    except RpcError:
        pass                                          # the interface shows the reason and lets you fix it and reload
    CharpenteApp(state, config=parsed.config).run()
    return 0
