"""Persistent build state (SQLite): what each action looked like the last time
it ran, and a memo of file digests keyed by (mtime, size).

Everything stored here is *derived* data: deleting the file only costs a
rebuild (or, thanks to the content cache, a cheap replay). A file that cannot
be opened or has an old schema is discarded and recreated, never trusted.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from . import hashing
from .graph import path_key
from .statcache import StatCache

SCHEMA_VERSION = 2
COMMIT_EVERY = 64
COMMIT_INTERVAL = 0.5
MISSING = "missing"

#: A file modified less than this long before we hashed it might still be
#: modified again within the same timestamp tick (coarse filesystem clocks), so
#: its (mtime, size) cannot be trusted as proof of unchanged content. Git uses
#: the same "racily clean" rule.
RACY_WINDOW_NS = 2_000_000_000


@dataclass
class ActionRecord:
    """What an action looked like when it last succeeded."""

    key: str
    argv: List[str]
    cwd: str
    tool: str
    env: List[Tuple[str, str]]
    inputs: Dict[str, str]                 # declared input path -> content digest
    deps: Dict[str, str]                   # discovered header path -> content digest
    outputs: Dict[str, List[int]]          # output path -> [mtime_ns, size]
    duration: float = 0.0
    finished_at: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, sort_keys=True)

    @staticmethod
    def from_json(text: str) -> "ActionRecord":
        data = json.loads(text)
        data["env"] = [tuple(x) for x in data.get("env", [])]
        return ActionRecord(**data)


class StateDB:
    """One SQLite file. Thread-safe (a single lock around every operation)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._files: Dict[str, Tuple[int, int, str, int]] = {}
        self._actions: Dict[str, str] = {}
        self._dirty_files: Dict[str, Tuple[int, int, str, int]] = {}
        self._pending = 0
        self._last_commit = time.monotonic()
        self._open()

    # ----------------------------------------------------------------- open
    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connect()
        except sqlite3.DatabaseError:
            self._discard()
            self._connect()

    def _connect(self) -> None:
        conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                conn.close()
                self._discard()
                conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(
                "CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER,"
                " digest TEXT, racy INTEGER);"
                "CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY, data TEXT);"
            )
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.commit()
            self._files = {p: (m, s, d, r) for p, m, s, d, r in conn.execute("SELECT * FROM files")}
            self._actions = dict(conn.execute("SELECT id, data FROM actions").fetchall())
        except sqlite3.DatabaseError:
            conn.close()
            raise
        self._conn = conn

    def _discard(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(str(self.path) + suffix)
            except OSError:
                pass

    # ---------------------------------------------------------- file digests
    def get_file(self, key: str) -> Optional[Tuple[int, int, str, int]]:
        with self._lock:
            return self._files.get(key)

    def put_file(self, key: str, mtime_ns: int, size: int, digest: str, racy: bool) -> None:
        record = (mtime_ns, size, digest, 1 if racy else 0)
        with self._lock:
            if self._files.get(key) != record:
                self._files[key] = record
                self._dirty_files[key] = record

    # -------------------------------------------------------------- actions
    def get_action(self, action_id: str) -> Optional[ActionRecord]:
        with self._lock:
            raw = self._actions.get(action_id)
        if raw is None:
            return None
        try:
            return ActionRecord.from_json(raw)
        except (ValueError, TypeError, KeyError):
            return None

    def put_action(self, action_id: str, record: ActionRecord) -> None:
        raw = record.to_json()
        with self._lock:
            self._actions[action_id] = raw
            assert self._conn is not None
            self._conn.execute("INSERT OR REPLACE INTO actions(id, data) VALUES(?, ?)", (action_id, raw))
            self._pending += 1
            # Committing after every action costs milliseconds each on some
            # systems; batch them. A crash loses at most the last batch, whose
            # actions then look "unrecorded" and are replayed from the cache.
            if self._pending >= COMMIT_EVERY or time.monotonic() - self._last_commit > COMMIT_INTERVAL:
                self._flush_files_locked()
                self._conn.commit()
                self._pending = 0
                self._last_commit = time.monotonic()

    def delete_action(self, action_id: str) -> None:
        with self._lock:
            if self._actions.pop(action_id, None) is not None:
                assert self._conn is not None
                self._conn.execute("DELETE FROM actions WHERE id=?", (action_id,))
                self._pending += 1

    def action_ids(self) -> List[str]:
        with self._lock:
            return list(self._actions)

    def records(self) -> Iterator[Tuple[str, ActionRecord]]:
        for aid in self.action_ids():
            rec = self.get_action(aid)
            if rec is not None:
                yield aid, rec

    # ---------------------------------------------------------------- flush
    def _flush_files_locked(self) -> None:
        if self._dirty_files and self._conn is not None:
            self._conn.executemany(
                "INSERT OR REPLACE INTO files(path, mtime_ns, size, digest, racy) VALUES(?,?,?,?,?)",
                [(p, *rec) for p, rec in self._dirty_files.items()],
            )
            self._dirty_files.clear()

    def flush(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._flush_files_locked()
                self._conn.commit()
                self._pending = 0
                self._last_commit = time.monotonic()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._flush_files_locked()
                self._conn.commit()
                self._conn.close()
                self._conn = None


class FileHasher:
    """Content digests with a stat-based shortcut.

    A file whose (mtime, size) match what we recorded is *not* re-read, unless
    the recording was "racy" (see RACY_WINDOW_NS). Within one session digests
    are memoised, because a header included by a thousand sources is looked at
    once; `invalidate()` must be called for files an action just produced.
    """

    def __init__(self, db: Optional[StateDB] = None, clock_ns: Any = time.time_ns,
                 stats: Optional[StatCache] = None) -> None:
        self._db = db
        self._clock_ns = clock_ns
        self.stats = stats if stats is not None else StatCache()
        self._memo: Dict[str, str] = {}
        self._lock = threading.Lock()
        self.reads = 0  # how many files were actually read (observable in tests / benchmarks)

    def digest(self, path: "str | Path") -> str:
        key = path_key(path)
        with self._lock:
            cached = self._memo.get(key)
        if cached is not None:
            return cached
        result = self._compute(key, path)
        with self._lock:
            self._memo[key] = result
        return result

    def _compute(self, key: str, path: "str | Path") -> str:
        meta = self.stats.stat(os.fspath(path))
        if meta is None:
            return MISSING
        mtime_ns, size = meta
        if self._db is not None:
            known = self._db.get_file(key)
            if known is not None:
                k_mtime, k_size, k_digest, k_racy = known
                if k_mtime == mtime_ns and k_size == size and not k_racy:
                    return k_digest
        try:
            digest = hashing.digest_file(path)
        except OSError:
            return MISSING
        self.reads += 1
        if self._db is not None:
            racy = abs(self._clock_ns() - mtime_ns) < RACY_WINDOW_NS
            self._db.put_file(key, mtime_ns, size, digest, racy)
        return digest

    def invalidate(self, path: "str | Path") -> None:
        """`path` was just written (or deleted) by a build step: forget what we knew."""
        self.stats.refresh(os.fspath(path))
        with self._lock:
            self._memo.pop(path_key(path), None)

    def forget_all(self) -> None:
        with self._lock:
            self._memo.clear()
        self.stats.forget_all()
