"""The build engine: run an action graph, as little and as fast as possible.

For each action, in dependency order and in parallel:

1. **Freshness** -- compare what the action looks like now (command, tool,
   input contents, discovered headers, outputs on disk) with what was recorded
   the last time it succeeded. Nothing changed: it is *up to date*.
2. **Cache** -- otherwise, look for a result under the content-derived key
   (local cache): a *cache hit* restores the outputs without running anything.
3. **Execute** -- otherwise run the command, record the headers it read, store
   the result in the cache and in the state database.

Freshness checks run inline on the scheduling thread (they are cheap and are
what a no-op build is made of); only real work is handed to worker threads.
Everything observable is emitted as events; nothing is printed here.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..errors import ChError
from ..events import EventBus
from . import depscan, diagnostics, hashing, process
from .actions import DEP_GNU, DEP_MSVC, Action
from .cache import LocalCache
from .graph import ActionGraph
from .statcache import StatCache
from .state import MISSING, ActionRecord, FileHasher, StateDB
from .toolid import ToolIdentities, ToolIdentity

# Environment variables that change what compilers/linkers produce; they are
# part of every action key when set. (PATH is deliberately absent: tool
# identity already captures which executable ran.)
KEYED_ENV = (
    "INCLUDE", "LIB", "LIBPATH", "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH",
    "OBJC_INCLUDE_PATH", "LIBRARY_PATH", "SDKROOT", "MACOSX_DEPLOYMENT_TARGET",
    "SOURCE_DATE_EPOCH", "CL", "_CL_", "LINK", "_LINK_",
)

STATUS_EXECUTED = "executed"
STATUS_CACHE_HIT = "cache_hit"
STATUS_UP_TO_DATE = "up_to_date"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"
STATUS_CANCELLED = "cancelled"

_OK = (STATUS_EXECUTED, STATUS_CACHE_HIT, STATUS_UP_TO_DATE)


@dataclass
class ActionResult:
    id: str
    status: str
    returncode: int = 0
    output: str = ""
    duration: float = 0.0
    reasons: List[str] = field(default_factory=list)
    command: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in _OK


@dataclass
class EngineResult:
    results: Dict[str, ActionResult]
    order: List[str]
    duration: float = 0.0
    interrupted: bool = False

    @property
    def ok(self) -> bool:
        return not self.interrupted and all(r.ok for r in self.results.values())

    def count(self, status: str) -> int:
        return sum(1 for r in self.results.values() if r.status == status)


@dataclass
class Decision:
    """Outcome of a freshness check (no execution involved)."""

    action_id: str
    fresh: bool
    reasons: List[str] = field(default_factory=list)


def _rel(path: str, base: Optional[Path]) -> str:
    if base is not None:
        try:
            return Path(path).resolve().relative_to(base.resolve()).as_posix()
        except (ValueError, OSError):
            pass
    return path


def default_jobs() -> int:
    return max(1, os.cpu_count() or 1)


class Engine:
    def __init__(
        self,
        state: StateDB,
        bus: EventBus,
        *,
        cache: Optional[LocalCache] = None,
        runner: Optional[process.Runner] = None,
        jobs: int = 0,
        keep_going: bool = False,
        root: Optional[Path] = None,
    ) -> None:
        self.state = state
        self.bus = bus
        self.cache = cache
        self.runner = runner
        self.jobs = jobs if jobs > 0 else default_jobs()
        self.keep_going = keep_going
        self.root = root
        self.stats = StatCache()
        self.hasher = FileHasher(state, stats=self.stats)
        self._env_memo: Dict[Tuple[Tuple[str, str], ...], List[Tuple[str, str]]] = {}
        # Tool identity always asks the real tool (never the injected test
        # runner): it describes the machine, and is remembered on disk.
        self.tools = ToolIdentities()

    # ================================================================ keys
    def _env_pairs(self, action: Action) -> List[Tuple[str, str]]:
        """Action-specific variables plus the inherited ones that affect compilers.
        Computed once per distinct `action.env` (the environment does not change mid-build)."""
        cached = self._env_memo.get(action.env)
        if cached is not None:
            return cached
        pairs = dict(action.env)
        for name in KEYED_ENV:
            value = os.environ.get(name)
            if value is not None and name not in pairs:
                pairs[name] = value
        result = sorted(pairs.items())
        self._env_memo[action.env] = result
        return result

    def _tool(self, action: Action) -> ToolIdentity:
        family = "msvc" if action.dep_format == DEP_MSVC else "gnu"
        return self.tools.identify(action.tool or action.argv[0], family)

    def _input_digests(self, action: Action) -> Dict[str, str]:
        return {str(p): self.hasher.digest(p) for p in action.inputs}

    def _key1(self, action: Action, inputs: Dict[str, str], env: List[Tuple[str, str]], tool: ToolIdentity) -> str:
        return hashing.digest_parts(
            "charpente-action/1", action.kind, json.dumps(list(action.argv)), str(action.cwd or ""),
            json.dumps(env), tool.key(), json.dumps(sorted(inputs.items())),
            json.dumps([str(o) for o in action.outputs]),
        )

    def _key2(self, key1: str, deps: List[str]) -> str:
        return hashing.digest_parts("charpente-deps/1", key1,
                                    json.dumps([[d, self.hasher.digest(d)] for d in sorted(deps)]))

    # ========================================================== freshness
    def evaluate(self, action: Action, *, rebuilt_upstream: Optional[List[str]] = None) -> Decision:
        """Is `action` up to date? (Never runs anything.)

        `rebuilt_upstream` lists actions known to be rebuilt in this run that
        this one depends on -- used by dry runs, where their outputs have not
        actually changed on disk yet.
        """
        reasons: List[str] = []
        if rebuilt_upstream:
            reasons.append("depends on " + ", ".join(rebuilt_upstream[:3])
                           + (f" (+{len(rebuilt_upstream) - 3} more)" if len(rebuilt_upstream) > 3 else "")
                           + " which will be rebuilt")
        rec = self.state.get_action(action.id)
        if rec is None:
            reasons.insert(0, "no previous build record")
            return Decision(action.id, False, reasons)

        argv = list(action.argv)
        if rec.argv != argv:
            reasons.append("command line changed: " + _argv_diff(rec.argv, argv))
        if rec.cwd != str(action.cwd or ""):
            reasons.append("working directory changed")
        tool = self._tool(action)
        if rec.tool != tool.key():
            reasons.append(f"tool changed ({_tool_version(rec.tool)} -> {tool.version or tool.path})")
        env = self._env_pairs(action)
        if [tuple(e) for e in rec.env] != env:
            old, new = dict(rec.env), dict(env)
            names = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
            reasons.append("environment changed: " + ", ".join(names))

        current_inputs = self._input_digests(action)
        for path, digest in current_inputs.items():
            before = rec.inputs.get(path)
            if before is None:
                reasons.append(f"new input: {_rel(path, self.root)}")
            elif before != digest:
                reasons.append(f"input changed: {_rel(path, self.root)}"
                               + (" (file is missing)" if digest == MISSING else ""))
        for path in rec.inputs:
            if path not in current_inputs:
                reasons.append(f"input removed: {_rel(path, self.root)}")

        for path, digest in rec.deps.items():
            now = self.hasher.digest(path)
            if now != digest:
                reasons.append(f"header {'removed' if now == MISSING else 'changed'}: {_rel(path, self.root)}")

        for out in action.outputs:
            fingerprint = rec.outputs.get(str(out))
            meta = self.stats.stat(str(out))
            if meta is None:
                reasons.append(f"output missing: {_rel(str(out), self.root)}")
                continue
            if fingerprint is None or [meta[0], meta[1]] != list(fingerprint):
                reasons.append(f"output modified outside the build: {_rel(str(out), self.root)}")
        return Decision(action.id, not reasons, reasons)

    # ============================================================ planning
    def plan(self, graph: ActionGraph) -> Dict[str, Decision]:
        """What *would* run, and why. Propagates staleness downstream, since a
        rebuilt object makes its link stale even though the object on disk is
        still the old one at this point."""
        decisions: Dict[str, Decision] = {}
        stale: Set[str] = set()
        for aid in graph.topological_order():
            upstream = sorted(d for d in graph.deps[aid] if d in stale)
            decision = self.evaluate(graph.actions[aid], rebuilt_upstream=upstream)
            decisions[aid] = decision
            if not decision.fresh:
                stale.add(aid)
        return decisions

    # ============================================================== running
    def run(self, graph: ActionGraph, *, only: Optional[Set[str]] = None) -> EngineResult:
        started = time.monotonic()
        selected = set(graph.actions) if only is None else graph.closure(only)
        order = [a for a in graph.topological_order() if a in selected]
        results: Dict[str, ActionResult] = {}
        if not order:
            return EngineResult(results, order, 0.0)

        durations = {aid: rec.duration for aid, rec in self.state.records() if aid in selected and rec.duration > 0}
        priority = graph.priorities(durations)
        total, _ = graph.critical_path(durations)
        targets = {graph.actions[a].target for a in order}
        self.bus.emit("graph.analyzed", actions=len(order), targets=len(targets),
                      critical_path=float(total), config="")

        pending = {aid: len(graph.deps[aid] & selected) for aid in order}
        seq = 0
        ready: List[Tuple[float, int, str]] = []

        import heapq

        def push(aid: str) -> None:
            nonlocal seq
            seq += 1
            heapq.heappush(ready, (-priority[aid], seq, aid))

        for aid in order:
            if pending[aid] == 0:
                push(aid)

        tracker = _TargetTracker(self.bus, graph, selected)
        stop = False
        interrupted = False
        inflight: Dict["Future[ActionResult]", str] = {}

        def complete(aid: str, result: ActionResult) -> None:
            nonlocal stop
            results[aid] = result
            tracker.finished(graph.actions[aid], result)
            if result.ok:
                for nxt in graph.dependents[aid] & selected:
                    pending[nxt] -= 1
                    if pending[nxt] == 0 and not stop:
                        push(nxt)
                return
            if self.keep_going:
                for blocked in sorted(graph.descendants([aid]) & selected):
                    if blocked not in results:
                        act = graph.actions[blocked]
                        results[blocked] = ActionResult(blocked, STATUS_BLOCKED,
                                                        output=f"depends on failed action {aid}")
                        self.bus.emit("action.blocked", action=blocked, target=act.target, kind=act.kind,
                                      because=[aid])
                        tracker.finished(act, results[blocked])
            else:
                stop = True

        pool = ThreadPoolExecutor(max_workers=self.jobs, thread_name_prefix="charpente-worker")
        try:
            while True:
                while ready and len(inflight) < self.jobs * 2 and not stop:
                    _, _, aid = heapq.heappop(ready)
                    if aid in results:
                        continue
                    action = graph.actions[aid]
                    decision = self.evaluate(action)
                    if decision.fresh:
                        self.bus.emit("action.up_to_date", action=aid, target=action.target, kind=action.kind)
                        complete(aid, ActionResult(aid, STATUS_UP_TO_DATE))
                        continue
                    tracker.started(action)
                    future = pool.submit(self._work, action, decision)
                    inflight[future] = aid
                if not inflight:
                    break
                done, _ = wait(list(inflight), return_when=FIRST_COMPLETED)
                for future in done:
                    aid = inflight.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:  # a bug in a worker must not hang or crash the build
                        result = ActionResult(aid, STATUS_FAILED, returncode=1,
                                              output=f"internal error: {type(exc).__name__}: {exc}")
                    complete(aid, result)
        except KeyboardInterrupt:
            interrupted = True
            stop = True
            for future in list(inflight):
                future.cancel()
            wait(list(inflight))  # let running children finish (they received the interrupt too)
        finally:
            pool.shutdown(wait=True)
            self.state.flush()

        for aid in order:
            if aid not in results:
                results[aid] = ActionResult(aid, STATUS_CANCELLED)
        return EngineResult(results, order, time.monotonic() - started, interrupted)

    # ================================================================ worker
    def _work(self, action: Action, decision: Decision) -> ActionResult:
        begin = time.monotonic()
        tool = self._tool(action)
        env = self._env_pairs(action)
        inputs = self._input_digests(action)
        key1 = self._key1(action, inputs, env, tool)

        if self.cache is not None and action.cacheable:
            hit = self._try_cache(action, key1, inputs, env, tool, decision)
            if hit is not None:
                hit.duration = time.monotonic() - begin
                return hit

        return self._execute(action, decision, key1, inputs, env, tool, begin)

    def _try_cache(self, action: Action, key1: str, inputs: Dict[str, str], env: List[Tuple[str, str]],
                   tool: ToolIdentity, decision: Decision) -> Optional[ActionResult]:
        assert self.cache is not None
        candidates: List[List[str]] = self.cache.manifest(key1) if action.dep_format else [[]]
        for deps in candidates:
            entry = self.cache.lookup(self._key2(key1, deps) if action.dep_format else key1)
            if entry is None:
                continue
            for out in action.outputs:
                _unlink(out)
            if not self.cache.restore(entry, list(action.outputs)):
                continue
            self._record(action, key1, inputs, env, tool, deps, entry.duration)
            self.bus.emit("action.cache_hit", action=action.id, target=action.target, kind=action.kind,
                          source="local", outputs=[str(o) for o in action.outputs])
            output = "\n".join(p for p in (entry.stdout, entry.stderr) if p.strip())
            self._diagnose(action, output)
            return ActionResult(action.id, STATUS_CACHE_HIT, output=output, reasons=decision.reasons)
        return None

    def _execute(self, action: Action, decision: Decision, key1: str, inputs: Dict[str, str],
                 env: List[Tuple[str, str]], tool: ToolIdentity, begin: float) -> ActionResult:
        self.bus.emit("action.started", action=action.id, target=action.target, kind=action.kind,
                      description=action.description, command=list(action.argv), reasons=decision.reasons[:5])
        # Outputs are removed first so a failed or partial run can never leave
        # something that looks valid (and `ar rcs` cannot keep stale members).
        for out in action.outputs:
            _unlink(out)
            out.parent.mkdir(parents=True, exist_ok=True)
            self.hasher.invalidate(out)
        if action.depfile is not None:
            _unlink(action.depfile)
            action.depfile.parent.mkdir(parents=True, exist_ok=True)

        run_env: Optional[Dict[str, str]] = None
        if action.env:
            run_env = dict(os.environ)
            run_env.update(dict(action.env))
        try:
            completed = process.run(list(action.argv), runner=self.runner,
                                    cwd=str(action.cwd) if action.cwd else None, env=run_env)
            returncode, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
        except ChError as exc:
            returncode, stdout, stderr = 127, "", exc.message

        duration = time.monotonic() - begin
        deps: List[Path] = []
        if action.dep_format == DEP_MSVC and returncode == 0:
            deps, stdout = depscan.parse_show_includes(stdout, action.cwd)
        elif action.dep_format == DEP_MSVC:
            _, stdout = depscan.parse_show_includes(stdout, action.cwd)
        output = "\n".join(p for p in (stdout, stderr) if p and p.strip()).strip()

        if returncode == 0:
            missing = [o for o in action.outputs if not o.exists()]
            if missing:
                returncode = 1
                output = ChError("CH3009", path=str(missing[0])).message
        if returncode != 0:
            self.bus.emit("action.failed", action=action.id, target=action.target, kind=action.kind,
                          returncode=returncode, duration=duration, output=output)
            self._diagnose(action, output)
            return ActionResult(action.id, STATUS_FAILED, returncode=returncode, output=output,
                                duration=duration, reasons=decision.reasons,
                                command=list(action.argv))

        if action.dep_format == DEP_GNU and action.depfile is not None:
            try:
                deps = depscan.parse_gnu_depfile(action.depfile.read_text(encoding="utf-8", errors="replace"),
                                                 action.cwd)
            except OSError:
                deps = []  # compiler without depfile support: fall back to source-only tracking
        source_paths = {str(p) for p in action.inputs}
        dep_strs = [str(d) for d in deps if str(d) not in source_paths]
        for out in action.outputs:
            self.hasher.invalidate(out)
        self._record(action, key1, inputs, env, tool, dep_strs, duration)

        if self.cache is not None and action.cacheable:
            if self.cache.store(self._key2(key1, dep_strs) if action.dep_format else key1,
                                list(action.outputs), stdout=stdout, stderr=stderr, duration=duration):
                if action.dep_format:
                    self.cache.add_to_manifest(key1, dep_strs)

        if output:
            self.bus.emit("action.output", action=action.id, target=action.target, stream="combined", text=output)
        self._diagnose(action, output)
        self.bus.emit("action.finished", action=action.id, target=action.target, kind=action.kind,
                      duration=duration, outputs=[str(o) for o in action.outputs])
        return ActionResult(action.id, STATUS_EXECUTED, output=output, duration=duration,
                            reasons=decision.reasons, command=list(action.argv))

    # ============================================================== records
    def _record(self, action: Action, key1: str, inputs: Dict[str, str], env: List[Tuple[str, str]],
                tool: ToolIdentity, deps: List[str], duration: float) -> None:
        outputs: Dict[str, List[int]] = {}
        for out in action.outputs:
            self.hasher.invalidate(out)                    # re-reads it with a real stat
            meta = self.stats.stat(str(out))
            if meta is not None:
                outputs[str(out)] = [meta[0], meta[1]]
        self.state.put_action(action.id, ActionRecord(
            key=key1, argv=list(action.argv), cwd=str(action.cwd or ""), tool=tool.key(), env=env,
            inputs=inputs, deps={d: self.hasher.digest(d) for d in deps}, outputs=outputs, duration=duration,
        ))

    def _diagnose(self, action: Action, output: str) -> None:
        if not output:
            return
        for diag in diagnostics.parse_output(output):
            self.bus.emit("diagnostic.emitted", file=diag.file, line=diag.line, column=diag.column,
                          severity=diag.severity, code=diag.code, message=diag.message, action=action.id)


# ===================================================================== helpers
def _unlink(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _argv_diff(old: List[str], new: List[str]) -> str:
    added = [a for a in new if a not in old]
    removed = [a for a in old if a not in new]
    parts = []
    if added:
        parts.append("added " + " ".join(added[:4]) + (" ..." if len(added) > 4 else ""))
    if removed:
        parts.append("removed " + " ".join(removed[:4]) + (" ..." if len(removed) > 4 else ""))
    return "; ".join(parts) or "arguments reordered"


def _tool_version(key: str) -> str:
    parts = key.split("|")
    return parts[1] if len(parts) > 1 and parts[1] else parts[0]


class _TargetTracker:
    """Derives target-level events (started / finished / up_to_date / failed)
    from action-level completions."""

    def __init__(self, bus: EventBus, graph: ActionGraph, selected: Set[str]) -> None:
        self.bus = bus
        self.total: Dict[str, int] = {}
        for aid in selected:
            t = graph.actions[aid].target
            self.total[t] = self.total.get(t, 0) + 1
        self.remaining = dict(self.total)
        self.counts: Dict[str, Dict[str, int]] = {t: {"executed": 0, "cached": 0, "up_to_date": 0}
                                                  for t in self.total}
        self.started_at: Dict[str, float] = {}
        self.announced: Set[str] = set()
        self.failed: Set[str] = set()
        self.not_ok: Set[str] = set()

    def started(self, action: Action) -> None:
        t = action.target
        if t not in self.announced:
            self.announced.add(t)
            self.started_at[t] = time.monotonic()
            self.bus.emit("target.started", target=t, actions=self.total[t])

    def finished(self, action: Action, result: ActionResult) -> None:
        t = action.target
        counts = self.counts[t]
        if result.status == STATUS_EXECUTED:
            counts["executed"] += 1
        elif result.status == STATUS_CACHE_HIT:
            counts["cached"] += 1
        elif result.status == STATUS_UP_TO_DATE:
            counts["up_to_date"] += 1
        else:
            self.not_ok.add(t)
            if result.status == STATUS_FAILED and t not in self.failed:
                self.failed.add(t)
                self.bus.emit("target.failed", target=t, error=result.output, code="CH3002")
        self.remaining[t] -= 1
        if self.remaining[t] == 0 and t not in self.not_ok:
            elapsed = time.monotonic() - self.started_at.get(t, time.monotonic())
            if counts["executed"] == 0 and counts["cached"] == 0:
                self.bus.emit("target.up_to_date", target=t)
            else:
                self.bus.emit("target.finished", target=t, duration=elapsed, executed=counts["executed"],
                              cached=counts["cached"], up_to_date=counts["up_to_date"])


__all__ = ["ActionResult", "Decision", "Engine", "EngineResult", "default_jobs",
           "STATUS_EXECUTED", "STATUS_CACHE_HIT", "STATUS_UP_TO_DATE", "STATUS_FAILED",
           "STATUS_BLOCKED", "STATUS_CANCELLED"]
