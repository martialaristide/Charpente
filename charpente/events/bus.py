"""The event bus: typed, ordered, and never able to slow a build down.

Every stage of the engine *emits*; the terminal, the JSONL file, the history
database, hooks, notifiers and Studio are all *subscribers*. Nothing prints
directly.

Delivery model
--------------
* `sync=True` subscribers run inline in the emitting thread. They must be
  fast and never block (collectors, counters). Their exceptions are caught.
* the default subscriber is asynchronous: it owns a bounded queue and one
  worker thread, so events reach it in order. If it falls behind, the queue
  fills and further events are **dropped for that subscriber only** (counted
  in `stats()`, reported at close) -- the build never waits.
"""
from __future__ import annotations

import fnmatch
import itertools
import os
import queue
import threading
import time
import types as pytypes
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from .types import EVENT_TYPES, SCHEMA_VERSION, field_spec

_PY_TYPES: Dict[str, Any] = {
    "str": str, "int": int, "float": (int, float), "bool": bool,
    "list": (list, tuple), "dict": dict, "any": object,
}


@dataclass(frozen=True)
class Event:
    """An immutable event. `payload` must be JSON-serialisable."""

    type: str
    payload: Mapping[str, Any]
    session_id: str
    id: int
    parent_id: Optional[int]
    timestamp: float
    wall_time: float
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "parent_id": self.parent_id,
            "timestamp": self.timestamp,
            "wall_time": self.wall_time,
            "session_id": self.session_id,
            "type": self.type,
            "payload": dict(self.payload),
        }

    @property
    def family(self) -> str:
        return self.type.split(".", 1)[0]


Handler = Callable[[Event], None]


class Subscription:
    """Handle returned by `EventBus.subscribe`."""

    def __init__(self, bus: "EventBus", handler: Handler, name: str, sync: bool,
                 maxsize: int, patterns: Optional[List[str]]) -> None:
        self.bus = bus
        self.handler = handler
        self.name = name
        self.sync = sync
        self.patterns = patterns
        self.dropped = 0
        self.delivered = 0
        self.errors: List[str] = []
        self._queue: "Optional[queue.Queue[Optional[Event]]]" = None
        self._thread: Optional[threading.Thread] = None
        if not sync:
            self._queue = queue.Queue(maxsize=maxsize)
            self._thread = threading.Thread(target=self._pump, name=f"charpente-events-{name}", daemon=True)
            self._thread.start()

    def wants(self, event_type: str) -> bool:
        if self.patterns is None:
            return True
        return any(fnmatch.fnmatchcase(event_type, p) for p in self.patterns)

    def _call(self, event: Event) -> None:
        try:
            self.handler(event)
            self.delivered += 1
        except Exception as exc:  # a broken subscriber must never break the build
            if len(self.errors) < 20:
                self.errors.append(f"{type(exc).__name__}: {exc}")

    def _pump(self) -> None:
        assert self._queue is not None
        while True:
            item = self._queue.get()
            if item is None:
                return
            self._call(item)

    def deliver(self, event: Event) -> None:
        if self.sync:
            self._call(event)
            return
        assert self._queue is not None
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped += 1

    def stop(self, timeout: float) -> None:
        if self._queue is not None and self._thread is not None:
            # A blocking put is fine here: we are closing, not emitting.
            try:
                self._queue.put(None, timeout=timeout)
            except queue.Full:
                return
            self._thread.join(timeout)

    def unsubscribe(self) -> None:
        self.bus._remove(self)


@dataclass
class BusStats:
    emitted: int = 0
    dropped: Dict[str, int] = field(default_factory=dict)
    errors: Dict[str, List[str]] = field(default_factory=dict)


class EventBus:
    def __init__(self, session_id: Optional[str] = None, strict: Optional[bool] = None) -> None:
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.strict = (os.environ.get("CHARPENTE_EVENTS_STRICT") == "1") if strict is None else strict
        self._subs: List[Subscription] = []
        self._lock = threading.RLock()
        self._ids = itertools.count(1)
        self._emitted = 0
        self._closed = False

    # ------------------------------------------------------------ subscribe
    def subscribe(self, handler: Handler, *, name: str = "", sync: bool = False,
                  maxsize: int = 10000, types: Optional[Iterable[str]] = None) -> Subscription:
        """Register `handler`. `types` are fnmatch patterns ('action.*', 'diagnostic.emitted');
        None means every event."""
        sub = Subscription(self, handler, name or getattr(handler, "__name__", "subscriber"), sync,
                           maxsize, list(types) if types is not None else None)
        with self._lock:
            self._subs.append(sub)
        return sub

    def _remove(self, sub: Subscription) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)
        sub.stop(1.0)

    # ----------------------------------------------------------------- emit
    def _validate(self, event_type: str, payload: Mapping[str, Any]) -> None:
        spec = EVENT_TYPES.get(event_type)
        if spec is None:
            raise ValueError(f"unknown event type {event_type!r}")
        for name, raw in spec.items():
            type_name, optional = field_spec(raw)
            if name not in payload:
                if not optional:
                    raise ValueError(f"{event_type}: missing required field {name!r}")
                continue
            value = payload[name]
            if value is None and optional:
                continue
            expected = _PY_TYPES[type_name]
            if type_name == "int" and isinstance(value, bool):
                raise ValueError(f"{event_type}.{name}: expected int, got bool")
            if not isinstance(value, expected):
                raise ValueError(f"{event_type}.{name}: expected {type_name}, got {type(value).__name__}")

    def emit(self, event_type: str, *, parent_id: Optional[int] = None, **payload: Any) -> Event:
        if self.strict:
            self._validate(event_type, payload)
        with self._lock:
            event = Event(
                type=event_type,
                payload=pytypes.MappingProxyType(dict(payload)),
                session_id=self.session_id,
                id=next(self._ids),
                parent_id=parent_id,
                timestamp=time.monotonic(),
                wall_time=time.time(),
            )
            self._emitted += 1
            # Delivered under the lock so every subscriber sees events in id
            # order even when several threads emit at once. Delivery to an
            # async subscriber is a non-blocking queue put; sync subscribers
            # are documented as fast (the lock is re-entrant, so a sync
            # handler may itself emit).
            if not self._closed:
                for sub in self._subs:
                    if sub.wants(event_type):
                        sub.deliver(event)
        return event

    # ---------------------------------------------------------------- close
    def stats(self) -> BusStats:
        with self._lock:
            subs = list(self._subs)
            emitted = self._emitted
        return BusStats(
            emitted=emitted,
            dropped={s.name: s.dropped for s in subs if s.dropped},
            errors={s.name: list(s.errors) for s in subs if s.errors},
        )

    def close(self, timeout: float = 5.0) -> BusStats:
        """Flush every asynchronous subscriber (waiting at most `timeout` each)
        and stop accepting events. Returns the final stats."""
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            sub.stop(timeout)
        stats = self.stats()
        with self._lock:
            self._closed = True
        return stats
