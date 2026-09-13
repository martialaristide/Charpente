"""Data model for a Charpente workspace: plain dataclasses with no behavior
of their own. The DSL (api.py) populates them; the builders (builders/)
read them. Keeping them dumb makes both sides independently testable."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class Kind(Enum):
    EXECUTABLE = "executable"
    STATIC_LIBRARY = "static_library"
    SHARED_LIBRARY = "shared_library"
    TEST = "test"


class Language(Enum):
    C = "c"
    CPP = "cpp"


class OS(Enum):
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"


@dataclass
class Target:
    """One buildable unit (an executable, a library, a test binary)."""

    name: str
    kind: Kind = Kind.EXECUTABLE
    language: Language = Language.CPP
    standard: str = "c++17"

    source_patterns: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    include_dirs: List[str] = field(default_factory=list)
    define_macros: List[str] = field(default_factory=list)
    link_libraries: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)

    extra_compile_flags: List[str] = field(default_factory=list)
    extra_link_flags: List[str] = field(default_factory=list)

    # Filled in by the loader once the workspace's own directory is known;
    # never set directly from a .charpente file.
    location: Optional[Path] = None

    def resolved_sources(self) -> List[Path]:
        """Expand source_patterns/exclude_patterns against `location` into a
        sorted, deduplicated list of real files. Pure and side-effect free
        so it can be unit tested without touching a real build."""
        if self.location is None:
            raise ValueError(f"Target {self.name!r} has no location set; "
                              f"resolved_sources() must run after the loader "
                              f"attaches it.")
        matched: set[Path] = set()
        for pattern in self.source_patterns:
            matched.update(self.location.glob(pattern))
        excluded: set[Path] = set()
        for pattern in self.exclude_patterns:
            excluded.update(self.location.glob(pattern))
        return sorted(p for p in matched - excluded if p.is_file())


@dataclass
class Workspace:
    """The root of a loaded .charpente file: one or more Targets, plus
    workspace-wide settings that apply to all of them."""

    name: str
    configurations: List[str] = field(default_factory=lambda: ["Debug", "Release"])
    targets: Dict[str, Target] = field(default_factory=dict)

    # Absolute directory containing the root .charpente file. Set by the
    # loader, not by DSL code.
    location: Optional[Path] = None

    def add_target(self, target: Target) -> None:
        if target.name in self.targets:
            raise ValueError(f"Target {target.name!r} is already defined in "
                              f"workspace {self.name!r}.")
        self.targets[target.name] = target

    def build_order(self) -> List[str]:
        """Topologically sorted target names (dependencies before
        dependents). Raises ValueError on an unknown dependency or a cycle,
        naming the target so the error is actionable.

        `path` is the chain of targets currently being visited, root first,
        NOT including `name` itself -- so `path + [name]` is always the
        full chain down to (and including) the node under inspection.
        """
        order: List[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str, path: List[str]) -> None:
            if name in visited:
                return
            if name not in self.targets:
                offender = path[-1] if path else name
                raise ValueError(
                    f"Target {offender!r} depends on unknown target {name!r}."
                )
            if name in visiting:
                cycle = " -> ".join(path + [name])
                raise ValueError(f"Dependency cycle detected: {cycle}")
            visiting.add(name)
            for dep in self.targets[name].depends_on:
                visit(dep, path + [name])
            visiting.discard(name)
            visited.add(name)
            order.append(name)

        for target_name in self.targets:
            visit(target_name, [])
        return order
