"""Actions: the unit of work of the engine. Pure data, no behaviour.

An action is a command plus everything that can change its result: the files
it reads, the files it writes, the environment variables that matter and the
identity of the tool. Two runs of an action with identical descriptions and
identical input *contents* must produce identical outputs -- that is what
makes caching sound.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

KIND_COMPILE = "compile"
KIND_LINK = "link"
KIND_ARCHIVE = "archive"
KIND_CUSTOM = "custom"

DEP_GNU = "gnu"    # a Makefile-style depfile written by -MMD -MF
DEP_MSVC = "msvc"  # "Note: including file:" lines on stdout (/showIncludes)


@dataclass(frozen=True)
class Action:
    id: str
    kind: str
    target: str
    argv: Tuple[str, ...]
    outputs: Tuple[Path, ...]
    inputs: Tuple[Path, ...] = ()
    #: ids of actions that must finish first, in addition to the edges inferred
    #: from outputs feeding inputs (used for pure ordering, e.g. `depends_on`).
    after: Tuple[str, ...] = ()
    env: Tuple[Tuple[str, str], ...] = ()
    #: the executable whose identity (path, version, binary digest) is part of the key
    tool: str = ""
    depfile: Optional[Path] = None
    dep_format: str = ""
    description: str = ""
    cacheable: bool = True
    #: the translation unit / primary input, for compile_commands.json
    source: Optional[Path] = None
    cwd: Optional[Path] = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("an action needs an id")
        if not self.argv or not all(isinstance(a, str) for a in self.argv):
            raise ValueError(f"action {self.id!r}: argv must be a non-empty tuple of strings")
        if not self.outputs:
            raise ValueError(f"action {self.id!r}: an action must declare at least one output")
        if self.dep_format and self.dep_format not in (DEP_GNU, DEP_MSVC):
            raise ValueError(f"action {self.id!r}: unknown dep_format {self.dep_format!r}")
        if self.dep_format == DEP_GNU and self.depfile is None:
            raise ValueError(f"action {self.id!r}: dep_format 'gnu' needs a depfile")

    def label(self) -> str:
        return self.description or self.id
