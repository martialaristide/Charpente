"""Build history: a SQLite record of every session, fed purely by events.

`HistoryRecorder` is an ordinary event subscriber -- the engine knows nothing
about it. `charpente history` lists sessions; `charpente diff-build A B`
compares two (time, binary sizes, new warnings).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..events import Event, EventBus

SCHEMA_VERSION = 1
MAX_WARNINGS_PER_SESSION = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY, started REAL, finished REAL, command TEXT, config TEXT, toolchain TEXT,
  ok INTEGER, exit_code INTEGER, duration REAL, actions INTEGER, executed INTEGER, cached INTEGER,
  up_to_date INTEGER, failed INTEGER, warnings INTEGER, errors INTEGER);
CREATE TABLE IF NOT EXISTS action_history(
  session TEXT, action TEXT, target TEXT, kind TEXT, status TEXT, duration REAL, reasons TEXT);
CREATE TABLE IF NOT EXISTS artifacts(session TEXT, path TEXT, size INTEGER);
CREATE TABLE IF NOT EXISTS warnings(session TEXT, file TEXT, line INTEGER, code TEXT, message TEXT);
CREATE INDEX IF NOT EXISTS idx_actions_session ON action_history(session);
"""


@dataclass
class SessionInfo:
    id: str
    started: float
    finished: float
    command: str
    config: str
    toolchain: str
    ok: bool
    exit_code: Optional[int]
    duration: float
    actions: int
    executed: int
    cached: int
    up_to_date: int
    failed: int
    warnings: int
    errors: int


def connect(path: Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    if conn.execute("PRAGMA user_version").fetchone()[0] not in (0, SCHEMA_VERSION):
        conn.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(str(path) + suffix)
            except OSError:
                pass
        conn = sqlite3.connect(str(path), timeout=30)
    conn.executescript(_SCHEMA)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.commit()
    return conn


class HistoryRecorder:
    """Subscribes to a bus and writes one row set per session."""

    def __init__(self, bus: EventBus, db_path: Path, *, command: str = "build", config: str = "",
                 toolchain: str = "") -> None:
        self.db_path = Path(db_path)
        self.command = command
        self.config = config
        self.toolchain = toolchain
        self.session_id = bus.session_id
        self._lock = threading.Lock()
        self._started = 0.0
        self._actions = 0
        self._rows: List[Tuple[str, str, str, str, float, str]] = []
        self._artifacts: List[str] = []
        self._warnings: List[Tuple[str, int, str, str]] = []
        self._warning_count = 0
        self._error_count = 0
        self._counts = {"executed": 0, "cached": 0, "up_to_date": 0, "failed": 0}
        self._reasons: Dict[str, List[str]] = {}
        self.written = False
        bus.subscribe(self._on_event, sync=True, name="history",
                      types=["session.*", "graph.analyzed", "action.*", "diagnostic.emitted"])

    def _on_event(self, event: Event) -> None:
        p = event.payload
        kind = event.type
        with self._lock:
            if kind == "session.started":
                self._started = event.wall_time
            elif kind == "graph.analyzed":
                self._actions = int(p["actions"])
            elif kind == "action.started":
                self._reasons[p["action"]] = list(p.get("reasons") or [])
            elif kind == "action.finished":
                self._counts["executed"] += 1
                self._rows.append((p["action"], p["target"], p["kind"], "executed", float(p["duration"]),
                                   json.dumps(self._reasons.pop(p["action"], []))))
                self._artifacts.extend(str(o) for o in (p.get("outputs") or []) if p["kind"] != "compile")
            elif kind == "action.cache_hit":
                self._counts["cached"] += 1
                self._rows.append((p["action"], p["target"], p["kind"], "cache_hit", 0.0, "[]"))
                self._artifacts.extend(str(o) for o in (p.get("outputs") or []) if p["kind"] != "compile")
            elif kind == "action.up_to_date":
                self._counts["up_to_date"] += 1
            elif kind == "action.failed":
                self._counts["failed"] += 1
                self._rows.append((p["action"], p["target"], p["kind"], "failed", float(p["duration"]),
                                   json.dumps(self._reasons.pop(p["action"], []))))
            elif kind == "diagnostic.emitted":
                if p["severity"] == "warning":
                    self._warning_count += 1
                    if len(self._warnings) < MAX_WARNINGS_PER_SESSION:
                        self._warnings.append((str(p.get("file") or ""), int(p.get("line") or 0),
                                               str(p.get("code") or ""), str(p["message"])))
                elif p["severity"] == "error":
                    self._error_count += 1
            elif kind == "session.finished":
                self._write(event)

    def _write(self, finish: Event) -> None:
        p = finish.payload
        try:
            conn = connect(self.db_path)
        except (sqlite3.Error, OSError):
            return                       # history is a convenience: never break a build over it
        try:
            c = self._counts
            conn.execute(
                "INSERT OR REPLACE INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (self.session_id, self._started or finish.wall_time, finish.wall_time, self.command, self.config,
                 self.toolchain, 1 if p["ok"] else 0, p.get("exit_code"), float(p["duration"]), self._actions,
                 c["executed"], c["cached"], c["up_to_date"], c["failed"], self._warning_count,
                 self._error_count))
            conn.executemany("INSERT INTO action_history VALUES(?,?,?,?,?,?,?)",
                             [(self.session_id, *row) for row in self._rows])
            sizes = []
            for path in dict.fromkeys(self._artifacts):
                try:
                    sizes.append((self.session_id, path, os.path.getsize(path)))
                except OSError:
                    pass
            conn.executemany("INSERT INTO artifacts VALUES(?,?,?)", sizes)
            conn.executemany("INSERT INTO warnings VALUES(?,?,?,?,?)",
                             [(self.session_id, *w) for w in self._warnings])
            conn.commit()
            self.written = True
        except sqlite3.Error:
            pass
        finally:
            conn.close()


# ------------------------------------------------------------------ queries
_COLUMNS = ("id, started, finished, command, config, toolchain, ok, exit_code, duration, actions, executed, "
            "cached, up_to_date, failed, warnings, errors")


def _to_info(row: Sequence[Any]) -> SessionInfo:
    return SessionInfo(id=row[0], started=row[1], finished=row[2], command=row[3], config=row[4],
                       toolchain=row[5], ok=bool(row[6]), exit_code=row[7], duration=row[8], actions=row[9],
                       executed=row[10], cached=row[11], up_to_date=row[12], failed=row[13], warnings=row[14],
                       errors=row[15])


def list_sessions(db_path: Path, limit: int = 20) -> List[SessionInfo]:
    if not Path(db_path).exists():
        return []
    conn = connect(db_path)
    try:
        rows = conn.execute(f"SELECT {_COLUMNS} FROM sessions ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [_to_info(r) for r in rows]


def find_session(db_path: Path, ref: str) -> Optional[SessionInfo]:
    """`ref` is 'latest', 'previous', a 1-based index from the newest ('1' is
    the latest), or a prefix of a session id."""
    sessions = list_sessions(db_path, limit=1000)
    if not sessions:
        return None
    if ref == "latest":
        return sessions[0]
    if ref == "previous":
        return sessions[1] if len(sessions) > 1 else None
    if ref.isdigit() and len(ref) <= 4:
        index = int(ref) - 1
        return sessions[index] if 0 <= index < len(sessions) else None
    matches = [s for s in sessions if s.id.startswith(ref)]
    return matches[0] if len(matches) == 1 else None


def action_rows(db_path: Path, session_id: str) -> List[Dict[str, Any]]:
    conn = connect(db_path)
    try:
        rows = conn.execute("SELECT action, target, kind, status, duration, reasons FROM action_history "
                            "WHERE session=?", (session_id,)).fetchall()
    finally:
        conn.close()
    return [{"action": r[0], "target": r[1], "kind": r[2], "status": r[3], "duration": r[4],
             "reasons": json.loads(r[5] or "[]")} for r in rows]


@dataclass
class BuildDiff:
    a: SessionInfo
    b: SessionInfo
    duration_delta: float
    artifact_deltas: List[Tuple[str, int, int]] = field(default_factory=list)   # (path, size_a, size_b)
    new_warnings: List[Tuple[str, int, str, str]] = field(default_factory=list)
    fixed_warnings: List[Tuple[str, int, str, str]] = field(default_factory=list)
    slower_actions: List[Tuple[str, float, float]] = field(default_factory=list)


def diff_sessions(db_path: Path, a: SessionInfo, b: SessionInfo) -> BuildDiff:
    conn = connect(db_path)
    try:
        def artifacts(sid: str) -> Dict[str, int]:
            return {r[0]: r[1] for r in conn.execute("SELECT path, size FROM artifacts WHERE session=?", (sid,))}

        def warns(sid: str) -> Set[Tuple[str, int, str, str]]:
            return {(r[0], r[1], r[2], r[3]) for r in conn.execute(
                "SELECT file, line, code, message FROM warnings WHERE session=?", (sid,))}

        def times(sid: str) -> Dict[str, float]:
            return {r[0]: r[1] for r in conn.execute(
                "SELECT action, duration FROM action_history WHERE session=? AND status='executed'", (sid,))}

        art_a, art_b = artifacts(a.id), artifacts(b.id)
        wa, wb = warns(a.id), warns(b.id)
        ta, tb = times(a.id), times(b.id)
    finally:
        conn.close()
    deltas = [(p, art_a.get(p, 0), art_b.get(p, 0)) for p in sorted(set(art_a) | set(art_b))
              if art_a.get(p) != art_b.get(p)]
    slower = sorted(((act, ta[act], tb[act]) for act in ta.keys() & tb.keys() if tb[act] - ta[act] > 0.05),
                    key=lambda t: t[2] - t[1], reverse=True)[:10]
    return BuildDiff(a=a, b=b, duration_delta=b.duration - a.duration, artifact_deltas=deltas,
                     new_warnings=sorted(wb - wa), fixed_warnings=sorted(wa - wb), slower_actions=slower)
