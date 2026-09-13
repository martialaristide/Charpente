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
from typing import Callable, List, Optional

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


def _build_dir(workspace: Workspace, config: str, target: Target) -> Path:
    return workspace.location / "build" / config / target.name


def _run(argv: List[str], run: RunFn) -> "subprocess.CompletedProcess":
    return run(argv, capture_output=True, text=True, shell=False)


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
    out_dir = _build_dir(workspace, config, target)
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
            return TargetResult(target.name, ok=False, error=(result.stderr or result.stdout).strip(), log=log)

    output_path = out_dir / flags.output_filename(target, target_os, toolchain)
    needs_link = any_compiled or not output_path.exists()
    if not needs_link:
        return TargetResult(target.name, ok=True, output_path=output_path, skipped=True, log=log)

    argv = flags.link_args(toolchain, target, objects, output_path)
    log.append(" ".join(argv))
    result = _run(argv, run)
    if result.returncode != 0:
        return TargetResult(target.name, ok=False, error=(result.stderr or result.stdout).strip(), log=log)

    return TargetResult(target.name, ok=True, output_path=output_path, log=log)


def build_workspace(
    workspace: Workspace,
    toolchain: Toolchain,
    target_os: OS,
    *,
    config: str = "Debug",
    run: RunFn = subprocess.run,
    keep_going: bool = False,
) -> BuildResult:
    """Builds every target in dependency order. Stops at the first failure
    unless keep_going=True, in which case it skips only the targets that
    depend (directly or transitively) on a failed one."""
    order = workspace.build_order()
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
