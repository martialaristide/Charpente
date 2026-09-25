"""Reacting to events from a workspace.

Two ways, both driven by the event bus:

* **In the DSL** -- a function decorated with `@ws.on(Event.BUILD_FINISHED)`:

      @ws.on(Event.BUILD_FINISHED)
      def summary(ev):
          notify(f"{ev.targets_built} targets built in {ev.duration:.1f}s")

* **Scripts** in `.charpente/hooks/`, named after an event type
  (`session.finished.py`, `action.failed.sh`...). The event is passed as JSON on
  standard input and in `CHARPENTE_EVENT`. Scripts are code from the repository,
  so they only run once you have approved them (same trust model as a
  `.charpente` file), and never through a shell.

Hooks are advisory: an exception or a failing script is reported on stderr and
can never fail or slow the build (they run on the event bus's own thread).
"""
from __future__ import annotations

import enum
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .core import process
from .errors import ChError
from .events import Event as BusEvent
from .events import EventBus

HOOKS_DIR = Path(".charpente") / "hooks"
SCRIPT_TIMEOUT = 60.0


class Event(enum.Enum):
    """Event names usable in `@ws.on(...)` (each maps to a bus event type)."""

    BUILD_STARTED = "session.started"
    BUILD_FINISHED = "session.finished"
    TARGET_STARTED = "target.started"
    TARGET_FINISHED = "target.finished"
    TARGET_FAILED = "target.failed"
    ACTION_FAILED = "action.failed"
    DIAGNOSTIC = "diagnostic.emitted"
    TEST_PASSED = "test.passed"
    TEST_FAILED = "test.failed"
    HINT = "hint.emitted"
    ANY = "*"


class HookEvent:
    """What a hook function receives: the bus event's fields as attributes, plus
    session totals on `BUILD_FINISHED` (`targets_built`, `targets_failed`,
    `actions_run`, `cache_hits`, `warnings`, `errors`, `duration`, `ok`)."""

    def __init__(self, event: BusEvent, totals: Dict[str, Any]) -> None:
        self.type = event.type
        self.payload = dict(event.payload)
        self.time = event.wall_time
        self.session_id = event.session_id
        self._extra = totals if event.type == "session.finished" else {}

    def __getattr__(self, name: str) -> Any:
        payload = self.__dict__.get("payload", {})
        if name in payload:
            return payload[name]
        extra = self.__dict__.get("_extra", {})
        if name in extra:
            return extra[name]
        raise AttributeError(f"{self.type} has no field {name!r} (has: {', '.join(sorted({**payload, **extra}))})")

    def __repr__(self) -> str:
        return f"<HookEvent {self.type} {self.payload}>"


class HookRunner:
    """Bus subscriber that runs DSL hooks and keeps the session totals."""

    def __init__(self, bus: EventBus, hooks: List[Tuple[Event, Callable[[HookEvent], Any]]],
                 on_error: Optional[Callable[[str], None]] = None) -> None:
        self._hooks = hooks
        self._on_error = on_error or (lambda m: print(f"charpente: hook failed: {m}", file=sys.stderr))
        self._totals: Dict[str, Any] = {"targets_built": 0, "targets_failed": 0, "actions_run": 0,
                                        "cache_hits": 0, "warnings": 0, "errors": 0}
        bus.subscribe(self._on_event, name="dsl-hooks")

    def _on_event(self, event: BusEvent) -> None:
        t = self._totals
        if event.type == "target.finished":
            t["targets_built"] += 1
        elif event.type == "target.failed":
            t["targets_failed"] += 1
        elif event.type == "action.finished":
            t["actions_run"] += 1
        elif event.type == "action.cache_hit":
            t["cache_hits"] += 1
        elif event.type == "diagnostic.emitted":
            t["warnings" if event.payload.get("severity") == "warning" else "errors"] += \
                1 if event.payload.get("severity") in ("warning", "error") else 0
        totals = dict(t)
        if event.type == "session.finished":
            totals.update(ok=bool(event.payload.get("ok")), duration=float(event.payload.get("duration", 0.0)))
        for wanted, function in self._hooks:
            if wanted is Event.ANY or wanted.value == event.type:
                try:
                    function(HookEvent(event, totals))
                except Exception as exc:  # user code: never let it break the bus
                    self._on_error(f"{getattr(function, '__name__', 'hook')} on {event.type}: "
                                   f"{type(exc).__name__}: {exc}")


# ------------------------------------------------------------------ script hooks
_INTERPRETERS: Dict[str, List[str]] = {
    ".py": [sys.executable],
    ".sh": ["sh"],
    ".bat": ["cmd", "/c"],
    ".cmd": ["cmd", "/c"],
    ".ps1": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"],
}


def discover_scripts(root: Path) -> Dict[str, List[Path]]:
    """event type -> hook scripts, from `<root>/.charpente/hooks/`."""
    directory = root / HOOKS_DIR
    found: Dict[str, List[Path]] = {}
    if not directory.is_dir():
        return found
    for path in sorted(p for p in directory.iterdir() if p.is_file()):
        name = path.name
        stem = name[: -len(path.suffix)] if path.suffix else name
        found.setdefault(stem, []).append(path)
    return found


def scripts_digest(scripts: Dict[str, List[Path]]) -> str:
    h = hashlib.sha256()
    for event_type in sorted(scripts):
        for path in scripts[event_type]:
            h.update(path.name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def command_for(script: Path) -> Optional[List[str]]:
    suffix = script.suffix.lower()
    if suffix in _INTERPRETERS:
        return [*_INTERPRETERS[suffix], str(script)]
    if not suffix and os.access(script, os.X_OK):
        return [str(script)]
    return None


class ScriptHooks:
    """Runs `.charpente/hooks/<event-type>.<ext>` scripts for matching events."""

    def __init__(self, bus: EventBus, scripts: Dict[str, List[Path]], root: Path,
                 on_error: Optional[Callable[[str], None]] = None,
                 runner: Optional[process.Runner] = None) -> None:
        self._scripts = scripts
        self._root = root
        self._runner = runner
        self._on_error = on_error or (lambda m: print(f"charpente: hook script failed: {m}", file=sys.stderr))
        bus.subscribe(self._on_event, name="script-hooks", types=list(scripts))

    def _on_event(self, event: BusEvent) -> None:
        payload = json.dumps(event.to_dict(), default=str)
        for script in self._scripts.get(event.type, []):
            argv = command_for(script)
            if argv is None:
                self._on_error(f"{script.name}: unknown script type (use .py, .sh, .bat, .cmd or .ps1)")
                continue
            env = dict(os.environ, CHARPENTE_EVENT=event.type, CHARPENTE_SESSION=event.session_id)
            try:
                result = process.run(argv, cwd=str(self._root), env=env, input=payload,
                                     timeout=SCRIPT_TIMEOUT, runner=self._runner)
            except ChError as exc:
                self._on_error(f"{script.name}: {exc.message}")
                continue
            except Exception as exc:                        # timeout and friends
                self._on_error(f"{script.name}: {type(exc).__name__}: {exc}")
                continue
            if result.returncode != 0:
                self._on_error(f"{script.name} exited with {result.returncode}: {result.output[:200]}")


def notify(message: str, *, ok: bool = True, title: str = "Charpente") -> None:
    """Available in `.charpente` files. Always prints the message; also sends it
    to every configured notifier that lists `events = ["notify"]` (see the
    charpente-notify module)."""
    print(f"[notify] {message}", file=sys.stderr)
    try:
        from .modules import runtime
        from .modules.official import notify as notify_module

        manager = runtime.get_manager()
        ctx = manager.contexts.get("charpente-notify")
        if ctx is None:
            return
        entries = notify_module.load_config(ctx.workspace_root)
        notify_module.Dispatcher(ctx, entries).send(title, message, ok, event="notify")
    except Exception as exc:  # advisory
        print(f"charpente: notify failed: {exc}", file=sys.stderr)
