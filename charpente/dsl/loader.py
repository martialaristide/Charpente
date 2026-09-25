"""Loads a .charpente file: consent check, then exec() into a namespace
pre-populated with the DSL surface, then hand back the Workspace it built."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..errors import ChError, ChFileNotFoundError
from . import api
from .model import Workspace
from .trust import ensure_trusted


class WorkspaceLoadError(ChError):
    """The file ran, but didn't produce a usable Workspace (or raised)."""


def _dsl_globals(file_path: Path) -> Dict[str, Any]:
    globals_dict: Dict[str, Any] = {
        "__file__": str(file_path),
        "__name__": "__charpente_workspace__",
        "__builtins__": __builtins__,
    }
    for name in api.__all__:
        globals_dict[name] = getattr(api, name)
    return globals_dict


def load_workspace(entry_file: str, *, prompt: Optional[Callable[[str], str]] = None) -> Workspace:
    """Load the workspace defined by `entry_file`. Raises FileNotFoundError,
    TrustRequiredError/TrustDeniedError, or WorkspaceLoadError."""
    file_path = Path(entry_file).resolve()
    if not file_path.exists():
        raise ChFileNotFoundError("CH1018", path=str(file_path))

    ensure_trusted(file_path, kind="workspace", prompt=prompt)

    api._reset_state()
    api.set_pending_location(file_path.parent)
    globals_dict = _dsl_globals(file_path)

    try:
        source = file_path.read_text(encoding="utf-8-sig")
        code = compile(source, str(file_path), "exec")
        exec(code, globals_dict)
    except (SyntaxError, Exception) as e:
        raise WorkspaceLoadError("CH1004", path=str(file_path), detail=str(e)) from e
    finally:
        api.set_pending_location(None)

    workspace = api.last_loaded_workspace()
    if workspace is None:
        raise WorkspaceLoadError("CH1005", path=str(file_path))
    return workspace
