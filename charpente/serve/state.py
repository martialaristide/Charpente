"""The server's view of one workspace: loading it, describing its targets, and building/testing/running them.

Everything a client can ask for goes through this class, so the BSP handlers, the WebSocket API and the tests share one
implementation. It never prompts (stdin is the protocol channel): a workspace file that has not been approved yet is an
error that says how to approve it.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import urllib.parse
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from .. import builder, cross, flags, platforms, toolchains
from ..core import history, process
from ..core.planner import effective_scope
from ..dsl.model import Kind, Target, Workspace
from ..errors import ChError
from ..events import Event, EventBus
from ..platform import host_os
from ..quality import gate
from ..workspace_finder import find_workspace_file
from .rpc import INTERNAL_ERROR, RpcError

BUSY = -32000
NOT_LOADED = -32001

_TAGS = {Kind.EXECUTABLE: "application", Kind.TEST: "test", Kind.STATIC_LIBRARY: "library", Kind.SHARED_LIBRARY: "library",
         Kind.PLUGIN: "library", Kind.HEADER_ONLY: "library"}


def path_to_uri(path: Path) -> str:
    return path.resolve().as_uri()


def uri_to_path(uri: str) -> Path:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "file":
        raise RpcError(-32602, f"only file: URIs are supported (got {uri!r})")
    text = urllib.parse.unquote(parsed.path)
    if sys.platform == "win32" and len(text) > 2 and text[0] == "/" and text[2] == ":":
        text = text[1:]
    return Path(text)


def severity_to_bsp(severity: str) -> int:
    """BSP: 1 Error, 2 Warning, 3 Information, 4 Hint."""
    return {"error": 1, "warning": 2, "note": 3, "hint": 4}.get(severity, 1)


class ServerState:
    def __init__(self, root: Path, workspace_file: Optional[str] = None) -> None:
        self.root = root.resolve()
        self.workspace_file = workspace_file
        self.workspace: Optional[Workspace] = None
        self.load_error: Optional[str] = None
        self.notice: Optional[str] = None                 # set while declared packages are not installed
        self._build_lock = threading.Lock()
        self.subscribers: Dict[int, Callable[[Dict[str, Any]], None]] = {}
        self._next_subscriber = 1
        self._sub_lock = threading.Lock()
        self.options: List[str] = []

    # ------------------------------------------------------------------ loading
    def load(self) -> Workspace:
        """(Re)load the workspace. Errors are remembered and raised as RPC errors with Charpente's own message."""
        from ..commands._common import load

        try:
            path = find_workspace_file(start_dir=self.root, explicit=self.workspace_file)
            self.root = path.parent
            self.notice = None
            try:
                self.workspace = load(str(path), self.options)
            except ChError as exc:
                if exc.code != "CH6005":
                    raise
                # Packages are declared but not installed yet: the project can still be shown and edited; building it is refused
                # (with this message) until they are installed.
                self.workspace = load(str(path), self.options, materialize_packages=False)
                self.notice = f"[{exc.code}] {exc}"
            self.load_error = None
        except ChError as exc:
            self.workspace = None
            self.load_error = f"[{exc.code}] {exc}"
            raise RpcError(NOT_LOADED, f"[{exc.code}] {exc}", {"code": exc.code}) from exc
        return self.workspace

    def require(self) -> Workspace:
        if self.workspace is None:
            return self.load()
        return self.workspace

    def workspace_path(self) -> Path:
        return find_workspace_file(start_dir=self.root, explicit=self.workspace_file)

    def safe_path(self, relative: str, *, for_write: bool = False) -> Path:
        """`relative` (a project-relative path with `/`) as an absolute path, refusing anything that leaves the project: `..`, absolute
        paths, drive letters, and symbolic links pointing outside. Writing under `.git` is refused (use Git for that)."""
        text = relative.replace("\\", "/")
        parts = [p for p in text.split("/") if p not in ("", ".")]
        if text.startswith("/") or (len(text) > 1 and text[1] == ":") or ".." in parts:
            raise RpcError(-32602, f"path outside the project: {relative!r}")
        if for_write and ".git" in [p.lower() for p in parts]:
            raise RpcError(-32602, "files under .git are managed by Git, not written directly")
        root = self.root.resolve()
        candidate = root.joinpath(*parts).resolve()
        if candidate != root and root not in candidate.parents:
            raise RpcError(-32602, f"path outside the project: {relative!r}")
        return candidate

    # ------------------------------------------------------------------ events
    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> int:
        with self._sub_lock:
            ident = self._next_subscriber
            self._next_subscriber += 1
            self.subscribers[ident] = callback
        return ident

    def unsubscribe(self, ident: int) -> None:
        with self._sub_lock:
            self.subscribers.pop(ident, None)

    def _publish(self, event: Event) -> None:
        with self._sub_lock:
            callbacks = list(self.subscribers.values())
        data = event.to_dict()
        for callback in callbacks:
            try:
                callback(data)
            except Exception:
                pass

    # ------------------------------------------------------------------ describing
    def target_id(self, name: str) -> str:
        return f"{path_to_uri(self.root)}?id={urllib.parse.quote(name)}"

    @staticmethod
    def target_name(uri: str) -> str:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(uri).query)
        if "id" not in query:
            raise RpcError(-32602, f"not a Charpente target id: {uri}")
        return query["id"][0]

    def own_targets(self) -> Dict[str, Target]:
        workspace = self.require()
        return {n: t for n, t in workspace.targets.items() if not t.external}

    def get_target(self, name: str) -> Target:
        workspace = self.require()
        if name not in workspace.targets:
            raise RpcError(-32602, f"unknown target {name!r} (known: {', '.join(sorted(self.own_targets()))})")
        return workspace.targets[name]

    def build_target(self, name: str) -> Dict[str, Any]:
        """A BSP `BuildTarget`."""
        target = self.get_target(name)
        buildable = target.kind not in (Kind.HEADER_ONLY,)
        return {
            "id": {"uri": self.target_id(name)}, "displayName": name, "baseDirectory": path_to_uri(target.location or self.root),
            "tags": [_TAGS.get(target.kind, "application")], "languageIds": [target.language.value],
            "dependencies": [{"uri": self.target_id(d)} for d in target.dependencies() if d in self.require().targets],
            "capabilities": {"canCompile": buildable, "canTest": target.kind == Kind.TEST,
                             "canRun": target.kind in (Kind.EXECUTABLE, Kind.TEST), "canDebug": False},
            "dataKind": "cpp", "data": {"version": "", "compiler": "", "cCompiler": "", "cppCompiler": ""},
        }

    def sources(self, name: str) -> List[Path]:
        return [Path(p) for p in self.get_target(name).resolved_sources()]

    def targets_containing(self, path: Path) -> List[str]:
        wanted = path.resolve()
        found = []
        for name in self.own_targets():
            try:
                if any(Path(s).resolve() == wanted for s in self.sources(name)):
                    found.append(name)
            except (OSError, ChError):
                continue
        return found

    def cpp_options(self, name: str) -> Dict[str, Any]:
        """`copts`, `defines`, `linkopts` for editors/language servers (from the effective target, host toolchain)."""
        workspace = self.require()
        try:
            target_os, toolchain = cross.select(None, None)
        except ChError:
            toolchain = None
        if toolchain is not None:
            _, effective = effective_scope(workspace, toolchain, "Debug", [name])
            target = effective[name]
        else:
            target = workspace.targets[name]
        copts = [f"-std={target.standard}"] if not (toolchain and flags.family(toolchain) == "msvc") else [f"/std:{target.standard}"]
        base = target.location or self.root
        copts += [f"-I{d if Path(d).is_absolute() else base / d}" for d in target.include_dirs] + list(target.extra_compile_flags)
        return {"target": {"uri": self.target_id(name)}, "copts": copts, "defines": list(target.define_macros),
                "linkopts": [f"-l{lib}" for lib in target.link_libraries] + list(target.extra_link_flags),
                "linkshared": target.kind in (Kind.SHARED_LIBRARY, Kind.PLUGIN)}

    def compile_commands(self, config: str = "Debug") -> List[Dict[str, Any]]:
        """A `compile_commands.json` (clang's compilation database) for every source of every own target, with the exact
        arguments the engine compiles it with -- what clangd and other C/C++ language servers read."""
        workspace = self.require()
        try:
            _, toolchain = cross.select(None, None)
        except ChError as exc:
            raise RpcError(INTERNAL_ERROR, f"[{exc.code}] {exc}", {"code": exc.code}) from exc
        names = list(self.own_targets())
        _, effective = effective_scope(workspace, toolchain, config, names)
        out_dir = self.root / "build" / "compile-commands"
        entries: List[Dict[str, Any]] = []
        for name in names:
            target = effective[name]
            if target.kind == Kind.HEADER_ONLY:
                continue
            base = target.location or self.root
            target = replace(target, include_dirs=[d if Path(d).is_absolute() else str(base / d) for d in target.include_dirs])
            for source in self.sources(name):
                obj = out_dir / name / (source.name + (".obj" if flags.family(toolchain) == "msvc" else ".o"))
                try:
                    argv = flags.compile_args(toolchain, target, source, obj, debug=config == "Debug")
                except ChError:
                    continue                                           # a file this toolchain cannot compile: nothing to tell clangd
                entries.append({"directory": str(self.root), "file": str(source), "arguments": argv, "output": str(obj)})
        return entries

    def graph(self) -> Dict[str, Any]:
        workspace = self.require()
        nodes = [{"name": n, "kind": t.kind.value, "language": t.language.value, "external": t.external,
                  "sources": len(self.sources(n)) if not t.external else 0} for n, t in workspace.targets.items()]
        edges = [{"from": n, "to": d} for n, t in workspace.targets.items() for d in t.dependencies() if d in workspace.targets]
        return {"nodes": nodes, "edges": edges, "order": workspace.build_order()}

    def info(self) -> Dict[str, Any]:
        workspace = self.require()
        try:
            host = platforms.host().name
        except ChError:
            host = ""
        return {"name": workspace.name, "version": workspace.version, "root": str(self.root),
                "file": str(find_workspace_file(start_dir=self.root, explicit=self.workspace_file)),
                "configurations": list(workspace.configurations), "platforms": list(workspace.platforms),
                "requires": list(workspace.requires), "kits": dict(workspace.kits), "host": host, "notice": self.notice,
                "options": {n: {"default": _option_text(o.default), "help": o.help, "kind": o.kind,
                                "choices": [str(c) for c in (o.choices or ())],
                                "value": _option_text(workspace.option_values.get(n, o.default))}
                            for n, o in workspace.options.items()}}

    def toolchain_report(self) -> Dict[str, Any]:
        detected = toolchains.detect(host_os())
        return {"toolchains": [{"name": t.name, "compiler": t.cxx_compiler, "crossOnly": t.cross_only, "targets": list(t.targets)}
                               for t in detected],
                "platforms": [{"name": p.name, "tier": p.tier, "family": p.family,
                               "buildable": p.name == (platforms.host().name if _has_host() else "") or any(
                                   cross.can_target(t, p) for t in detected)} for p in platforms.all_platforms()]}

    # ------------------------------------------------------------------ building
    def compile(self, names: Sequence[str], *, config: str = "Debug", platform: Optional[str] = None,
                toolchain: Optional[str] = None, jobs: int = 0, use_cache: bool = True,
                on_event: Optional[Callable[[Event], None]] = None) -> Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Build `names` (and what they need). Returns (ok, per-target results, diagnostics). One build at a time."""
        workspace = self.require()
        if self.notice:
            raise RpcError(NOT_LOADED, self.notice + " Install them (charpente pkg install) and reload.", {"code": "CH6005"})
        if not self._build_lock.acquire(blocking=False):
            raise RpcError(BUSY, "a build is already running")
        try:
            args = argparse.Namespace(platform=platform, toolchain=toolchain, sanitize=None, coverage=False)
            from ..commands._common import toolchain_for

            try:
                target_os, tc = toolchain_for(args, workspace)
            except ChError as exc:
                raise RpcError(INTERNAL_ERROR, f"[{exc.code}] {exc}", {"code": exc.code}) from exc
            closure: Set[str] = set()
            for name in names:
                closure |= builder.dependency_closure(workspace, name)
            bus = EventBus()
            diagnostics: List[Dict[str, Any]] = []

            def observe(event: Event) -> None:
                if event.type == "diagnostic.emitted":
                    diagnostics.append(dict(event.payload))
                self._publish(event)
                if on_event is not None:
                    on_event(event)

            bus.subscribe(observe, sync=True)
            history.HistoryRecorder(bus, builder.state_dir(workspace) / "history.db", command="build", config=config, toolchain=tc.name)
            bus.emit("session.started", command="serve.compile", argv=list(names), cwd=str(self.root), version="", config=config)
            begun = time.monotonic()
            result = builder.build_workspace(workspace, tc, target_os, config=config, only=closure or None, jobs=jobs, bus=bus,
                                             use_cache=use_cache)
            bus.emit("session.finished", ok=result.ok, exit_code=0 if result.ok else 1, duration=time.monotonic() - begun)
            bus.flush()
            results = [{"target": r.target_name, "ok": r.ok, "output": str(r.output_path) if r.output_path else None,
                        "error": r.error, "code": r.error_code, "executed": r.executed, "cached": r.cached,
                        "upToDate": r.up_to_date} for r in result.targets]
            return result.ok, results, diagnostics
        finally:
            self._build_lock.release()

    def run_cli(self, args: Sequence[str], *, timeout: float = 3600) -> Tuple[int, str]:
        """Run `charpente <args>` as a subprocess in the project (tests, runs, explanations). Returns (exit code, output)."""
        # (process.run gives a captured child no stdin: it never reads, or holds open, the protocol channel)
        result = process.run([sys.executable, "-m", "charpente", *args], cwd=str(self.root), timeout=timeout)
        return result.returncode, result.output

    def check(self, level: Optional[str] = None, changed: bool = False, bus: Optional[EventBus] = None) -> Dict[str, Any]:
        outcome = gate.run_gate(self.root, level=level, changed=changed, bus=bus)
        return {**outcome.to_dict(), "findings": [
            {"check": r.name, "message": f.message, "file": f.file, "line": f.line, "column": f.column, "severity": f.severity,
             "code": f.code, "fix": f.fix} for r in outcome.results for f in r.findings]}

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        workspace = self.require()
        return [{"id": s.id, "command": s.command, "ok": s.ok, "duration": s.duration, "started": s.started, "config": s.config,
                 "toolchain": s.toolchain, "executed": s.executed, "cached": s.cached}
                for s in history.list_sessions(builder.state_dir(workspace) / "history.db", limit=limit)]


def _option_text(value: Any) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


def _has_host() -> bool:
    try:
        platforms.host()
        return True
    except ChError:
        return False
