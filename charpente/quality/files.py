"""Which files a check looks at: everything tracked, or what changed since the last commit."""
from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Set

from ..core import process

SKIP_DIRS = {".git", "build", "dist", "node_modules", "__pycache__", ".venv", "venv", ".charpente", "vendor",
             ".mypy_cache", ".pytest_cache", ".ruff_cache"}
CPP_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp", ".m", ".mm")


def _git(root: Path, args: Sequence[str], run: Callable[..., process.ProcessResult] = process.run,
         which: Callable[[str], Optional[str]] = shutil.which) -> Optional[List[str]]:
    git = which("git")
    if not git:
        return None
    result = run([git, "-C", str(root), *args], timeout=120)
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


def is_git_repo(root: Path, run: Callable[..., process.ProcessResult] = process.run,
                which: Callable[[str], Optional[str]] = shutil.which) -> bool:
    return _git(root, ["rev-parse", "--is-inside-work-tree"], run, which) == ["true"]


def list_files(root: Path, run: Callable[..., process.ProcessResult] = process.run,
               which: Callable[[str], Optional[str]] = shutil.which) -> List[Path]:
    """Every file of the project: tracked and untracked-but-not-ignored when it is a Git repository, else a walk
    that skips build output and caches."""
    listed = _git(root, ["ls-files", "--cached", "--others", "--exclude-standard"], run, which)
    if listed is not None:
        return sorted((root / name) for name in listed
                      if (root / name).is_file() and not SKIP_DIRS.intersection(Path(name).parts[:-1]))
    found: List[Path] = []
    for folder, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        found += [Path(folder) / n for n in names]
    return sorted(found)


def changed_files(root: Path, run: Callable[..., process.ProcessResult] = process.run,
                  which: Callable[[str], Optional[str]] = shutil.which) -> Optional[List[Path]]:
    """Files modified, added or untracked since HEAD (None when this is not a Git repository or Git is missing)."""
    if not is_git_repo(root, run, which):
        return None
    names: Set[str] = set()
    for args in (["diff", "--name-only", "--diff-filter=d", "HEAD"], ["diff", "--name-only", "--diff-filter=d", "--cached"],
                 ["ls-files", "--others", "--exclude-standard"]):
        names.update(_git(root, args, run, which) or [])
    if _git(root, ["rev-parse", "--verify", "HEAD"], run, which) is None:       # no commit yet: everything is new
        names.update(_git(root, ["ls-files", "--cached"], run, which) or [])
    return sorted(root / n for n in names if (root / n).is_file() and not SKIP_DIRS.intersection(Path(n).parts[:-1]))


def matches_any(relative: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(relative, p) or fnmatch.fnmatch(Path(relative).name, p) for p in patterns)
