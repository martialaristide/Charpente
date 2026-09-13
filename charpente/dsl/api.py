"""The public DSL surface: what a .charpente file actually calls.

Design note: a .charpente file is executed as plain Python (see loader.py),
so `Workspace`/`Target` are ordinary context managers built around a bit of
module-level state -- there is no parser, no grammar, no magic beyond
`__enter__`/`__exit__` pushing and popping "the current thing" so nested
calls know what they're configuring.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from . import model as _model
from .model import Kind, Language, OS

__all__ = ["Workspace", "Target", "Kind", "Language", "OS", "current_workspace"]

_current_workspace: Optional[_model.Workspace] = None
_current_target: Optional[_model.Target] = None
_pending_location: Optional[Path] = None
_last_workspace: Optional[_model.Workspace] = None


def current_workspace() -> Optional[_model.Workspace]:
    """The Workspace currently open (inside its `with` block), or None. For
    the DSL's own use (e.g. a helper function that needs "the workspace
    being built right now")."""
    return _current_workspace


def last_loaded_workspace() -> Optional[_model.Workspace]:
    """The most recently *completed* `with Workspace(...)` block, even
    after its `with` has exited -- this is what the loader reads once
    exec() of the whole file has finished."""
    return _last_workspace


def set_pending_location(directory: Optional[Path]) -> None:
    """Called by the loader, before exec()'ing a .charpente file, with that
    file's parent directory -- the only way `Workspace()` can know where it
    lives, since the DSL file itself never states its own path."""
    global _pending_location
    _pending_location = directory


def _reset_state() -> None:
    """Clear module-level state between file loads (tests, and a loader
    that runs more than once in the same process)."""
    global _current_workspace, _current_target, _last_workspace
    _current_workspace = None
    _current_target = None
    _last_workspace = None


class Workspace:
    """`with Workspace("Name") as ws: ...` -- opens a new workspace and
    makes it the target of any `Target(...)` block declared inside."""

    def __init__(self, name: str):
        self._model = _model.Workspace(name=name, location=_pending_location)

    def __enter__(self) -> "Workspace":
        global _current_workspace
        if _current_workspace is not None:
            raise RuntimeError(
                f"Workspace {self._model.name!r} opened while workspace "
                f"{_current_workspace.name!r} is still open. Workspaces "
                f"cannot be nested."
            )
        _current_workspace = self._model
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        global _current_workspace, _last_workspace
        if exc_type is None:
            _last_workspace = self._model
        _current_workspace = None

    def configurations(self, names: Iterable[str]) -> "Workspace":
        self._model.configurations = list(names)
        return self

    @property
    def model(self) -> _model.Workspace:
        return self._model


class Target:
    """`with Target("name") as t: t.kind(...)...` -- declares one buildable
    unit inside the currently-open Workspace."""

    def __init__(self, name: str):
        if _current_workspace is None:
            raise RuntimeError(
                f"Target {name!r} declared outside of any `with "
                f"Workspace(...)` block."
            )
        self._model = _model.Target(name=name, location=_current_workspace.location)

    def __enter__(self) -> "Target":
        global _current_target
        _current_target = self._model
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        global _current_target
        _current_workspace.add_target(self._model)
        _current_target = None

    def kind(self, value: Kind) -> "Target":
        self._model.kind = value
        return self

    def language(self, value: Language) -> "Target":
        self._model.language = value
        return self

    def standard(self, value: str) -> "Target":
        self._model.standard = value
        return self

    def sources(self, patterns: Iterable[str]) -> "Target":
        self._model.source_patterns.extend(patterns)
        return self

    def exclude(self, patterns: Iterable[str]) -> "Target":
        self._model.exclude_patterns.extend(patterns)
        return self

    def include_dirs(self, dirs: Iterable[str]) -> "Target":
        self._model.include_dirs.extend(dirs)
        return self

    def defines(self, macros: Iterable[str]) -> "Target":
        self._model.define_macros.extend(macros)
        return self

    def links(self, libraries: Iterable[str]) -> "Target":
        self._model.link_libraries.extend(libraries)
        return self

    def depends_on(self, targets: Iterable[str]) -> "Target":
        self._model.depends_on.extend(targets)
        return self

    def compile_flags(self, flags: Iterable[str]) -> "Target":
        self._model.extra_compile_flags.extend(flags)
        return self

    def link_flags(self, flags: Iterable[str]) -> "Target":
        self._model.extra_link_flags.extend(flags)
        return self
