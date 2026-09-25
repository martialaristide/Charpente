"""Loading modules: from the store (and the bundled official ones) into an
`ExtensionRegistry`.

Loading is defensive. A module that cannot be loaded (bad entry point, API
mismatch, capabilities not approved, duplicate names) is *skipped* with a
recorded reason (`manager.problems`) -- it never takes Charpente down.
"""
from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..errors import ChError
from ..events import EventBus
from ..events.types import register_extension_event
from . import manifest as manifest_mod
from .api import Capabilities, Manifest
from .capabilities import ModuleContext
from .registry import ExtensionRegistry
from .store import InstalledModule, ModuleStore


class ModuleManager:
    def __init__(self, store: ModuleStore, *, builtin_commands: Optional[List[str]] = None,
                 workspace_root: Optional[Path] = None, bus: Optional[EventBus] = None,
                 opener: Optional[Callable[..., Any]] = None) -> None:
        self.store = store
        self.workspace_root = workspace_root
        self.bus = bus
        self.opener = opener
        self.registry = ExtensionRegistry(builtin_commands)
        self.problems: Dict[str, ChError] = {}
        self.loaded: Dict[str, Manifest] = {}
        self.contexts: Dict[str, ModuleContext] = {}

    def set_workspace(self, root: Optional[Path]) -> None:
        self.workspace_root = root
        for ctx in self.contexts.values():
            ctx.set_workspace_root(root)

    # ---------------------------------------------------------------- manifests
    def manifest_of(self, module: InstalledModule) -> Manifest:
        if module.bundled:
            from .official import bundled_manifest

            return bundled_manifest(module.name)
        return manifest_mod.load(Path(module.path))[0]

    def command_index(self) -> Dict[str, str]:
        """command name -> module name, from manifests only (imports nothing)."""
        index: Dict[str, str] = {}
        for module in self.store.list():
            if not module.enabled:
                continue
            try:
                manifest = self.manifest_of(module)
            except ChError:
                continue
            for command in manifest.provides.get("commands", ()):
                index.setdefault(command, module.name)
        return index

    # -------------------------------------------------------------------- load
    def load_all(self) -> ExtensionRegistry:
        for module in self.store.list():
            if module.enabled:
                self.load(module)
        return self.registry

    def load(self, module: InstalledModule) -> bool:
        if module.name in self.loaded:
            return True
        try:
            manifest = self.manifest_of(module)
            manifest_mod.check_api(manifest)
            approved = module.approved_caps()
            if not approved.covers(manifest.capabilities):
                raise ChError("CH7015", name=module.name,
                              detail="; ".join(manifest.capabilities.describe()))
            self._import_and_register(module, manifest, approved)
        except ChError as exc:
            self.registry.remove_module(module.name)
            self.problems[module.name] = exc
            return False
        self.loaded[module.name] = manifest
        return True

    def _import_and_register(self, module: InstalledModule, manifest: Manifest, approved: Capabilities) -> None:
        data_dir = self.store.data_dir(module.name)
        ctx = ModuleContext(manifest, approved, data_dir=data_dir, workspace_root=self.workspace_root,
                            bus=self.bus, opener=self.opener)
        for event_type in manifest.provides.get("events", ()):
            try:
                register_extension_event(event_type)
            except ValueError as exc:
                raise ChError("CH7009", name=module.name, detail=str(exc)) from exc
        module_path, _, func_name = manifest.entry.partition(":")
        if not module.bundled and module.path and module.path not in sys.path:
            # Stays on sys.path for the process: submodules are imported lazily, e.g. when a command runs.
            sys.path.insert(0, module.path)
        _purge_foreign(module_path, module.path)
        try:
            imported = importlib.import_module(module_path)
            register = getattr(imported, func_name)
            view = self.registry.for_module(manifest)
            try:
                nparams = len(inspect.signature(register).parameters)
            except (TypeError, ValueError):
                nparams = 2
            register(view, ctx) if nparams >= 2 else register(view)
        except ChError:
            raise
        except Exception as exc:  # module code: anything can go wrong
            raise ChError("CH7009", name=module.name, detail=f"{type(exc).__name__}: {exc}") from exc
        self.contexts[module.name] = ctx


def _purge_foreign(entry_module: str, folder: str) -> None:
    """Forget an already-imported package of the same name that came from somewhere
    else (an earlier version of the module, or another module using the same
    package name), so this module's own code is the one imported."""
    top = entry_module.split(".", 1)[0]
    importlib.invalidate_caches()
    for name in [n for n in sys.modules if n == top or n.startswith(top + ".")]:
        origin = str(getattr(sys.modules[name], "__file__", "") or "")
        if origin and folder and not origin.startswith(folder):
            del sys.modules[name]
