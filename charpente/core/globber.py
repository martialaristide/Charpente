"""File-pattern expansion (`sources(["src/**/*.cpp"])`) built on `os.scandir`.

`pathlib.Path.glob` builds a `Path` object for every directory entry it looks
at, which dominates the cost of planning a build with tens of thousands of
files. This walks with `scandir` and only compares names.

Supported syntax (per path component, `/` or `\\` as separator):

* `*`, `?`, `[...]`  -- as in shell globs, within one component
* `**`               -- zero or more directories (must be a whole component)

Matching is case-insensitive on Windows, case-sensitive elsewhere, like the
file system. Symbolic links to directories are not followed by `**`.
"""
from __future__ import annotations

import fnmatch
import os
import re
from typing import Iterable, List, Optional, Pattern, Set

from ..errors import ChValueError

_CASE_INSENSITIVE = os.name == "nt"
_MAGIC = re.compile(r"[*?\[]")


def _compile(component: str) -> Pattern[str]:
    flags = re.IGNORECASE if _CASE_INSENSITIVE else 0
    return re.compile(fnmatch.translate(component), flags)


def _split(pattern: str) -> List[str]:
    parts = [p for p in pattern.replace("\\", "/").split("/") if p not in ("", ".")]
    for part in parts:
        if "**" in part and part != "**":
            raise ChValueError("CH1019", pattern=pattern)
    return parts


def expand(root: str, patterns: Iterable[str]) -> Set[str]:
    """Absolute paths of the *files* matching any pattern, relative to `root`."""
    found: Set[str] = set()
    for pattern in patterns:
        parts = _split(pattern)
        if not parts:
            continue
        if os.path.isabs(pattern):
            raise ChValueError("CH1020", pattern=pattern)
        _walk(root, parts, 0, found)
    return found


def _walk(directory: str, parts: List[str], index: int, found: Set[str]) -> None:
    part = parts[index]
    last = index == len(parts) - 1

    if part == "**":
        # zero directories: continue matching the rest right here
        if last:
            _collect_all(directory, found)
            return
        _walk(directory, parts, index + 1, found)
        for sub in _subdirectories(directory):
            _walk(sub, parts, index, found)          # `**` stays active in the subdirectory
        return

    if not _MAGIC.search(part):
        # A literal component: no need to list the directory.
        path = os.path.join(directory, part)
        if last:
            if os.path.isfile(path):
                found.add(os.path.normpath(path))
        elif os.path.isdir(path):
            _walk(path, parts, index + 1, found)
        return

    regex = _compile(part)
    try:
        with os.scandir(directory) as entries:
            matches = [e for e in entries if regex.match(e.name)]
    except OSError:
        return
    for entry in matches:
        try:
            if last:
                if entry.is_file():
                    found.add(os.path.normpath(entry.path))
            elif entry.is_dir():
                _walk(entry.path, parts, index + 1, found)
        except OSError:
            continue


def _subdirectories(directory: str) -> List[str]:
    try:
        with os.scandir(directory) as entries:
            return [e.path for e in entries if e.is_dir(follow_symlinks=False)]
    except OSError:
        return []


def _collect_all(directory: str, found: Set[str]) -> None:
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        _collect_all(entry.path, found)
                    elif entry.is_file():
                        found.add(os.path.normpath(entry.path))
                except OSError:
                    continue
    except OSError:
        return


def expand_sorted(root: str, patterns: Iterable[str], exclude: Optional[Iterable[str]] = None) -> List[str]:
    """`expand(patterns) - expand(exclude)`, sorted."""
    matched = expand(root, patterns)
    if exclude:
        matched -= expand(root, exclude)
    return sorted(matched)
