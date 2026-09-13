"""Orchestrates a build: resolve sources, decide what needs recompiling,
run the compiler/linker, report results.

Incremental checks are timestamp-based only (object file newer than its
source => skip) -- no per-header dependency tracking in this version. That
is a real, known limitation (editing a header won't trigger a rebuild of
the .cpp files that include it), not an oversight; `charpente clean` is
the escape hatch, and proper dependency-file tracking (-MMD/-showIncludes)
is a natural next step once the basics are solid.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Set

from . import flags
from .dsl.model import Kind, OS, Target, Workspace
from .toolchains import Toolchain

RunFn = Callable[..., "subprocess.CompletedProcess"]


@dataclass
class TargetResult:
    target_name: str
    ok: bool
    output_path: Optional[Path] = None
    skipped: bool = False  # nothing to do: every object and the output were already up to date
    error: str = ""
    log: List[str] = field(default_factory=list)


@dataclass
class BuildResult:
    ok: bool
    targets: List[TargetResult] = field(default_factory=list)

    def target(self, name: str) -> Optional[TargetResult]:
        return next((t for t in self.targets if t.target_name == name), None)


def _needs_rebuild(source: Path, obj: Path) -> bool:
    if not obj.exists():
        return True
    return source.stat().st_mtime > obj.stat().st_mtime


def build_dir(workspace: Workspace, config: str, target: Target) -> Path:
    return workspace.location / "build" / config / target.name


def _run(argv: List[str], run: RunFn) -> "subprocess.CompletedProcess":
    return run(argv, capture_output=True, text=True, shell=False)


def _error_text(result: "subprocess.CompletedProcess") -> str:
    """Both streams, not just one: a compiler/linker can split a single
    failure across stdout and stderr (e.g. GCC's "undefined reference"
    detail lines on stderr alongside collect2's summary line also on
    stderr, or informational compiler output on stdout with the actual
    error on stderr) -- picking only one risks silently dropping the part
    a human (or --ai-diagnose) actually needs to see."""
    parts = [s for s in (result.stdout, result.stderr) if s and s.strip()]
    return "\n".join(parts).strip()


def build_target(
    workspace: Workspace,
    target: Target,
    toolchain: Toolchain,
    target_os: OS,
    *,
    config: str = "Debug",
    run: RunFn = subprocess.run,
) -> TargetResult:
    debug = config.lower() == "debug"
    out_dir = build_dir(workspace, config, target)
    obj_dir = out_dir / "obj"
    obj_dir.mkdir(parents=True, exist_ok=True)

    sources = target.resolved_sources()
    if not sources:
        return TargetResult(target.name, ok=False,
                            error=f"Target {target.name!r} has no source files "
                                  f"(check its sources()/exclude() patterns).")

    log: List[str] = []
    objects: List[Path] = []
    any_compiled = False

    for source in sources:
        obj = obj_dir / (source.stem + (".obj" if flags.family(toolchain) == "msvc" else ".o"))
        objects.append(obj)
        if not _needs_rebuild(source, obj):
            continue
        any_compiled = True
        argv = flags.compile_args(toolchain, target, source, obj, debug=debug)
        log.append(" ".join(argv))
        result = _run(argv, run)
        if result.returncode != 0:
            return TargetResult(target.name, ok=False, error=_error_text(result), log=log)

    output_path = out_dir / flags.output_filename(target, target_os, toolchain)
    needs_link = any_compiled or not output_path.exists()
    if not needs_link:
        return TargetResult(target.name, ok=True, output_path=output_path, skipped=True, log=log)

    # Each dependency's own build directory is where its .a/.lib landed --
    # added as a library search path so `t.links([dep_name])` resolves
    # without the .charpente file having to know Charpente's build layout.
    dependency_dirs = [
        build_dir(workspace, config, workspace.targets[dep])
        for dep in target.depends_on
        if dep in workspace.targets
    ]
    argv = flags.link_args(toolchain, target, objects, output_path, library_dirs=dependency_dirs)
    log.append(" ".join(argv))
    result = _run(argv, run)
    if result.returncode != 0:
        return TargetResult(target.name, ok=False, error=_error_text(result), log=log)

    return TargetResult(target.name, ok=True, output_path=output_path, log=log)


def dependency_closure(workspace: Workspace, target_name: str) -> Set[str]:
    """`target_name` plus everything it depends on, transitively -- the
    minimal set of targets that must be built (in workspace.build_order()
    order) to produce `target_name` correctly. Used by commands (`run`,
    `package`, `test`) that build a single target directly: without this,
    asking for a target in a configuration that's never been built before
    would try to link against a dependency's library that was never built
    for that configuration either."""
    needed: Set[str] = set()

    def visit(name: str) -> None:
        if name in needed or name not in workspace.targets:
            return
        needed.add(name)
        for dep in workspace.targets[name].depends_on:
            visit(dep)

    visit(target_name)
    return needed


def build_workspace(
    workspace: Workspace,
    toolchain: Toolchain,
    target_os: OS,
    *,
    config: str = "Debug",
    run: RunFn = subprocess.run,
    keep_going: bool = False,
    only: Optional[Iterable[str]] = None,
) -> BuildResult:
    """Builds every target in dependency order (or, with `only`, just the
    given subset -- still in dependency order, still with the same
    keep_going semantics -- see dependency_closure() for building one
    target plus what it needs). Stops at the first failure unless
    keep_going=True, in which case it skips only the targets that depend
    (directly or transitively) on a failed one."""
    order = workspace.build_order()
    if only is not None:
        only_set = set(only)
        order = [name for name in order if name in only_set]
    results: List[TargetResult] = []
    failed: set[str] = set()

    for name in order:
        target = workspace.targets[name]
        blocked_by = failed.intersection(target.depends_on)
        if blocked_by:
            results.append(TargetResult(
                name, ok=False,
                error=f"Skipped: depends on failed target(s) {sorted(blocked_by)}.",
            ))
            failed.add(name)
            continue

        result = build_target(workspace, target, toolchain, target_os, config=config, run=run)
        results.append(result)
        if not result.ok:
            failed.add(name)
            if not keep_going:
                break

    return BuildResult(ok=not failed, targets=results)
