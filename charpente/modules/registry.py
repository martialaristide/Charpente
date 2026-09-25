"""The extension registry: what the loaded modules have registered.

A module's `register(registry, ctx)` calls the `add_*` methods. Registration
is checked against the manifest (a module may only register what it declared
in `[provides]`), names are unique per extension kind (CH7008), and a module
can never replace a built-in command (CH7013).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ..errors import ChError
from .api import EXTENSION_KINDS, Manifest

BUILTIN_MODULE = "charpente"


@dataclass(frozen=True)
class Extension:
    kind: str
    name: str
    obj: Any
    module: str


class ExtensionRegistry:
    def __init__(self, builtin_commands: Optional[List[str]] = None) -> None:
        self._items: Dict[str, Dict[str, Extension]] = {kind: {} for kind in EXTENSION_KINDS}
        self._builtin_commands = set(builtin_commands or [])
        self._owner_manifest: Dict[str, Manifest] = {}

    # -------------------------------------------------------------- module scope
    def for_module(self, manifest: Manifest) -> "ModuleRegistry":
        self._owner_manifest[manifest.name] = manifest
        return ModuleRegistry(self, manifest)

    def _add(self, module: str, kind: str, name: str, obj: Any) -> None:
        if kind not in self._items:
            raise ValueError(f"unknown extension kind {kind!r}")
        manifest = self._owner_manifest.get(module)
        if manifest is not None:
            declared = manifest.provides.get(EXTENSION_KINDS[kind], ())
            if name not in declared:
                raise ChError("CH7014", module=module, kind=kind, name=name,
                              key=EXTENSION_KINDS[kind])
        if kind == "command" and name in self._builtin_commands:
            raise ChError("CH7013", module=module, name=name)
        existing = self._items[kind].get(name)
        if existing is not None:
            raise ChError("CH7008", module=module, kind=kind, name=name, owner=existing.module)
        self._items[kind][name] = Extension(kind, name, obj, module)

    def add_builtin(self, kind: str, name: str, obj: Any) -> None:
        """For Charpente's own built-in providers (no manifest to check)."""
        self._add(BUILTIN_MODULE, kind, name, obj)

    # ----------------------------------------------------------------- queries
    def get(self, kind: str, name: str) -> Optional[Extension]:
        return self._items[kind].get(name)

    def all(self, kind: str) -> List[Extension]:
        return list(self._items[kind].values())

    def names(self, kind: str) -> List[str]:
        return sorted(self._items[kind])

    def by_module(self, module: str) -> List[Extension]:
        return [e for kind in self._items.values() for e in kind.values() if e.module == module]

    def remove_module(self, module: str) -> None:
        for kind in self._items.values():
            for name in [n for n, e in kind.items() if e.module == module]:
                del kind[name]


class ModuleRegistry:
    """The view a module gets: registration methods bound to its own name."""

    def __init__(self, registry: ExtensionRegistry, manifest: Manifest) -> None:
        self._registry = registry
        self.manifest = manifest

    def _register(self, kind: str, name: str, obj: Any) -> None:
        self._registry._add(self.manifest.name, kind, name, obj)

    def add_toolchain(self, provider: Any) -> None:
        self._register("toolchain", provider.name, provider)

    def add_platform(self, provider: Any) -> None:
        self._register("platform", provider.name, provider)

    def add_language(self, provider: Any) -> None:
        self._register("language", provider.name, provider)

    def add_kind(self, name: str, provider: Any = None) -> None:
        self._register("kind", name, provider)

    def add_packager(self, provider: Any) -> None:
        self._register("packager", provider.name, provider)

    def add_check(self, check: Any) -> None:
        self._register("quality_check", check.name, check)

    def add_notifier(self, notifier: Any) -> None:
        self._register("notifier", notifier.name, notifier)

    def add_ai_provider(self, name: str, factory: Callable[..., Any]) -> None:
        self._register("ai_provider", name, factory)

    def add_template(self, template: Any) -> None:
        self._register("template", template.name, template)

    def add_command(self, command: Any) -> None:
        self._register("command", command.name, command)

    def add_subscriber(self, subscriber: Any) -> None:
        self._register("event_subscriber", subscriber.name, subscriber)
