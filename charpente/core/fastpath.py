"""The no-op fast path: "is anything different since the last successful build?"
answered from file metadata alone, without planning a single action.

After a build in which every action succeeded, the engine leaves a *stamp*: a
digest of everything that defines the build (configuration, toolchain identity,
target definitions, the list of source files) plus the (mtime, size) of every
file it read or wrote (sources, discovered headers, outputs), grouped by
directory. The next run recomputes the digest, lists the same directories and
compares. If nothing differs the build is up to date and we are done;
otherwise (or on the slightest doubt) the full engine runs, which remains the
single source of truth -- including for files that were merely touched, which
it re-hashes.

Two safeguards keep this sound:

* a stamp is only written if every watched file is older than the "racy
  window" (2 s): a same-size edit made within one timestamp tick of the stamp
  could otherwise go unnoticed;
* any surprise (unreadable stamp, other version, missing file) means "not
  proven up to date", never "up to date".
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import hashing
from .statcache import StatCache
from .state import RACY_WINDOW_NS

STAMP_VERSION = 2

#: directory -> [(file name, mtime_ns, size)]
Dirs = Dict[str, List[Tuple[str, int, int]]]


@dataclass
class Stamp:
    context: str
    targets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    dirs: Dirs = field(default_factory=dict)
    created_ns: int = 0


def context_digest(parts: Iterable[str]) -> str:
    return hashing.digest_parts("charpente-stamp/2", *list(parts))


def stamp_path(state_dir: Path, key: str) -> Path:
    return Path(state_dir) / f"stamp-{hashing.digest_parts(key).split(':', 1)[1][:16]}.txt"


def load(path: Path) -> Optional[Stamp]:
    """Format: a JSON header line, then for each directory a `D<TAB>path` line
    followed by `mtime<TAB>size<TAB>name` lines."""
    dirs: Dirs = {}
    try:
        with open(path, encoding="utf-8") as handle:
            header = json.loads(handle.readline())
            if header.get("version") != STAMP_VERSION:
                return None
            current: Optional[List[Tuple[str, int, int]]] = None
            for line in handle:
                line = line.rstrip("\n")
                if line.startswith("D\t"):
                    current = dirs.setdefault(line[2:], [])
                    continue
                if current is None:
                    return None
                mtime, size, name = line.split("\t", 2)
                current.append((name, int(mtime), int(size)))
    except (OSError, ValueError):
        return None
    return Stamp(context=header["context"], targets=header.get("targets", {}), dirs=dirs,
                 created_ns=int(header.get("created_ns", 0)))


def verify(stamp: Optional[Stamp], context: str, stats: StatCache) -> bool:
    """True only if the context is identical and every watched file has exactly
    the recorded (mtime, size)."""
    if stamp is None or stamp.context != context:
        return False
    for directory, entries in stamp.dirs.items():
        metas = stats.stat_many(directory, [name for name, _, _ in entries])
        for (_, mtime, size), meta in zip(entries, metas):
            if meta is None or meta[0] != mtime or meta[1] != size:
                return False
    return True


def write(path: Path, stamp: Stamp) -> bool:
    """Persist `stamp`. Returns False (and removes any older stamp) if any watched
    file is too recent to be trusted (see module docstring)."""
    newest = max((m for entries in stamp.dirs.values() for _, m, _ in entries), default=0)
    if stamp.created_ns - newest < RACY_WINDOW_NS:
        _remove(path)
        return False
    header = {"version": STAMP_VERSION, "context": stamp.context, "targets": stamp.targets,
              "created_ns": stamp.created_ns}
    lines: List[str] = [json.dumps(header)]
    for directory, entries in stamp.dirs.items():
        lines.append(f"D\t{directory}")
        lines.extend(f"{m}\t{s}\t{name}" for name, m, s in entries)
    tmp = Path(str(path) + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def _remove(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def collect(names: Iterable[str], stats: StatCache) -> Optional[Dirs]:
    """Current (mtime, size) of every file in `names`, grouped by directory;
    None if any of them is missing."""
    grouped: Dict[str, List[str]] = {}
    for full in names:
        directory, name = os.path.split(full)
        grouped.setdefault(directory, []).append(name)
    dirs: Dirs = {}
    for directory, files in grouped.items():
        metas = stats.stat_many(directory, files)
        entries: List[Tuple[str, int, int]] = []
        for name, meta in zip(files, metas):
            if meta is None:
                return None
            entries.append((name, meta[0], meta[1]))
        dirs[directory] = entries
    return dirs


def now_ns() -> int:
    return time.time_ns()
