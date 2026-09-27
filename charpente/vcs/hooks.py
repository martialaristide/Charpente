"""Git hooks that run the quality gate: `charpente hooks install | uninstall | status`.

The hooks Charpente writes carry a marker line. It never overwrites a hook it did not write (unless `--force`, which keeps
the old one as `<name>.pre-charpente` and puts it back on `uninstall`). Git lets anyone skip hooks with `--no-verify`;
Charpente cannot prevent that, so `charpente push` and `charpente pr` report commits that have no passing gate record.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from .. import fsutil
from ..errors import ChError

MARKER = "# charpente-managed-hook v1"
HOOKS: Dict[str, str] = {
    "pre-commit": "check --level rapide --changed --hook pre-commit",
    "pre-push": "check --level standard --hook pre-push",
}


def script(name: str) -> str:
    """The POSIX shell script for hook `name` (Git for Windows runs hooks with its own sh)."""
    args = HOOKS[name]
    return (f"#!/bin/sh\n{MARKER}\n# Installed by `charpente hooks install`; remove with `charpente hooks uninstall`.\n"
            "if command -v charpente >/dev/null 2>&1; then\n"
            f"  exec charpente {args}\n"
            "elif command -v python3 >/dev/null 2>&1; then\n"
            f"  exec python3 -m charpente {args}\n"
            "else\n"
            f"  exec python -m charpente {args}\n"
            "fi\n")


@dataclass(frozen=True)
class HookState:
    name: str
    installed: bool          # a Charpente-managed hook is in place
    foreign: bool            # a hook Charpente did not write is in place
    backup: bool             # a `.pre-charpente` backup exists


def state(hooks_dir: Path) -> List[HookState]:
    out = []
    for name in HOOKS:
        path = hooks_dir / name
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        managed = MARKER in text
        out.append(HookState(name, managed, bool(text) and not managed, (hooks_dir / f"{name}.pre-charpente").is_file()))
    return out


def install(hooks_dir: Path, *, force: bool = False) -> List[Tuple[str, str]]:
    """Write the hooks; returns [(name, what happened)]."""
    hooks_dir.mkdir(parents=True, exist_ok=True)
    done: List[Tuple[str, str]] = []
    for current in state(hooks_dir):
        path = hooks_dir / current.name
        if current.foreign and not force:
            raise ChError("CH8013", command="charpente hooks install",
                          detail=f"{path} already exists and was not written by Charpente; use --force to keep it as "
                                 f"{current.name}.pre-charpente and replace it")
        action = "installed"
        if current.foreign:
            path.replace(hooks_dir / f"{current.name}.pre-charpente")
            action = "replaced (the old hook is kept as .pre-charpente)"
        elif current.installed:
            action = "updated"
        fsutil.write_text(path, script(current.name), newline="\n")
        try:
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass
        done.append((current.name, action))
    return done


def uninstall(hooks_dir: Path) -> List[Tuple[str, str]]:
    done: List[Tuple[str, str]] = []
    for current in state(hooks_dir):
        path = hooks_dir / current.name
        if not current.installed:
            done.append((current.name, "not managed by Charpente: left alone"))
            continue
        path.unlink()
        backup = hooks_dir / f"{current.name}.pre-charpente"
        if backup.is_file():
            os.replace(backup, path)
            done.append((current.name, "removed; the previous hook was restored"))
        else:
            done.append((current.name, "removed"))
    return done
