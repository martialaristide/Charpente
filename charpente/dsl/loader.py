"""Loads a .charpente file: consent check, then exec() into a namespace
pre-populated with the DSL surface, then hand back the Workspace it built."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import api
from .model import Workspace
from .trust import ensure_trusted


class WorkspaceLoadError(Exception):
    """The file ran, but didn't produce a usable Workspace (or raised)."""


def _dsl_globals(file_path: Path) -> dict:
    globals_dict = {
        "__file__": str(file_path),
        "__name__": "__charpente_workspace__",
        "__builtins__": __builtins__,
    }
    for name in api.__all__:
        globals_dict[name] = getattr(api, name)
    return globals_dict


def load_workspace(entry_file: str, *, prompt=None) -> Workspace:
    """Load the workspace defined by `entry_file`. Raises FileNotFoundError,
    TrustRequiredError/TrustDeniedError, or WorkspaceLoadError."""
    file_path = Path(entry_file).resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Workspace file not found: {file_path}")

    ensure_trusted(file_path, kind="workspace", prompt=prompt)

    api._reset_state()
    api.set_pending_location(file_path.parent)
    globals_dict = _dsl_globals(file_path)

    try:
        source = file_path.read_text(encoding="utf-8-sig")
        code = compile(source, str(file_path), "exec")
        exec(code, globals_dict)
    except (SyntaxError, Exception) as e:
        raise WorkspaceLoadError(f"Error loading {file_path}: {e}") from e
    finally:
        api.set_pending_location(None)

    workspace = api.last_loaded_workspace()
    if workspace is None:
        raise WorkspaceLoadError(
            f"{file_path} did not define a workspace (no `with Workspace(...):` block)."
        )
    return workspace
