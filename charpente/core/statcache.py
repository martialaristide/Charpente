"""Cheap file metadata for freshness checks.

On Windows a single `os.stat` costs tens of microseconds (measured: ~48 us,
so 10 000 files take half a second), while `os.scandir` hands out the same
information for a whole directory almost for free (24 ms for 10 000 entries).
Ninja does the same on Windows. This cache therefore lists a directory once and
serves every file in it from that listing; on POSIX, where `stat` is a fast
system call, it simply calls `os.stat`.

Trade-off, stated plainly: a directory listing may briefly lag behind a file
another process still holds open for writing. Files a build step *produces* are
therefore always re-read with `os.stat` (see `refresh`), and a lagging entry can
only make Charpente rebuild too much, never too little for outputs.
"""
from __future__ import annotations

import os
import threading
from typing import Dict, List, Optional, Tuple

_FOLD = os.name == "nt"   # names are case-insensitive: index the lower-cased spelling too

#: (mtime_ns, size)
Meta = Tuple[int, int]


class StatCache:
    def __init__(self, batch: Optional[bool] = None) -> None:
        self.batch = (os.name == "nt") if batch is None else batch
        self._dirs: Dict[str, Dict[str, Optional[Meta]]] = {}
        self._lock = threading.Lock()
        self.syscalls = 0

    def stat(self, path: str) -> Optional[Meta]:
        """(mtime_ns, size) of a regular file, or None if it is missing or not a file."""
        if not self.batch:
            return self._direct(path)
        directory, name = os.path.split(path)
        return self.stat_many(directory, [name])[0]

    def stat_many(self, directory: str, names: List[str]) -> List[Optional[Meta]]:
        """Metadata of several files of one directory. One listing serves them all
        where listing is cheap (Windows); elsewhere one `stat` per file."""
        if not self.batch:
            base = directory + os.sep if directory else ""
            return [self._direct(base + name) for name in names]
        with self._lock:
            listing = self._dirs.get(directory)
            if listing is None:
                listing = self._scan(directory)
                self._dirs[directory] = listing
            get = listing.get
            out = [get(name) for name in names]
            if None in out:      # tolerate a different spelling of the same name (case)
                out = [m if m is not None else get(n.lower()) for m, n in zip(out, names)]
        return out

    def _direct(self, path: str) -> Optional[Meta]:
        self.syscalls += 1
        try:
            st = os.stat(path)
        except OSError:
            return None
        import stat as stat_mod

        return (st.st_mtime_ns, st.st_size) if stat_mod.S_ISREG(st.st_mode) else None

    def _scan(self, directory: str) -> Dict[str, Optional[Meta]]:
        """One listing: name (and its case-folded twin) -> metadata."""
        self.syscalls += 1
        listing: Dict[str, Optional[Meta]] = {}
        try:
            with os.scandir(directory or ".") as entries:
                for entry in entries:
                    try:
                        if entry.is_file():
                            st = entry.stat()
                            meta: Optional[Meta] = (st.st_mtime_ns, st.st_size)
                        else:
                            meta = None
                    except OSError:
                        meta = None
                    listing[entry.name] = meta
                    if _FOLD:
                        listing[entry.name.lower()] = meta
        except OSError:
            pass
        return listing

    def refresh(self, path: str) -> Optional[Meta]:
        """Re-read one file with a real `os.stat` (used after a build step wrote it)."""
        meta = self._direct(path)
        if self.batch:
            directory, name = os.path.split(path)
            with self._lock:
                listing = self._dirs.get(directory)
                if listing is not None:
                    listing[name] = meta
                    if _FOLD:
                        listing[name.lower()] = meta
        return meta

    def forget_all(self) -> None:
        with self._lock:
            self._dirs.clear()
