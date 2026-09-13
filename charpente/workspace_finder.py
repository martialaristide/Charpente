"""Finds the .charpente file a command should operate on: explicit --file,
otherwise the single .charpente file in the current directory (or the
nearest ancestor that has exactly one)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional


class WorkspaceNotFoundError(Exception):
    pass


class AmbiguousWorkspaceError(Exception):
    pass


def find_workspace_file(start_dir: Optional[Path] = None, explicit: Optional[str] = None) -> Path:
    if explicit:
        path = Path(explicit).resolve()
        if not path.exists():
            raise WorkspaceNotFoundError(f"No such file: {path}")
        return path

    current = (start_dir or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        matches = sorted(directory.glob("*.charpente"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(m.name for m in matches)
            raise AmbiguousWorkspaceError(
                f"Multiple .charpente files in {directory}: {names}. "
                f"Use --file to pick one."
            )
    raise WorkspaceNotFoundError(
        f"No .charpente file found in {current} or its parent directories."
    )
