"""A command's session: the event bus, its subscribers and the session
start/finish events, in one place so every build-like command behaves alike.

Subscribers attached here:

* the terminal renderer (`--output plain`, default) or JSON Lines on stdout
  (`--output jsonl`, for scripts and editors);
* the replayable per-session log `build/.charpente/events/<session>.jsonl`;
* the build history database (`charpente history`, `charpente diff-build`).
"""
from __future__ import annotations

import argparse
import sys
import time
from types import TracebackType
from typing import Any, Optional, Type

from .. import _version
from ..builder import state_dir
from ..core.history import HistoryRecorder
from ..dsl.model import Workspace
from ..events import EventBus
from ..output import JsonlStream, PlainRenderer, SessionLog

OUTPUT_MODES = ("plain", "jsonl")


def add_engine_args(parser: argparse.ArgumentParser, *, output: bool = True) -> None:
    parser.add_argument("-j", "--jobs", type=int, default=0, metavar="N",
                        help="Maximum parallel actions (default: one per CPU)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Do not read or write the content cache")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show every command that runs, and why")
    if output:
        parser.add_argument("--output", choices=OUTPUT_MODES, default="plain",
                            help="'plain' (default) for people, 'jsonl' for scripts (one JSON event per line)")


class Session:
    def __init__(self, command: str, parsed: argparse.Namespace, workspace: Optional[Workspace] = None,
                 *, toolchain: str = "", config: str = "") -> None:
        self.command = command
        self.machine = getattr(parsed, "output", "plain") == "jsonl"
        self.bus = EventBus()
        self._started = time.monotonic()
        self._closed = False
        self.log: Optional[SessionLog] = None
        self.history: Optional[HistoryRecorder] = None
        if self.machine:
            JsonlStream(self.bus, sys.stdout)
        else:
            PlainRenderer(self.bus, verbose=bool(getattr(parsed, "verbose", False)))
        if workspace is not None and workspace.location is not None:
            base = state_dir(workspace)
            self.log = SessionLog(self.bus, base / "events")
            self.history = HistoryRecorder(self.bus, base / "history.db", command=command, config=config,
                                           toolchain=toolchain)
        self.bus.emit("session.started", command=command, argv=list(sys.argv[1:]),
                      cwd=str(workspace.location if workspace and workspace.location else ""),
                      version=_version.__version__)
        if workspace is not None:
            self.bus.emit("workspace.loaded", name=workspace.name, path=str(workspace.location or ""),
                          targets=len(workspace.targets))

    # ------------------------------------------------------------ lifecycle
    def finish(self, ok: bool, exit_code: Optional[int] = None) -> None:
        if self._closed:
            return
        self._closed = True
        self.bus.emit("session.finished", ok=ok, duration=time.monotonic() - self._started,
                      exit_code=exit_code)
        self.bus.close()
        if self.log is not None:
            self.log.close()

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException],
                 tb: Optional[TracebackType]) -> None:
        if self._closed:
            return
        if exc_type is not None and issubclass(exc_type, KeyboardInterrupt):
            self.bus.emit("session.interrupted", reason="keyboard")
        self.finish(ok=exc_type is None, exit_code=None if exc_type is None else 1)

    # -------------------------------------------------------------- helpers
    def flush(self) -> None:
        """Let the renderers catch up before the caller prints its own lines."""
        self.bus.flush()

    def say(self, text: str = "", **kwargs: Any) -> None:
        """Human-readable line; suppressed in machine output modes."""
        if not self.machine:
            print(text, **kwargs)
