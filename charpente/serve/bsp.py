"""Build Server Protocol 2.1 (with its C/C++ extension) and Charpente's own `charpente/*` methods.

One dispatcher serves both: an editor or build client speaks BSP over stdio (`build/initialize`, `workspace/buildTargets`,
`buildTarget/compile` ...); Charpente Studio and the VS Code extension additionally call `charpente/*` (workspace info, the
target graph, the quality gate, `why`, history, event subscription) over the same connection or a WebSocket.

Progress and problems are pushed as notifications: `build/taskStart`, `build/taskFinish`, `build/logMessage`,
`build/publishDiagnostics` (BSP) and `charpente/event` (every engine event, for clients that subscribed).
"""
from __future__ import annotations

import argparse
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from .. import _version, i18n
from ..errors import describe
from ..events import Event
from .rpc import INVALID_PARAMS, SERVER_NOT_INITIALIZED, Dispatcher, RpcError
from .state import ServerState, path_to_uri, severity_to_bsp, uri_to_path

BSP_VERSION = "2.1.0"
Notify = Callable[[str, Any], None]

# BSP status codes
OK, ERROR, CANCELLED = 1, 2, 3


def _now() -> int:
    return int(time.time() * 1000)


def _params(params: Any) -> Dict[str, Any]:
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise RpcError(INVALID_PARAMS, "params must be an object")
    return params


def _parse_arguments(arguments: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parser.add_argument("--config", default="Debug")
    parser.add_argument("--platform")
    parser.add_argument("--toolchain")
    parser.add_argument("-j", "--jobs", type=int, default=0)
    parser.add_argument("--no-cache", action="store_true")
    try:
        parsed, _unknown = parser.parse_known_args([str(a) for a in arguments])
    except (argparse.ArgumentError, SystemExit) as exc:
        raise RpcError(INVALID_PARAMS, f"bad build arguments: {exc}") from exc
    return parsed


def _lsp_range(line: Optional[int], column: Optional[int]) -> Dict[str, Any]:
    start_line = max((line or 1) - 1, 0)
    start_col = max((column or 1) - 1, 0)
    return {"start": {"line": start_line, "character": start_col}, "end": {"line": start_line, "character": start_col + 1}}


def make_dispatcher(state: ServerState, notify: Notify, *, exit_callback: Callable[[], None] = lambda: None,
                    track_subscription: Callable[[int], None] = lambda ident: None) -> Dispatcher:
    """Wire every method to `state`. `notify(method, params)` pushes a notification to the connected client."""
    d = Dispatcher()
    flags: Dict[str, bool] = {"initialized": False, "shutdown": False}
    published: Dict[str, Set[str]] = {"files": set()}          # files we sent diagnostics for (to clear them next time)

    def bsp(fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
        def guarded(params: Any) -> Any:
            if not flags["initialized"]:
                raise RpcError(SERVER_NOT_INITIALIZED, "call build/initialize first")
            return fn(params)
        return guarded

    # ------------------------------------------------------------------ lifecycle
    def initialize(params: Any) -> Dict[str, Any]:
        p = _params(params)
        root = p.get("rootUri")
        if root:
            state.root = uri_to_path(root)
        flags["initialized"] = True
        languages = ["c", "cpp"]
        return {
            "displayName": "charpente", "version": _version.__version__, "bspVersion": BSP_VERSION,
            "capabilities": {"compileProvider": {"languageIds": languages}, "testProvider": {"languageIds": languages},
                             "runProvider": {"languageIds": languages}, "debugProvider": {"languageIds": []},
                             "inverseSourcesProvider": True, "dependencySourcesProvider": True, "dependencyModulesProvider": False,
                             "resourcesProvider": True, "outputPathsProvider": False, "buildTargetChangedProvider": False,
                             "jvmRunEnvironmentProvider": False, "jvmTestEnvironmentProvider": False, "canReload": True},
            "data": {"charpente": {"methods": [m for m in d.method_names if m.startswith("charpente/")]}},
        }

    d.add_method("build/initialize", initialize)
    d.add_notification("build/initialized", lambda params: None)
    def shutdown(params: Any) -> None:
        flags["shutdown"] = True

    d.add_method("build/shutdown", shutdown)
    d.add_notification("build/exit", lambda params: exit_callback())
    d.add_notification("$/cancelRequest", lambda params: None)       # builds cannot be interrupted yet: documented
    def reload_workspace(params: Any) -> None:
        state.load()

    d.add_method("workspace/reload", bsp(reload_workspace))

    # ------------------------------------------------------------------ targets
    def build_targets(params: Any) -> Dict[str, Any]:
        state.require()
        return {"targets": [state.build_target(n) for n in state.own_targets()]}

    d.add_method("workspace/buildTargets", bsp(build_targets))

    def wanted(p: Dict[str, Any]) -> List[str]:
        return [state.target_name(t["uri"]) for t in p.get("targets", [])]

    def sources(params: Any) -> Dict[str, Any]:
        items = []
        for name in wanted(_params(params)):
            items.append({"target": {"uri": state.target_id(name)},
                          "sources": [{"uri": path_to_uri(f), "kind": 1, "generated": False} for f in state.sources(name)]})
        return {"items": items}

    d.add_method("buildTarget/sources", bsp(sources))
    d.add_method("buildTarget/dependencySources", bsp(lambda params: {"items": [
        {"target": {"uri": state.target_id(n)}, "sources": []} for n in wanted(_params(params))]}))
    d.add_method("buildTarget/resources", bsp(lambda params: {"items": [
        {"target": {"uri": state.target_id(n)}, "resources": []} for n in wanted(_params(params))]}))

    def inverse_sources(params: Any) -> Dict[str, Any]:
        document = _params(params).get("textDocument", {}).get("uri")
        if not document:
            raise RpcError(INVALID_PARAMS, "textDocument.uri is required")
        return {"targets": [{"uri": state.target_id(n)} for n in state.targets_containing(uri_to_path(document))]}

    d.add_method("buildTarget/inverseSources", bsp(inverse_sources))
    d.add_method("buildTarget/cppOptions", bsp(lambda params: {"items": [state.cpp_options(n) for n in wanted(_params(params))]}))

    # ------------------------------------------------------------------ compile / test / run / clean
    def publish_diagnostics(diagnostics: List[Dict[str, Any]], origin: Optional[str], target_uri: str) -> None:
        by_file: Dict[str, List[Dict[str, Any]]] = {}
        for item in diagnostics:
            if not item.get("file"):
                continue
            path = Path(item["file"])
            uri = path_to_uri(path if path.is_absolute() else state.root / path)
            by_file.setdefault(uri, []).append({
                "range": _lsp_range(item.get("line"), item.get("column")), "severity": severity_to_bsp(str(item.get("severity", "error"))),
                "code": item.get("code"), "source": "charpente", "message": item.get("message", "")})
        for uri in published["files"] - set(by_file):            # fixed since last time: clear
            notify("build/publishDiagnostics", {"textDocument": {"uri": uri}, "buildTarget": {"uri": target_uri}, "originId": origin,
                                                "diagnostics": [], "reset": True})
        for uri, items in by_file.items():
            notify("build/publishDiagnostics", {"textDocument": {"uri": uri}, "buildTarget": {"uri": target_uri}, "originId": origin,
                                                "diagnostics": items, "reset": True})
        published["files"] = set(by_file)

    def compile_(params: Any) -> Dict[str, Any]:
        p = _params(params)
        names = wanted(p)
        origin = p.get("originId")
        args = _parse_arguments(p.get("arguments", []))
        task = {"id": str(uuid.uuid4())}
        target_uri = state.target_id(names[0]) if names else path_to_uri(state.root)
        notify("build/taskStart", {"taskId": task, "originId": origin, "eventTime": _now(), "message": "Compiling " + ", ".join(names),
                                   "dataKind": "compile-task", "data": {"target": {"uri": target_uri}}})

        def forward(event: Event) -> None:
            if event.type == "action.output":
                notify("build/logMessage", {"type": 3, "task": task, "originId": origin, "message": str(event.payload.get("text", ""))})
            elif event.type in ("target.finished", "target.failed"):
                notify("build/taskProgress", {"taskId": task, "originId": origin, "eventTime": _now(),
                                              "message": f"{event.payload.get('target')}: {event.type.split('.')[1]}"})

        ok, results, diagnostics = state.compile(names, config=args.config, platform=args.platform, toolchain=args.toolchain,
                                                 jobs=args.jobs, use_cache=not args.no_cache, on_event=forward)
        publish_diagnostics(diagnostics, origin, target_uri)
        errors = sum(1 for x in diagnostics if x.get("severity") == "error")
        notify("build/taskFinish", {"taskId": task, "originId": origin, "eventTime": _now(), "status": OK if ok else ERROR,
                                    "message": "Compiled" if ok else "Compilation failed", "dataKind": "compile-report",
                                    "data": {"target": {"uri": target_uri}, "originId": origin, "errors": errors,
                                             "warnings": len(diagnostics) - errors}})
        for result in results:
            if not result["ok"] and result["error"] and not diagnostics:
                notify("build/logMessage", {"type": 1, "task": task, "originId": origin, "message": result["error"]})
        return {"originId": origin, "statusCode": OK if ok else ERROR, "dataKind": "charpente/results", "data": results}

    d.add_method("buildTarget/compile", bsp(compile_))

    def run_cli(args: List[str], origin: Optional[str], message: str) -> Dict[str, Any]:
        task = {"id": str(uuid.uuid4())}
        notify("build/taskStart", {"taskId": task, "originId": origin, "eventTime": _now(), "message": message})
        code, output = state.run_cli(args)
        for line in output.splitlines():
            notify("build/logMessage", {"type": 3 if code == 0 else 1, "task": task, "originId": origin, "message": line})
        notify("build/taskFinish", {"taskId": task, "originId": origin, "eventTime": _now(), "status": OK if code == 0 else ERROR,
                                    "message": message})
        return {"originId": origin, "statusCode": OK if code == 0 else ERROR}

    def test(params: Any) -> Dict[str, Any]:
        p = _params(params)
        args = _parse_arguments(p.get("arguments", []))
        cmd = ["test", "--config", args.config] + (["--platform", args.platform] if args.platform else [])
        return run_cli(cmd, p.get("originId"), "Testing")

    def run(params: Any) -> Dict[str, Any]:
        """`arguments` are the program's own arguments (BSP); how to build it (`config`, `platform`) is in `data`."""
        p = _params(params)
        target = p.get("target", {}).get("uri")
        if not target:
            raise RpcError(INVALID_PARAMS, "target.uri is required")
        options: Dict[str, Any] = p["data"] if isinstance(p.get("data"), dict) else {}
        program = [str(a) for a in p.get("arguments", [])]
        cmd = ["run", "--target", state.target_name(target), "--config", str(options.get("config", "Debug"))]
        if options.get("platform"):
            cmd += ["--platform", str(options["platform"])]
        cmd += ["--"] * bool(program) + program
        return run_cli(cmd, p.get("originId"), f"Running {state.target_name(target)}")

    d.add_method("buildTarget/test", bsp(test))
    d.add_method("buildTarget/run", bsp(run))
    d.add_method("buildTarget/cleanCache", bsp(lambda params: {"message": run_cli(["clean"], None, "Cleaning")["statusCode"] == OK
                                                                and "Build directory removed" or "Clean failed", "cleaned": True}))

    # ------------------------------------------------------------------ Charpente's own methods
    d.add_method("charpente/workspace", lambda params: state.info())
    d.add_method("charpente/graph", lambda params: state.graph())
    d.add_method("charpente/compileCommands", lambda params: {"entries": state.compile_commands(str(_params(params).get("config", "Debug")))})
    d.add_method("charpente/toolchains", lambda params: state.toolchain_report())
    d.add_method("charpente/history", lambda params: state.history(int(_params(params).get("limit", 20))))
    d.add_method("charpente/reload", lambda params: (state.load(), state.info())[1])

    def build(params: Any) -> Dict[str, Any]:
        p = _params(params)
        names = p.get("targets") or list(state.own_targets())
        ok, results, diagnostics = state.compile(names, config=p.get("config", "Debug"), platform=p.get("platform"),
                                                 toolchain=p.get("toolchain"), jobs=int(p.get("jobs", 0)),
                                                 use_cache=bool(p.get("cache", True)))
        return {"ok": ok, "results": results, "diagnostics": diagnostics}

    d.add_method("charpente/build", build)

    def check(params: Any) -> Dict[str, Any]:
        p = _params(params)
        return state.check(level=p.get("level"), changed=bool(p.get("changed", False)))

    d.add_method("charpente/check", check)

    def explain(params: Any) -> Dict[str, Any]:
        code = str(_params(params).get("code", "")).strip().upper()
        lang = str(_params(params).get("lang", i18n.current_lang()))
        text = describe(code, lang) if lang in i18n.SUPPORTED else ""
        if not text:
            raise RpcError(INVALID_PARAMS, f"unknown error code {code!r}")
        return {"code": code, "text": text}

    d.add_method("charpente/explain", explain)

    def why(params: Any) -> Dict[str, Any]:
        p = _params(params)
        args = ["why"] + ([p["target"]] if p.get("target") else []) + ([p["file"]] if p.get("file") else [])
        code, output = state.run_cli(args)
        return {"exitCode": code, "text": output}

    d.add_method("charpente/why", why)

    def subscribe(params: Any) -> Dict[str, Any]:
        ident = state.subscribe(lambda event: notify("charpente/event", event))
        track_subscription(ident)                                 # so a closed connection can drop it
        return {"subscription": ident}

    d.add_method("charpente/subscribe", subscribe)
    def unsubscribe(params: Any) -> None:
        state.unsubscribe(int(_params(params).get("subscription", 0)))

    d.add_method("charpente/unsubscribe", unsubscribe)
    d.add_method("charpente/ping", lambda params: {"pong": True, "version": _version.__version__})
    return d


def bsp_connection_details(argv: List[str]) -> Dict[str, Any]:
    """The `.bsp/charpente.json` file BSP clients discover servers with."""
    return {"name": "charpente", "version": _version.__version__, "bspVersion": BSP_VERSION, "languages": ["c", "cpp"],
            "argv": argv}
