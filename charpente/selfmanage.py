"""Removing what Charpente keeps on this machine (`charpente self uninstall`).

Everything Charpente stores lives under its config folder (`~/.charpente`, or `CHARPENTE_HOME`) plus, when `CHARPENTE_CACHE_DIR` says so, a cache folder elsewhere. This module
lists those places in groups, with sizes, and removes the groups you name. It never touches project files, and it removes only the entries it knows: a folder that merely *contains*
the config (because `CHARPENTE_HOME` points at, say, your documents) is never deleted as a whole.

* The default is a **dry run**: nothing is removed without `--yes`.
* The `keys` group (signing keys made by `charpente release`) cannot be recreated and is never removed unless you ask for it by name (`--keys`).
* A link (symlink/junction) inside the config folder is unlinked, never followed.
* The Python package itself is removed by pip; the command to run is printed (a program cannot always delete itself, notably on Windows).
"""
from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

#: group -> (what it holds, can it be rebuilt/downloaded again?, entries under the config folder)
GROUPS: Dict[str, Tuple[str, bool, Tuple[str, ...]]] = {
    "cache": ("build cache (and the shared-cache server's store, and remembered compiler identities)", True, ("cache", "cache-server", "toolid.json")),
    "toolchains": ("compilers and SDKs installed by Charpente (zig, emsdk, NDK...)", True, ("toolchains",)),
    "packages": ("downloaded and built packages, local recipes", True, ("pkg",)),
    "modules": ("installed extension modules", True, ("modules",)),
    "android": ("the Android debug keystore (debug-signed apps get a new one)", True, ("android",)),
    "trust": ("your decisions about which files and keys to trust", True, ("trusted_files.json", "trusted_keys.json")),
    "settings": ("remembered preferences (language)", True, ("settings.json",)),
    "keys": ("signing keys for releases: CANNOT be recreated", False, ("keys",)),
}
PROTECTED = "keys"


@dataclass
class Item:
    group: str
    path: Path
    size: int
    is_link: bool = False


def size_of(path: Path) -> int:
    """Bytes under `path` without following links; an unreadable entry counts for 0."""
    try:
        if path.is_symlink() or path.is_file():
            return path.lstat().st_size
        total = 0
        for root, _dirs, files in os.walk(path):                     # os.walk does not follow directory links by default
            for name in files:
                try:
                    total += os.lstat(os.path.join(root, name)).st_size
                except OSError:
                    pass
        return total
    except OSError:
        return 0


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name == "nt":                                              # a junction is a directory that is a reparse point but not a symlink
        try:
            return bool(getattr(path.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        except (OSError, AttributeError):
            return False
    return False


def cache_folder_is_safe(path: Path, config: Path) -> bool:
    """A cache folder outside the config folder is removed only when it is plainly a cache: not a drive root, not a home folder, and named like one."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if resolved == resolved.parent or resolved == Path.home().resolve() or len(resolved.parts) < 3:
        return False
    try:
        resolved.relative_to(config.resolve())
        return True
    except ValueError:
        return any(word in resolved.name.lower() for word in ("cache", "charpente"))


def plan(config: Path, cache_override: Optional[str] = None) -> Tuple[List[Item], List[str]]:
    """(the items that exist, notes about anything skipped on purpose)."""
    items: List[Item] = []
    notes: List[str] = []
    for group, (_what, _rebuildable, entries) in GROUPS.items():
        for entry in entries:
            target = config / entry
            if group == "cache" and entry == "cache" and cache_override:
                target = Path(cache_override).expanduser()
                if not cache_folder_is_safe(target, config):
                    notes.append(f"CHARPENTE_CACHE_DIR ({target}) is not removed: it does not look like a cache folder (remove it yourself if it is one)")
                    continue
            if target.exists() or target.is_symlink():
                items.append(Item(group, target, size_of(target), _is_link(target)))
    return items, notes


def _make_writable_and_retry(function: Callable[[str], object], path: str, _excinfo: object) -> None:
    os.chmod(path, stat.S_IWRITE)                                    # read-only files (git objects in a cached checkout, Windows) block rmtree
    function(path)


def remove(item: Item) -> Optional[str]:
    """Delete one item. Returns None on success, else the reason it could not be removed."""
    try:
        if item.is_link or item.path.is_symlink():
            try:
                os.unlink(item.path)                                 # a file link, or a directory link on POSIX
            except OSError:
                os.rmdir(item.path)                                  # a directory link or junction on Windows: removes the link, never the target's content
        elif item.path.is_dir():
            shutil.rmtree(item.path, onerror=_make_writable_and_retry)
        else:
            item.path.unlink()
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def select(items: Sequence[Item], only: Optional[Sequence[str]], keys: bool) -> Tuple[List[Item], List[str]]:
    """The items to remove: every group except `keys`, unless `only` names some; `keys` is included only when asked for. Returns (chosen, refusals)."""
    refusals: List[str] = []
    wanted = list(only) if only else [g for g in GROUPS if g != PROTECTED]
    for name in wanted:
        if name not in GROUPS:
            refusals.append(f"unknown group {name!r} (groups: {', '.join(GROUPS)})")
    if PROTECTED in wanted and not keys:
        refusals.append("the 'keys' group holds signing keys that cannot be recreated: add --keys to remove it")
        wanted = [w for w in wanted if w != PROTECTED]
    if keys and PROTECTED not in wanted:
        wanted.append(PROTECTED)
    return [i for i in items if i.group in wanted], refusals


def pip_command(python: str) -> List[str]:
    return [python, "-m", "pip", "uninstall", "charpente"]


def humanize(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
