"""A progress display built on the optional `rich` package.

Shows one live bar for the whole build with the action currently running.
The commands print the per-target result lines afterwards, exactly as with the
plain renderer; `finish()` stops the live area first so nothing interleaves.
"""
from __future__ import annotations

import os
import sys
import threading
from typing import Any, Optional, TextIO

from ..errors import ChError
from ..events import Event, EventBus, Subscription


def available() -> bool:
    try:
        import rich  # noqa: F401
    except ImportError:
        return False
    return True


def wanted_by_default(stream: Optional[TextIO] = None) -> bool:
    """`--output auto` uses rich only on an interactive terminal with rich installed."""
    out = stream or sys.stdout
    try:
        tty = out.isatty()
    except (AttributeError, ValueError):
        tty = False
    if not tty or os.environ.get("CI") or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    return available()


class RichRenderer:
    def __init__(self, bus: EventBus, *, console: Any = None) -> None:
        try:
            from rich.console import Console
            from rich.progress import (
                BarColumn,
                MofNCompleteColumn,
                Progress,
                SpinnerColumn,
                TextColumn,
                TimeElapsedColumn,
            )
        except ImportError as exc:
            raise ChError("CH4006", package="rich", extra="rich") from exc
        self._console = console or Console(stderr=False)
        self._progress = Progress(
            SpinnerColumn(), TextColumn("[bold]{task.fields[what]}", justify="left"), BarColumn(),
            MofNCompleteColumn(), TimeElapsedColumn(), console=self._console, transient=True)
        self._task: Any = None
        self._lock = threading.Lock()
        self._running = False
        self.subscription: Subscription = bus.subscribe(
            self._on_event, name="rich",
            types=["graph.analyzed", "action.started", "action.cache_hit", "action.up_to_date", "action.finished",
                   "action.failed", "action.output", "hint.emitted", "session.finished"])

    def _start(self, total: int) -> None:
        if not self._running:
            self._progress.start()
            self._running = True
        self._task = self._progress.add_task("build", total=total, what="starting")

    def _on_event(self, event: Event) -> None:
        p = event.payload
        with self._lock:
            kind = event.type
            if kind == "graph.analyzed":
                if int(p["actions"]) > 0:
                    self._start(int(p["actions"]))
            elif kind == "action.started" and self._task is not None:
                self._progress.update(self._task, what=str(p.get("description") or p["action"])[:60])
            elif kind in ("action.finished", "action.cache_hit", "action.up_to_date", "action.failed") \
                    and self._task is not None:
                self._progress.advance(self._task)
            elif kind == "action.output":
                text = str(p.get("text", "")).rstrip()
                if text:
                    self._progress.console.print(text, markup=False, highlight=False)
            elif kind == "hint.emitted":
                self._progress.console.print(f"[yellow]hint:[/yellow] {p['message']}")
            elif kind == "session.finished":
                self._stop()

    def _stop(self) -> None:
        if self._running:
            self._progress.stop()
            self._running = False

    def finish(self) -> None:
        """Stop the live area (idempotent) so the caller can print normally."""
        with self._lock:
            self._stop()
