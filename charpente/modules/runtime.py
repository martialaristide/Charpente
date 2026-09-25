"""The process-wide registry: builtins plus every enabled module, built lazily.

`get_registry()` is what the rest of Charpente asks ("which toolchains exist?",
"is there a module command called `x`?"). Tests call `reset()` between cases.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, List, Optional

from ..errors import ChError
from .builtin import register_builtins
from .loader import ModuleManager
from .registry import ExtensionRegistry
from .store import ModuleStore

_lock = threading.RLock()
_manager: Optional[ModuleManager] = None


def builtin_command_names() -> List[str]:
    from ..commands import COMMANDS

    return list(COMMANDS)


def get_manager(workspace_root: Optional[Path] = None) -> ModuleManager:
    global _manager
    with _lock:
        if _manager is None:
            manager = ModuleManager(ModuleStore(), builtin_commands=builtin_command_names(),
                                    workspace_root=workspace_root)
            register_builtins(manager.registry)
            manager.load_all()
            _manager = manager
        return _manager


def get_registry() -> ExtensionRegistry:
    return get_manager().registry


def problems() -> Dict[str, ChError]:
    return dict(get_manager().problems)


def reset() -> None:
    """Forget the loaded registry (the next `get_registry()` rebuilds it)."""
    global _manager
    with _lock:
        _manager = None
