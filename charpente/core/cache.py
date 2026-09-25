"""Content-addressed cache of action results.

Layout under the cache root::

    cas/<xx>/<digest>      file contents, named by their digest (deduplicated)
    ac/<key>.json          "action cache": what an action key produced
    mf/<key1>.json         "manifests": the header sets seen for an action

Correctness rests on the key, not on the cache: an entry is only ever found
by the hash of everything that determines its content (command, tool,
input and header *contents*), so a stale entry cannot be returned -- it is
just never asked for. Writes are atomic (temp file + rename), so concurrent
Charpente processes can share one cache directory.

Header handling follows the "manifest" idea used by ccache: the full key of a
compilation depends on the headers it read, which are only known after
running it. The manifest stores, per pre-key, the header lists observed so far;
a lookup re-hashes each list's *current* contents and asks for that key.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import hashing

CACHE_ENV = "CHARPENTE_CACHE_DIR"
MAX_MANIFEST_ENTRIES = 16


def default_cache_dir() -> Path:
    override = os.environ.get(CACHE_ENV)
    if override:
        return Path(override).expanduser().resolve()
    from ..dsl.trust import config_dir

    return config_dir() / "cache"


@dataclass(frozen=True)
class CachedOutput:
    digest: str
    size: int
    mode: int


@dataclass(frozen=True)
class CacheEntry:
    key: str
    outputs: "tuple[CachedOutput, ...]"
    stdout: str
    stderr: str
    duration: float


@dataclass
class CacheStats:
    entries: int
    blobs: int
    bytes: int


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


class LocalCache:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else default_cache_dir()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    # ------------------------------------------------------------- paths
    @staticmethod
    def _safe(name: str) -> str:
        return name.replace(":", "-")

    def _blob(self, digest: str) -> Path:
        name = self._safe(digest)
        return self.root / "cas" / name.split("-", 1)[-1][:2] / name

    def _entry_path(self, key: str) -> Path:
        return self.root / "ac" / f"{self._safe(key)}.json"

    def _manifest_path(self, key: str) -> Path:
        return self.root / "mf" / f"{self._safe(key)}.json"

    # ------------------------------------------------------------- entries
    def lookup(self, key: str) -> Optional[CacheEntry]:
        path = self._entry_path(key)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entry = CacheEntry(
                key=key,
                outputs=tuple(CachedOutput(o["digest"], int(o["size"]), int(o.get("mode", 0o644)))
                              for o in data["outputs"]),
                stdout=data.get("stdout", ""),
                stderr=data.get("stderr", ""),
                duration=float(data.get("duration", 0.0)),
            )
        except (OSError, ValueError, KeyError, TypeError):
            with self._lock:
                self.misses += 1
            return None
        if not all(self._blob(o.digest).is_file() for o in entry.outputs):
            self._drop(key)          # a blob was evicted: the entry is useless
            with self._lock:
                self.misses += 1
            return None
        with self._lock:
            self.hits += 1
        self._touch(path)
        for out in entry.outputs:   # recency of use drives eviction (atime is unreliable)
            self._touch(self._blob(out.digest))
        return entry

    def store(self, key: str, outputs: Sequence[Path], stdout: str = "", stderr: str = "",
              duration: float = 0.0) -> bool:
        """Cache the files in `outputs` under `key`. Returns False (and stores
        nothing) if any output cannot be read."""
        records: List[Dict[str, Any]] = []
        try:
            for out in outputs:
                digest = hashing.digest_file(out)
                blob = self._blob(digest)
                if not blob.exists():
                    blob.parent.mkdir(parents=True, exist_ok=True)
                    fd, tmp = tempfile.mkstemp(dir=str(blob.parent), prefix=".tmp-")
                    os.close(fd)
                    try:
                        shutil.copyfile(out, tmp)
                        os.replace(tmp, blob)
                    except BaseException:
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                        raise
                st = os.stat(out)
                records.append({"digest": digest, "size": st.st_size, "mode": st.st_mode & 0o777})
            payload = {"outputs": records, "stdout": stdout, "stderr": stderr, "duration": duration,
                       "created": time.time()}
            _atomic_write(self._entry_path(key), json.dumps(payload).encode("utf-8"))
        except OSError:
            return False
        return True

    def restore(self, entry: CacheEntry, destinations: Sequence[Path]) -> bool:
        """Copy the cached files to `destinations` (same order as stored)."""
        if len(entry.outputs) != len(destinations):
            return False
        try:
            for cached, dest in zip(entry.outputs, destinations):
                dest.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix=".charpente-restore-")
                os.close(fd)
                try:
                    shutil.copyfile(self._blob(cached.digest), tmp)
                    if os.name == "posix":
                        os.chmod(tmp, cached.mode or 0o644)
                    os.replace(tmp, dest)
                except BaseException:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    raise
        except OSError:
            return False
        return True

    def _drop(self, key: str) -> None:
        try:
            os.remove(self._entry_path(key))
        except OSError:
            pass

    @staticmethod
    def _touch(path: Path) -> None:
        try:
            os.utime(path, None)
        except OSError:
            pass

    # ----------------------------------------------------------- manifests
    def manifest(self, key1: str) -> List[List[str]]:
        try:
            data = json.loads(self._manifest_path(key1).read_text(encoding="utf-8"))
            return [list(map(str, deps)) for deps in data["header_sets"]]
        except (OSError, ValueError, KeyError, TypeError):
            return []

    def add_to_manifest(self, key1: str, deps: Iterable[str]) -> None:
        deps_list = list(map(str, deps))
        with self._lock:
            current = self.manifest(key1)
            if deps_list in current:
                current.remove(deps_list)
            current.insert(0, deps_list)
            try:
                _atomic_write(self._manifest_path(key1),
                              json.dumps({"header_sets": current[:MAX_MANIFEST_ENTRIES]}).encode("utf-8"))
            except OSError:
                pass

    # --------------------------------------------------------- maintenance
    def stats(self) -> CacheStats:
        entries = sum(1 for _ in (self.root / "ac").glob("*.json")) if (self.root / "ac").exists() else 0
        blobs = 0
        total = 0
        cas = self.root / "cas"
        if cas.exists():
            for p in cas.rglob("*"):
                if p.is_file() and not p.name.startswith(".tmp-"):
                    blobs += 1
                    total += p.stat().st_size
        return CacheStats(entries=entries, blobs=blobs, bytes=total)

    def gc(self, max_bytes: int) -> int:
        """Delete the least-recently-used blobs until the cache fits in
        `max_bytes`. Returns the number of bytes freed. Entries whose blobs
        disappear are discarded lazily by `lookup`."""
        cas = self.root / "cas"
        if not cas.exists():
            return 0
        blobs = []
        total = 0
        for p in cas.rglob("*"):
            if p.is_file():
                st = p.stat()
                blobs.append((max(st.st_atime, st.st_mtime), st.st_size, p))
                total += st.st_size
        freed = 0
        for _, size, path in sorted(blobs, key=lambda b: b[0]):
            if total - freed <= max_bytes:
                break
            try:
                path.unlink()
                freed += size
            except OSError:
                pass
        return freed

    def clear(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
