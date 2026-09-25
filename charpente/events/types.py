"""The event taxonomy: every event type Charpente can emit, with its payload.

This table is the single source of truth. `schema.py` turns it into the
JSON Schemas published in docs/events/, the bus validates against it in
strict mode (tests), and Studio/CI consumers rely on it.

Field types: str, int, float, bool, list, dict, any. A trailing `?` marks an
optional field. Adding an optional field is backward compatible; renaming or
removing a field, or making one required, means a new `schema_version`.
"""
from __future__ import annotations

from typing import Dict

SCHEMA_VERSION = 1

EVENT_TYPES: Dict[str, Dict[str, str]] = {
    # -- session ------------------------------------------------------------
    "session.started": {"command": "str", "argv": "list", "cwd": "str", "version": "str", "config": "str?"},
    "session.finished": {"ok": "bool", "duration": "float", "exit_code": "int?"},
    "session.interrupted": {"reason": "str?"},
    # -- workspace loading --------------------------------------------------
    "workspace.loading": {"path": "str"},
    "workspace.loaded": {"name": "str", "path": "str", "targets": "int"},
    "workspace.trust_required": {"path": "str"},
    "workspace.lint_warning": {"path": "str", "line": "int?", "code": "str", "message": "str"},
    # -- graph --------------------------------------------------------------
    "graph.analyzed": {"actions": "int", "targets": "int", "critical_path": "float", "config": "str"},
    # -- actions ------------------------------------------------------------
    "action.queued": {"action": "str", "target": "str", "kind": "str"},
    "action.started": {"action": "str", "target": "str", "kind": "str", "description": "str?",
                       "command": "list?", "reasons": "list?"},
    "action.cache_hit": {"action": "str", "target": "str", "kind": "str", "source": "str?", "outputs": "list?"},
    "action.up_to_date": {"action": "str", "target": "str", "kind": "str"},
    "action.finished": {"action": "str", "target": "str", "kind": "str", "duration": "float",
                        "outputs": "list?"},
    "action.failed": {"action": "str", "target": "str", "kind": "str", "returncode": "int",
                      "duration": "float", "output": "str"},
    "action.blocked": {"action": "str", "target": "str", "kind": "str", "because": "list"},
    "action.output": {"action": "str", "target": "str", "stream": "str", "text": "str"},
    # -- targets ------------------------------------------------------------
    "target.started": {"target": "str", "actions": "int"},
    "target.finished": {"target": "str", "output": "str?", "duration": "float", "executed": "int",
                        "cached": "int", "up_to_date": "int"},
    "target.up_to_date": {"target": "str", "output": "str?"},
    "target.failed": {"target": "str", "error": "str", "code": "str?"},
    # -- diagnostics --------------------------------------------------------
    "diagnostic.emitted": {"file": "str?", "line": "int?", "column": "int?", "severity": "str",
                           "code": "str?", "message": "str", "action": "str?", "fix": "str?"},
    # -- tests --------------------------------------------------------------
    "test.started": {"target": "str"},
    "test.passed": {"target": "str", "duration": "float?"},
    "test.failed": {"target": "str", "exit_code": "int", "duration": "float?"},
    "test.flaky_detected": {"target": "str"},
    # -- quality gate -------------------------------------------------------
    "gate.check_started": {"check": "str", "level": "str?"},
    "gate.check_passed": {"check": "str", "duration": "float?"},
    "gate.check_failed": {"check": "str", "reason": "str"},
    "gate.blocked": {"reason": "str"},
    # -- packages -----------------------------------------------------------
    "pkg.resolving": {"name": "str", "constraint": "str?"},
    "pkg.downloading": {"name": "str", "received": "int", "total": "int?"},
    "pkg.verified": {"name": "str", "digest": "str"},
    "pkg.cached": {"name": "str", "version": "str?"},
    # -- vcs ----------------------------------------------------------------
    "vcs.commit_created": {"sha": "str", "message": "str"},
    "vcs.push_done": {"remote": "str", "branch": "str"},
    "vcs.pr_opened": {"url": "str"},
    "vcs.ci_status": {"state": "str", "url": "str?"},
    # -- deployment ---------------------------------------------------------
    "deploy.device_found": {"device": "str", "platform": "str", "name": "str?"},
    "deploy.installing": {"device": "str", "artifact": "str"},
    "deploy.launched": {"device": "str", "app": "str?"},
    "deploy.log": {"device": "str", "level": "str?", "line": "str"},
    # -- resources ----------------------------------------------------------
    "resource.low_disk": {"path": "str", "free_bytes": "int"},
    "resource.low_memory": {"free_bytes": "int"},
    "resource.on_battery": {"jobs": "int?"},
    # -- hints and bookkeeping ----------------------------------------------
    "hint.emitted": {"code": "str", "message": "str", "detail": "dict?"},
    "bus.dropped": {"subscriber": "str", "count": "int"},
}

#: Event types declared by installed modules (`[provides] events`). Kept apart from
#: EVENT_TYPES so the published schemas describe only what Charpente itself emits.
EXTENSION_EVENT_TYPES: Dict[str, Dict[str, str]] = {}


def register_extension_event(name: str) -> None:
    """Allow a module's own event type (free-form payload) on the bus."""
    if "." not in name:
        raise ValueError(f"module event {name!r} must look like 'family.name'")
    if name in EVENT_TYPES:
        raise ValueError(f"module event {name!r} collides with a built-in event")
    EXTENSION_EVENT_TYPES.setdefault(name, {})


_TYPE_NAMES = {"str", "int", "float", "bool", "list", "dict", "any"}


def field_spec(spec: str) -> "tuple[str, bool]":
    """('int', optional=True) for 'int?'."""
    optional = spec.endswith("?")
    name = spec[:-1] if optional else spec
    if name not in _TYPE_NAMES:
        raise ValueError(f"unknown field type {spec!r}")
    return name, optional


def families() -> "list[str]":
    """The distinct families (text before the first dot), in first-seen order."""
    seen: "list[str]" = []
    for name in EVENT_TYPES:
        family = name.split(".", 1)[0]
        if family not in seen:
            seen.append(family)
    return seen
