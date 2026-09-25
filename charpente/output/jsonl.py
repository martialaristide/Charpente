"""JSON Lines output: one event per line. Used for `--output jsonl` (scripts,
CI, editors) and for the replayable per-session log under
`build/.charpente/events/`."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO, Any, List, Optional, TextIO

from ..events import Event, EventBus, Subscription

KEEP_SESSIONS = 20


def encode(event: Event) -> str:
    return json.dumps(event.to_dict(), separators=(",", ":"), default=str)


class JsonlStream:
    """Writes every event to an open text stream."""

    def __init__(self, bus: EventBus, stream: Optional[TextIO] = None, *, name: str = "jsonl") -> None:
        self._stream = stream
        self.subscription: Subscription = bus.subscribe(self._write, name=name)

    def _write(self, event: Event) -> None:
        out = self._stream if self._stream is not None else sys.stdout
        out.write(encode(event) + "\n")
        out.flush()


class SessionLog:
    """Writes the session's events to `<events_dir>/<session>.jsonl`, keeping
    only the newest `KEEP_SESSIONS` files."""

    def __init__(self, bus: EventBus, events_dir: Path) -> None:
        self.path = Path(events_dir) / f"{bus.session_id}.jsonl"
        self._handle: Optional[IO[str]] = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._prune(self.path.parent)
            self._handle = open(self.path, "w", encoding="utf-8", buffering=1)
        except OSError:
            self._handle = None           # a read-only tree must not break the build
        self.subscription: Subscription = bus.subscribe(self._write, name="session-log")

    @staticmethod
    def _prune(directory: Path) -> None:
        files = sorted(directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[KEEP_SESSIONS - 1:]:
            try:
                old.unlink()
            except OSError:
                pass

    def _write(self, event: Event) -> None:
        if self._handle is not None:
            self._handle.write(encode(event) + "\n")

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def read_log(path: Path) -> List[Any]:
    """Parse a session log back into dictionaries (used by `charpente replay`)."""
    events: List[Any] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events
