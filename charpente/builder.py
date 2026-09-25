"""Building a workspace: the stable, high-level entry point.

`build_workspace` plans the workspace into an action graph
(`core.planner`), runs it with the engine (`core.engine`: header-exact
incremental builds, content cache, parallelism) and folds the per-action
results back into the per-target results the commands print.

Everything observable is also emitted on the event bus
(`bus=`), which is how the terminal, JSONL files, the history database and
Studio follow a build.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from .core import analysis, compdb, fastpath, hashing, process
from .core import engine as engine_mod
from .core.cache import LocalCache
from .core.planner import Plan, plan_workspace
from .core.planner import build_dir as _build_dir
from .core.statcache import StatCache
from .core.state import StateDB
from .core.toolid import ToolIdentities
from .dsl.model import OS, Target, Workspace
from .errors import ChError
from .events import EventBus
from .toolchains import Toolchain

RunFn = process.Runner


@dataclass
class TargetResult:
    target_name: str
    ok: bool
    output_path: Optional[Path] = None
    skipped: bool = False  # nothing to do: every action was already up to date
    error: str = ""
    error_code: str = ""
    log: List[str] = field(default_factory=list)
    executed: int = 0
    cached: int = 0
    up_to_date: int = 0


@dataclass
class BuildResult:
    ok: bool
    targets: List[TargetResult] = field(default_factory=list)
    interrupted: bool = False
    duration: float = 0.0
    engine: Optional[engine_mod.EngineResult] = None
    plan: Optional[Plan] = None

    def target(self, name: str) -> Optional[TargetResult]:
        return next((t for t in self.targets if t.target_name == name), None)


def build_dir(workspace: Workspace, config: str, target: Target) -> Path:
    return _build_dir(workspace, config, target)


def state_dir(workspace: Workspace) -> Path:
    """Where the engine keeps its per-workspace state (removed by `charpente clean`)."""
    return workspace.root / "build" / ".charpente"


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


def _fold(plan: Plan, result: engine_mod.EngineResult) -> List[TargetResult]:
    """Per-action results -> per-target results, in workspace build order."""
    graph = plan.graph
    out: List[TargetResult] = []
    for name in plan.order:
        if name in plan.errors:
            err = plan.errors[name]
            out.append(TargetResult(name, ok=False, error=err.message, error_code=err.code))
            continue
        ids = plan.target_actions.get(name)
        if not ids:
            continue
        acts = [result.results.get(i) for i in ids]
        acts_present = [a for a in acts if a is not None]
        failed = [a for a in acts_present if a.status == engine_mod.STATUS_FAILED]
        blocked = [a for a in acts_present if a.status == engine_mod.STATUS_BLOCKED]
        cancelled = [a for a in acts_present if a.status == engine_mod.STATUS_CANCELLED]
        log = [" ".join(a.command) for a in acts_present if a.status == engine_mod.STATUS_EXECUTED and a.command]
        n_exec = sum(a.status == engine_mod.STATUS_EXECUTED for a in acts_present)
        n_cached = sum(a.status == engine_mod.STATUS_CACHE_HIT for a in acts_present)
        n_fresh = sum(a.status == engine_mod.STATUS_UP_TO_DATE for a in acts_present)
        if failed:
            failed_ids = {a.id for a in failed}
            text = "\n".join(dict.fromkeys(a.output for a in sorted(failed, key=lambda a: ids.index(a.id))
                                            if a.output)) or "build failed"
            kind_code = "CH3003" if any(graph.actions[i].kind != "compile" for i in failed_ids) else "CH3002"
            out.append(TargetResult(name, ok=False, error=text, error_code=kind_code, log=log,
                                     executed=n_exec, cached=n_cached, up_to_date=n_fresh))
        elif blocked:
            culprits = sorted({graph.actions[d].target for a in blocked for d in graph.deps[a.id]
                               if d in result.results and result.results[d].status == engine_mod.STATUS_FAILED}
                              - {name})
            if not culprits:
                culprits = sorted(t for t in plan.order if t != name and any(
                    result.results.get(i) is not None and result.results[i].status == engine_mod.STATUS_FAILED
                    for i in plan.target_actions.get(t, [])))
            err = ChError("CH3006", targets=culprits)
            out.append(TargetResult(name, ok=False, error=err.message, error_code=err.code, log=log,
                                     executed=n_exec, cached=n_cached, up_to_date=n_fresh))
        elif cancelled:
            continue  # never attempted (fail-fast stopped the build before it)
        else:
            out.append(TargetResult(
                name, ok=True, output_path=plan.outputs[name], log=log,
                skipped=n_exec == 0 and n_cached == 0, executed=n_exec, cached=n_cached,
                up_to_date=n_fresh))
    return out


def _context(workspace: Workspace, toolchain: Toolchain, target_os: OS, config: str, scope: List[str],
             sources: Dict[str, List[str]]) -> List[str]:
    """Everything (other than file contents) that determines what a build does."""
    from . import _version, flags

    fam = flags.family(toolchain)
    tools = ToolIdentities()
    tool_keys = sorted({tools.identify(t, fam).key() for t in (
        toolchain.c_compiler, toolchain.cxx_compiler, toolchain.archiver, toolchain.linker)})
    parts = [_version.__version__, config, target_os.value, toolchain.name, str(workspace.root),
             "|".join(tool_keys), "|".join(f"{k}={os.environ.get(k, '')}" for k in engine_mod.KEYED_ENV),
             ",".join(scope)]
    for name in scope:
        parts.append(repr(workspace.targets[name]))
        parts.append(hashing.digest_parts(*sources[name]))
    return parts


def _fast_result(stamp: fastpath.Stamp, scope: List[str], events: EventBus) -> BuildResult:
    total = sum(int(t.get("actions", 0)) for t in stamp.targets.values())
    events.emit("graph.analyzed", actions=total, targets=len(stamp.targets), critical_path=0.0, config="")
    targets: List[TargetResult] = []
    for name in scope:
        info = stamp.targets.get(name)
        if info is None:
            continue
        events.emit("target.up_to_date", target=name)
        targets.append(TargetResult(name, ok=True, output_path=Path(str(info["output"])), skipped=True,
                                    up_to_date=int(info.get("actions", 0))))
    return BuildResult(ok=True, targets=targets)


def _write_stamp(path: Path, plan: Plan, state: StateDB, context: str,
                 sources: Dict[str, List[str]], result: engine_mod.EngineResult) -> None:
    """After a fully successful build: remember the metadata of every file involved."""
    if plan.errors or not result.ok:
        return
    names: Dict[str, None] = {}
    for paths in sources.values():
        for p in paths:
            names[p] = None
    for aid in plan.graph.actions:
        record = state.get_action(aid)
        if record is None:
            return
        for dep in record.deps:
            names[dep] = None
        for out in record.outputs:
            names[out] = None
        for inp in record.inputs:
            names[inp] = None
    fresh = StatCache()          # a new listing: the build just changed the directories
    dirs = fastpath.collect(names, fresh)
    if dirs is None:
        return
    targets = {name: {"output": str(plan.outputs[name]), "actions": len(plan.target_actions[name])}
               for name in plan.outputs}
    fastpath.write(path, fastpath.Stamp(context=context, targets=targets, dirs=dirs,
                                        created_ns=fastpath.now_ns()))


def build_workspace(
    workspace: Workspace,
    toolchain: Toolchain,
    target_os: OS,
    *,
    config: str = "Debug",
    run: RunFn = process.raw_run,
    keep_going: bool = False,
    only: Optional[Iterable[str]] = None,
    jobs: int = 0,
    bus: Optional[EventBus] = None,
    use_cache: bool = True,
    cache: Optional[LocalCache] = None,
    write_compdb: bool = True,
    fast_path: bool = True,
) -> BuildResult:
    """Builds every target in dependency order (or, with `only`, just the
    given subset -- see `dependency_closure()` for building one target plus
    what it needs). Stops at the first failure unless keep_going=True, in
    which case it skips only the targets that depend (directly or
    transitively) on a failed one. Independent work runs in parallel
    (`jobs`, default: one per CPU).

    When nothing changed since the last fully successful build, the answer
    comes from file metadata alone (`core.fastpath`) without planning."""
    own_bus = bus is None
    events = bus or EventBus()
    try:
        return _build(workspace, toolchain, target_os, config, run, keep_going, only, jobs, events,
                      use_cache, cache, write_compdb, fast_path)
    finally:
        if own_bus:
            events.close()


def _build(workspace: Workspace, toolchain: Toolchain, target_os: OS, config: str, run: RunFn,
           keep_going: bool, only: Optional[Iterable[str]], jobs: int, events: EventBus, use_cache: bool,
           cache: Optional[LocalCache], write_compdb: bool, fast_path: bool) -> BuildResult:
    order = workspace.build_order()                 # raises for unknown dependencies and cycles
    wanted = set(only) if only is not None else None
    scope = [n for n in order if wanted is None or n in wanted]
    sources = {name: workspace.targets[name].source_files() for name in scope}

    context: Optional[str] = None
    stamp_file: Optional[Path] = None
    if fast_path:
        context = fastpath.context_digest(_context(workspace, toolchain, target_os, config, scope, sources))
        stamp_file = fastpath.stamp_path(state_dir(workspace), f"{config}|{','.join(scope)}")
        stamp = fastpath.load(stamp_file)
        if stamp is not None and fastpath.verify(stamp, context, StatCache()):
            return _fast_result(stamp, scope, events)

    plan = plan_workspace(workspace, toolchain, target_os, config=config, only=only, sources=sources)

    first_error: Optional[str] = None
    for name in plan.order:
        if name in plan.errors:
            first_error = name
            break

    graph = plan.graph
    if write_compdb and len(graph):
        compdb.write(graph, workspace.root / "build" / "compile_commands.json")
    runnable: Optional[Set[str]] = None
    if first_error is not None and not keep_going:
        # A target that cannot even be planned stops the build, as a failed
        # compile always did: only what precedes it in build order runs.
        limit = plan.order.index(first_error)
        keep = set(plan.order[:limit])
        runnable = {aid for name in keep for aid in plan.target_actions.get(name, [])}

    state = StateDB(state_dir(workspace) / "state.db")
    try:
        the_cache = cache if cache is not None else (LocalCache() if use_cache else None)
        engine = engine_mod.Engine(state, events, cache=the_cache, runner=run, jobs=jobs,
                                   keep_going=keep_going, root=workspace.root)
        result = engine.run(graph, only=runnable)
        for hint in analysis.hints_from_reasons({aid: r.reasons for aid, r in result.results.items()
                                                 if r.status == engine_mod.STATUS_EXECUTED}, workspace.root):
            events.emit("hint.emitted", code=hint.code, message=hint.message, detail=dict(hint.detail))
        if stamp_file is not None and context is not None and runnable is None:
            _write_stamp(stamp_file, plan, state, context, sources, result)
    finally:
        state.close()

    targets = _fold(plan, result)
    if first_error is not None and not keep_going:
        # Drop anything reported after the first plan-level error.
        cutoff = plan.order.index(first_error)
        targets = [t for t in targets if plan.order.index(t.target_name) <= cutoff]
    ok = not result.interrupted and all(t.ok for t in targets)
    return BuildResult(ok=ok, targets=targets, interrupted=result.interrupted,
                       duration=result.duration, engine=result, plan=plan)


def build_target(
    workspace: Workspace,
    target: Target,
    toolchain: Toolchain,
    target_os: OS,
    *,
    config: str = "Debug",
    run: RunFn = process.raw_run,
    jobs: int = 0,
    bus: Optional[EventBus] = None,
    use_cache: bool = True,
) -> TargetResult:
    """Builds one target *without* its dependencies (they must already be
    built). Prefer `build_workspace(..., only=dependency_closure(...))`."""
    result = build_workspace(workspace, toolchain, target_os, config=config, run=run, only=[target.name],
                             jobs=jobs, bus=bus, use_cache=use_cache)
    found = result.target(target.name)
    if found is None:
        return TargetResult(target.name, ok=False, error="build interrupted", error_code="CH3008")
    return found
