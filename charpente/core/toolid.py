"""Identity of a tool (compiler, linker, archiver).

The identity is part of every action key: upgrading the compiler must
invalidate cached objects. It is made of the resolved path, the version line
the tool prints and a digest of the executable file itself.

Asking a tool for its version means starting a process, which would dominate
a no-op build. The answer is therefore remembered on disk, keyed by the
binary's (path, mtime, size): as long as the executable is untouched nothing
is spawned.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

from ..errors import ChError
from . import hashing, process

UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ToolIdentity:
    requested: str
    path: str
    version: str
    digest: str

    def key(self, portable: bool = False) -> str:
        """The string mixed into action keys. `portable` leaves the install path out (version and the binary's digest identify the tool
        on any machine: what a cache shared between machines needs)."""
        if portable:
            return f"{self.version}|{self.digest}"
        return f"{self.path}|{self.version}|{self.digest}"

    @property
    def resolved(self) -> bool:
        return self.digest != UNRESOLVED


def _cache_file() -> Path:
    from ..dsl.trust import config_dir

    return config_dir() / "toolid.json"


class ToolIdentities:
    """Resolves and memoises tool identities for a session."""

    def __init__(self, runner: Optional[process.Runner] = None,
                 which: Callable[[str], Optional[str]] = shutil.which,
                 persist: bool = True) -> None:
        self._runner = runner
        self._which = which
        self._persist = persist
        self._memo: Dict[str, ToolIdentity] = {}
        self._disk: Optional[Dict[str, Dict[str, object]]] = None
        self._lock = threading.Lock()

    # -------------------------------------------------------------- disk
    def _load_disk(self) -> Dict[str, Dict[str, object]]:
        if self._disk is None:
            try:
                data = json.loads(_cache_file().read_text(encoding="utf-8"))
                self._disk = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self._disk = {}
        return self._disk

    def _save_disk(self) -> None:
        if not self._persist or self._disk is None:
            return
        try:
            target = _cache_file()
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._disk, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(tmp, target)
        except OSError:
            pass

    # -------------------------------------------------------------- query
    def identify(self, tool: str, family: str = "gnu") -> ToolIdentity:
        with self._lock:
            known = self._memo.get(tool)
            if known is not None:
                return known
            identity = self._identify(tool, family)
            self._memo[tool] = identity
            return identity

    def _identify(self, tool: str, family: str) -> ToolIdentity:
        resolved = tool if os.path.isabs(tool) and os.path.isfile(tool) else self._which(tool)
        if not resolved or not os.path.isfile(resolved):
            return ToolIdentity(tool, tool, "", UNRESOLVED)
        resolved = os.path.normcase(os.path.abspath(resolved))
        st = os.stat(resolved)
        if self._persist:
            entry = self._load_disk().get(resolved)
            if (entry and entry.get("mtime_ns") == st.st_mtime_ns and entry.get("size") == st.st_size
                    and isinstance(entry.get("version"), str) and isinstance(entry.get("digest"), str)):
                return ToolIdentity(tool, resolved, str(entry["version"]), str(entry["digest"]))
        version = self._version(resolved, family)
        try:
            digest = hashing.digest_file(resolved)
        except OSError:
            digest = UNRESOLVED
        if self._persist and digest != UNRESOLVED:
            self._load_disk()[resolved] = {"mtime_ns": st.st_mtime_ns, "size": st.st_size,
                                           "version": version, "digest": digest}
            self._save_disk()
        return ToolIdentity(tool, resolved, version, digest)

    def _version(self, path: str, family: str) -> str:
        if family == "msvc":
            argv = [path]
        elif os.path.basename(path).lower().startswith("zig"):
            argv = [path, "version"]                 # `zig --version` is not a zig command
        else:
            argv = [path, "--version"]
        try:
            result = process.run(argv, runner=self._runner, timeout=30)
        except ChError:
            return ""
        except Exception:  # timeout or odd runner: identity falls back to the binary digest alone
            return ""
        text = result.output
        for line in text.splitlines():
            if line.strip():
                return line.strip()[:200]
        return ""
