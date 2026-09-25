"""Plain-text terminal renderer: an event subscriber, nothing more.

It prints what happens *while* a build runs (progress lines with -v, compiler
warnings). The per-target summary lines (`[ok]`, `[up to date]`, `[FAILED]`)
are printed by the commands from the build result, exactly as in v0.1.0.
"""
from __future__ import annotations

import sys
from typing import Optional, TextIO

from ..events import Event, EventBus, Subscription


class PlainRenderer:
    def __init__(self, bus: EventBus, *, verbose: bool = False, out: Optional[TextIO] = None,
                 err: Optional[TextIO] = None) -> None:
        self._out = out
        self._err = err
        self.verbose = verbose
        self._total = 0
        self._done = 0
        self.subscription: Subscription = bus.subscribe(
            self._on_event, name="terminal",
            types=["graph.analyzed", "action.started", "action.cache_hit", "action.output",
                   "action.failed", "resource.*", "hint.emitted", "bus.dropped"])

    @property
    def out(self) -> TextIO:
        return self._out if self._out is not None else sys.stdout

    @property
    def err(self) -> TextIO:
        return self._err if self._err is not None else sys.stderr

    def _on_event(self, event: Event) -> None:
        p = event.payload
        kind = event.type
        if kind == "graph.analyzed":
            self._total = int(p["actions"])
            self._done = 0
        elif kind == "action.started":
            self._done += 1
            if self.verbose:
                label = p.get("description") or p["action"]
                print(f"  [{self._done}/{self._total}] {label}", file=self.out)
                command = p.get("command")
                if command:
                    print("      " + " ".join(str(c) for c in command), file=self.out)
                for reason in p.get("reasons") or []:
                    print(f"      because: {reason}", file=self.out)
        elif kind == "action.cache_hit":
            self._done += 1
            if self.verbose:
                print(f"  [{self._done}/{self._total}] (cached) {p['action']}", file=self.out)
        elif kind == "action.output":
            # Output of a *successful* action: warnings the developer should still see.
            text = str(p.get("text", "")).rstrip()
            if text:
                print(text, file=self.err)
        elif kind == "hint.emitted":
            print(f"  hint: {p['message']}", file=self.out)
        elif kind == "resource.low_disk":
            print(f"  warning: low disk space on {p['path']}", file=self.err)
        elif kind == "bus.dropped":
            print(f"  note: {p['count']} events were dropped for {p['subscriber']}", file=self.err)
        self.out.flush()
