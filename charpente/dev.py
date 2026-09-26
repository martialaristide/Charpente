"""`charpente dev`: rebuild when files change, and publish each successful build of a plugin as a hot-reloadable generation (experimental).

Watching is by polling (a stat per file every half second): no dependency, the same on every OS, and cheap enough for thousands of files because the engine
does the real work (only what changed is rebuilt, from the content-addressed cache when possible). What is watched is what the build reads: every source of every
target, the headers in the include directories, and the workspace file.

Publishing a plugin: after a successful build, its shared library is copied to `<hot dir>/<name>.<generation>.<ext>` (unique names: on Windows a loaded DLL cannot be
overwritten) and `<hot dir>/<name>.json` is atomically replaced with `{"generation": N, "path": "..."}`. A host using `charpente_hot.h` picks it up while running.
A *failed* build publishes nothing, so the host keeps running the last good code. Old generations are pruned (the newest few stay: a host may still hold one).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from .dsl.model import Kind, Workspace

HEADER_SUFFIXES = (".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp")
KEEP_GENERATIONS = 3


def snapshot(paths: Iterable[Path]) -> Dict[str, Tuple[int, int]]:
    """{path: (mtime_ns, size)} of the files that exist."""
    state: Dict[str, Tuple[int, int]] = {}
    for path in paths:
        try:
            stat = os.stat(path)
        except OSError:
            continue
        state[str(path)] = (stat.st_mtime_ns, stat.st_size)
    return state


def changes(before: Dict[str, Tuple[int, int]], after: Dict[str, Tuple[int, int]]) -> List[str]:
    """Paths added, removed or modified between two snapshots, sorted."""
    keys = set(before) | set(after)
    return sorted(k for k in keys if before.get(k) != after.get(k))


def watched_files(workspace: Workspace, workspace_file: Optional[Path], only: Optional[Iterable[str]] = None) -> List[Path]:
    """The files whose change should trigger a rebuild: sources, headers in include directories, the workspace file."""
    files: Set[Path] = set()
    if workspace_file is not None:
        files.add(workspace_file)
    names = set(only) if only is not None else None
    for name, target in workspace.targets.items():
        if target.external or (names is not None and name not in names):
            continue
        base = target.location or workspace.root
        try:
            files.update(target.resolved_sources())
        except Exception:
            pass                                                                # a pattern that no longer matches is a change the build will report
        for directory in [*target.include_dirs, *target.public_include_dirs, *target.interface_include_dirs]:
            folder = Path(directory) if Path(directory).is_absolute() else base / directory
            if folder.is_dir():
                files.update(p for p in folder.rglob("*") if p.suffix.lower() in HEADER_SUFFIXES and p.is_file())
        for source in list(target.source_patterns):
            folder = base / Path(source).parent
            if folder.is_dir() and not any(ch in str(folder) for ch in "*?["):
                files.update(p for p in folder.glob("*") if p.suffix.lower() in HEADER_SUFFIXES and p.is_file())
    return sorted(files)


def plugin_targets(workspace: Workspace, only: Optional[Iterable[str]] = None) -> List[str]:
    names = set(only) if only is not None else None
    return [n for n, t in workspace.targets.items() if t.kind == Kind.PLUGIN and not t.external and (names is None or n in names)]


@dataclass(frozen=True)
class Published:
    target: str
    generation: int
    path: Path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def current_generation(hot_dir: Path, name: str) -> int:
    try:
        return int(json.loads((hot_dir / f"{name}.json").read_text(encoding="utf-8"))["generation"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def publish(hot_dir: Path, name: str, library: Path, keep: int = KEEP_GENERATIONS) -> Published:
    """Copy `library` as the next generation of plugin `name`, then point the manifest at it, then prune old copies."""
    generation = current_generation(hot_dir, name) + 1
    hot_dir.mkdir(parents=True, exist_ok=True)
    copy = hot_dir / f"{name}.{generation}{library.suffix}"
    shutil.copyfile(library, copy)                                              # the copy exists before the manifest names it
    _atomic_write(hot_dir / f"{name}.json", json.dumps({"generation": generation, "path": str(copy), "source": str(library), "published": time.time()}))
    for old in sorted(hot_dir.glob(f"{name}.*{library.suffix}"), key=lambda p: _generation_of(p, name)):
        if _generation_of(old, name) <= generation - keep:
            try:
                old.unlink()
            except OSError:
                pass                                                            # still loaded by a host (Windows): pruned next time
    return Published(name, generation, copy)


def _generation_of(path: Path, name: str) -> int:
    middle = path.name[len(name) + 1:].split(".", 1)[0]
    return int(middle) if middle.isdigit() else 0


class Watcher:
    """Remembers a snapshot and reports what changed since the last call to `poll()`. `files()` is asked every time, so new files are noticed."""

    def __init__(self, files: Callable[[], List[Path]]) -> None:
        self._files = files
        self.state = snapshot(files())

    def poll(self) -> List[str]:
        after = snapshot(self._files())
        changed = changes(self.state, after)
        self.state = after
        return changed
