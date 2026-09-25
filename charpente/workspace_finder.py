"""Finds the .charpente file a command should operate on: explicit --file,
otherwise the single .charpente file in the current directory (or the
nearest ancestor that has exactly one)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .errors import ChError


class WorkspaceNotFoundError(ChError):
    pass


class AmbiguousWorkspaceError(ChError):
    pass


def find_workspace_file(start_dir: Optional[Path] = None, explicit: Optional[str] = None) -> Path:
    if explicit:
        path = Path(explicit).resolve()
        if not path.exists():
            raise WorkspaceNotFoundError("CH1001", path=str(path))
        return path

    current = (start_dir or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        # Files only: a project's own `.charpente/` *directory* (state, hooks,
        # notify.toml, quality.toml) also matches the pattern and is not a workspace.
        matches = sorted(m for m in directory.glob("*.charpente") if m.is_file() and m.name != ".charpente")
        if not matches and (directory / "charpente.toml").is_file():
            return directory / "charpente.toml"       # the declarative form, when there is no .charpente file
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(m.name for m in matches)
            raise AmbiguousWorkspaceError("CH1003", directory=str(directory), names=names)
    raise WorkspaceNotFoundError("CH1002", directory=str(current))
