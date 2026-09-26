"""The methods Charpente Studio's panels call: files, DSL schema, profile, headers, Git, devices and logs, packages, options, terminal.

Every method is a thin layer over code the command line uses (Git wrapper, package index, history database...), so what Studio shows is what the
commands do. Anything that changes files is confined to the project folder (`ServerState.safe_path`); anything that starts a program takes an
argument list, never a command line for a shell.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import android, builder, harmony, shellenv
from .. import debug as debug_mod
from ..core import history, process
from ..core.analysis import header_costs
from ..core.state import StateDB
from ..dsl import api as dsl_api
from ..dsl import edit as dsl_edit
from ..dsl.model import Kind, Language
from ..errors import ChError
from ..pkg.index import RecipeIndex
from ..pkg.store import PackageStore
from ..vcs.git import Git
from . import insight, lsp
from .relay import Relays
from .rpc import INVALID_PARAMS, Dispatcher, RpcError
from .state import ServerState

MAX_TEXT_BYTES = 2 * 1024 * 1024
CONFLICT = -32011
NOT_TEXT = -32010
HIDDEN_DIRS = {".git", "build", "node_modules", "__pycache__", ".vs", ".idea", ".vscode-test", "out", ".cache"}
LANGUAGES = {".c": "c", ".h": "cpp", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp", ".inl": "cpp",
             ".charpente": "charpente", ".py": "python", ".md": "markdown", ".toml": "toml", ".json": "json", ".yml": "yaml", ".yaml": "yaml",
             ".txt": "text", ".cmake": "cmake", ".glsl": "glsl", ".vert": "glsl", ".frag": "glsl", ".java": "java", ".kt": "kotlin",
             ".swift": "swift", ".ts": "typescript", ".ets": "typescript", ".js": "javascript", ".html": "html", ".css": "css",
             ".sh": "shell", ".ps1": "powershell", ".xml": "xml", ".gradle": "groovy"}

Notify = Callable[[str, Any], None]


def sha256_text(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def language_of(path: Path) -> str:
    if path.name == "CMakeLists.txt":
        return "cmake"
    return LANGUAGES.get(path.suffix.lower(), "text")


class StudioApi:
    """State shared by one client connection: its running streams (device logs, terminal commands), stopped when it disconnects."""

    def __init__(self, state: ServerState, notify: Notify) -> None:
        self.state = state
        self.notify = notify
        self._streams: Dict[str, process.LineStream] = {}
        self._lock = threading.Lock()
        self.lsp = lsp.LspSessions(state.root, notify)
        self.dap = Relays(notify, "charpente/dap")

    # ------------------------------------------------------------------ helpers
    def _git(self) -> Git:
        git = Git(self.state.root)
        try:
            git.require_repo()
        except ChError as exc:
            raise RpcError(INVALID_PARAMS, f"[{exc.code}] {exc}", {"code": exc.code}) from exc
        return git

    def close(self) -> None:
        self.lsp.close()
        self.dap.close()
        with self._lock:
            streams, self._streams = list(self._streams.values()), {}
        for stream in streams:
            stream.stop()

    def _start_stream(self, kind: str, argv: List[str], *, cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None,
                      label: str = "") -> str:
        ident = uuid.uuid4().hex[:12]

        def on_line(line: str) -> None:
            self.notify("charpente/stream", {"id": ident, "kind": kind, "line": line})

        def on_exit(code: int) -> None:
            with self._lock:
                self._streams.pop(ident, None)
            self.notify("charpente/stream", {"id": ident, "kind": kind, "exit": code})

        try:
            stream = process.LineStream(argv, on_line, on_exit, cwd=cwd, env=env)
        except ChError as exc:
            raise RpcError(INVALID_PARAMS, f"[{exc.code}] {exc}", {"code": exc.code}) from exc
        with self._lock:
            self._streams[ident] = stream
        self.notify("charpente/stream", {"id": ident, "kind": kind, "started": label or " ".join(argv)})
        return ident

    def stop_stream(self, params: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            stream = self._streams.pop(str(params.get("id", "")), None)
        if stream is not None:
            stream.stop()
        return {"stopped": stream is not None}

    # ------------------------------------------------------------------ files
    def files_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        folder = self.state.safe_path(str(params.get("path", "")))
        if not folder.is_dir():
            raise RpcError(INVALID_PARAMS, f"not a folder: {params.get('path', '')!r}")
        entries = []
        for child in sorted(folder.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
            if child.name in HIDDEN_DIRS and child.is_dir():
                continue
            try:
                is_dir = child.is_dir()
                size = 0 if is_dir else child.stat().st_size
            except OSError:
                continue
            entries.append({"name": child.name, "path": child.relative_to(self.state.root).as_posix(), "dir": is_dir, "size": size,
                            "language": "" if is_dir else language_of(child)})
        return {"path": folder.relative_to(self.state.root).as_posix() if folder != self.state.root else "", "entries": entries}

    def files_read(self, params: Dict[str, Any]) -> Dict[str, Any]:
        path = self.state.safe_path(str(params.get("path", "")))
        if not path.is_file():
            raise RpcError(INVALID_PARAMS, f"not a file: {params.get('path', '')!r}")
        size = path.stat().st_size
        if size > MAX_TEXT_BYTES:
            raise RpcError(NOT_TEXT, f"{path.name} is {size} bytes: too big to edit here (limit {MAX_TEXT_BYTES})")
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RpcError(NOT_TEXT, f"{path.name} is not UTF-8 text") from exc
        return {"path": path.relative_to(self.state.root).as_posix(), "text": text, "sha256": sha256_text(data),
                "language": language_of(path), "size": size}

    def files_write(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Write a text file. With `expected` (the sha256 the client read), a file that changed meanwhile is a conflict, not overwritten."""
        rel = str(params.get("path", ""))
        path = self.state.safe_path(rel, for_write=True)
        text = params.get("text")
        if not isinstance(text, str):
            raise RpcError(INVALID_PARAMS, "text must be a string")
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise RpcError(NOT_TEXT, "the text is too big")
        expected = params.get("expected")
        if path.exists():
            if not path.is_file():
                raise RpcError(INVALID_PARAMS, f"not a file: {rel!r}")
            current = sha256_text(path.read_bytes())
            if expected is not None and expected != current:
                raise RpcError(CONFLICT, f"{path.name} changed on disk since you opened it", {"sha256": current})
        elif expected:
            raise RpcError(CONFLICT, f"{path.name} was deleted since you opened it")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode("utf-8")
        temporary = path.with_name(path.name + ".charpente-tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)                                 # a crash never leaves a half-written source file
        return {"path": path.relative_to(self.state.root).as_posix(), "sha256": sha256_text(data), "size": len(data)}

    def files_create(self, params: Dict[str, Any]) -> Dict[str, Any]:
        path = self.state.safe_path(str(params.get("path", "")), for_write=True)
        if path.exists():
            raise RpcError(CONFLICT, f"{path.name} already exists")
        if params.get("dir"):
            path.mkdir(parents=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
        return {"path": path.relative_to(self.state.root).as_posix()}

    # ------------------------------------------------------------------ debugging (DAP relay)
    def debug_available(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"debuggers": [{"name": d["name"], "version": d["version"]} for d in debug_mod.find_debuggers()]}

    def debug_start(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Start `charpente debug-adapter` for this project; the client then speaks DAP through `charpente/debug/send` and `charpente/dap`."""
        try:
            chosen = debug_mod.choose_debugger(str(params["debugger"]) if params.get("debugger") else None)
        except ChError as exc:
            raise RpcError(INVALID_PARAMS, f"[{exc.code}] {exc}", {"code": exc.code}) from exc
        argv = [sys.executable, "-m", "charpente", "debug-adapter", "--root", str(self.state.root), "--debugger", chosen["name"]]
        return {"id": self.dap.start(argv, cwd=str(self.state.root)), "debugger": chosen["name"]}

    def debug_send(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"sent": self.dap.send(str(params.get("id", "")), params.get("message"))}

    def debug_stop(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"stopped": self.dap.stop(str(params.get("id", "")))}

    # ------------------------------------------------------------------ language server, formatting
    def lsp_start(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.lsp.root = self.state.root
        return self.lsp.start(self.state.compile_commands(str(params.get("config", "Debug"))))

    def lsp_send(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"sent": self.lsp.send(str(params.get("id", "")), params.get("message"))}

    def lsp_stop(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"stopped": self.lsp.stop(str(params.get("id", "")))}

    def format(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Format C/C++ text with `clang-format` (only when the project has a .clang-format: without one the text is returned unchanged). Unavailable is reported, not faked."""
        text = params.get("text")
        rel = str(params.get("path", "file.cpp"))
        if not isinstance(text, str):
            raise RpcError(INVALID_PARAMS, "text must be a string")
        target = self.state.safe_path(rel)                          # refused first, whether or not clang-format exists
        exe = shutil.which("clang-format")
        if exe is None:
            return {"available": False, "text": text, "reason": "clang-format is not installed"}
        result = process.run([exe, f"--assume-filename={target}", "--style=file", "--fallback-style=none"], input=text, timeout=60,
                             cwd=str(self.state.root))
        if result.returncode != 0:
            return {"available": True, "text": text, "error": result.output[-500:]}
        return {"available": True, "text": result.stdout}

    # ------------------------------------------------------------------ DSL, profile, headers
    def dsl_schema(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return insight.dsl_schema({"Workspace": dsl_api.Workspace, "Target": dsl_api.Target, "Rule": dsl_api.Rule},
                                  {"Kind": Kind, "Language": Language})

    def profile(self, params: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self.state.require()
        db = builder.state_dir(workspace) / "history.db"
        wanted = str(params.get("session", "latest"))
        session = history.find_session(db, wanted)
        rows = history.action_rows(db, session.id) if session is not None else []
        if wanted == "latest" and not rows:
            # The newest session may have found everything up to date (a `run` right after a build): profile the newest one that did work.
            for candidate in history.list_sessions(db, limit=30):
                found = history.action_rows(db, candidate.id)
                if found:
                    session, rows = candidate, found
                    break
        if session is None:
            return {"session": None, "actions": [], "targets": {}, "criticalPath": [], "criticalSeconds": 0.0}
        costs = insight.target_costs(rows)
        dependencies = {n: [d for d in t.dependencies() if d in workspace.targets] for n, t in workspace.targets.items() if n in costs or not t.external}
        chain, seconds = insight.critical_path(dependencies, {n: c["total"] for n, c in costs.items()})
        return {"session": {"id": session.id, "command": session.command, "ok": session.ok, "duration": session.duration, "executed": session.executed,
                            "cached": session.cached, "config": session.config, "toolchain": session.toolchain},
                "actions": sorted(rows, key=lambda r: -(r["duration"] or 0.0))[:int(params.get("limit", 200))],
                "targets": costs, "criticalPath": chain, "criticalSeconds": seconds}

    def headers(self, params: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self.state.require()
        db = builder.state_dir(workspace) / "state.db"
        if not db.exists():
            return {"headers": []}
        database = StateDB(db)
        try:
            costs = header_costs(database.records())
        finally:
            database.close()
        root = str(workspace.root)
        return {"headers": [{"path": c.path[len(root) + 1:] if c.path.startswith(root) else c.path, "includedBy": c.includers,
                             "cost": c.rebuild_seconds} for c in costs[:int(params.get("limit", 30))]]}

    # ------------------------------------------------------------------ Git
    def git_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        git = self._git()
        status = git.status()
        return {"branch": status.branch, "upstream": status.upstream, "ahead": status.ahead, "behind": status.behind,
                "staged": list(status.staged), "modified": list(status.modified), "untracked": list(status.untracked),
                "conflicted": list(status.conflicted)}

    def git_diff(self, params: Dict[str, Any]) -> Dict[str, Any]:
        git = self._git()
        args = ["diff", "--no-color", *(["--cached"] if params.get("staged") else [])]
        if params.get("path"):
            self.state.safe_path(str(params["path"]))              # must be inside the project
            args += ["--", str(params["path"])]
        return {"diff": git.call(args).stdout}

    def git_log(self, params: Dict[str, Any]) -> Dict[str, Any]:
        git = self._git()
        if git.head() is None:
            return {"commits": []}
        commits = git.log("HEAD", limit=int(params.get("limit", 20)))
        return {"commits": [{"sha": c.sha, "short": c.short, "subject": c.subject} for c in commits]}

    def git_stage(self, params: Dict[str, Any]) -> Dict[str, Any]:
        git = self._git()
        paths = [str(p) for p in params.get("paths", [])]
        for p in paths:
            self.state.safe_path(p)
        if not paths:
            raise RpcError(INVALID_PARAMS, "paths is required")
        git.call(["restore", "--staged", "--", *paths] if params.get("unstage") else ["add", "--", *paths])
        return {"ok": True}

    def git_apply(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Stage or unstage one hunk: `patch` is a unified diff of that hunk (block-by-block staging)."""
        git = self._git()
        patch = params.get("patch")
        if not isinstance(patch, str) or not patch.strip():
            raise RpcError(INVALID_PARAMS, "patch is required")
        git.call(["apply", "--cached", "--recount", *(["--reverse"] if params.get("unstage") else []), "-"], input=patch if patch.endswith("\n") else patch + "\n")
        return {"ok": True}

    def git_commit(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Commit with the quality gate in front (`charpente commit`): the gate's report comes back with the outcome."""
        message = str(params.get("message", "")).strip()
        if not message:
            raise RpcError(INVALID_PARAMS, "a commit message is required")
        args = ["commit", "-m", message, "--level", str(params.get("level", "rapide"))]
        if params.get("all"):
            args.append("--all")
        if params.get("noVerify"):
            args.append("--no-verify")
        code, output = self.state.run_cli(args)
        return {"ok": code == 0, "output": output}

    # ------------------------------------------------------------------ devices and logs
    def devices(self, params: Dict[str, Any]) -> Dict[str, Any]:
        found: List[Dict[str, str]] = []
        notes: List[str] = []
        try:
            adb = android.adb_path(android.find_sdk())
            result = process.run([adb, "devices"], timeout=30)
            for serial, state in android.parse_devices(result.output):
                found.append({"id": serial, "platform": "android", "state": state, "name": serial})
        except ChError as exc:
            notes.append(exc.message)
        try:
            hdc = harmony.hdc_path()
            result = process.run([hdc, "list", "targets"], timeout=30)
            for serial in harmony.parse_targets(result.output):
                found.append({"id": serial, "platform": "harmonyos", "state": "device", "name": serial})
        except ChError as exc:
            notes.append(exc.message)
        return {"devices": found, "notes": notes}

    def device_logs(self, params: Dict[str, Any]) -> Dict[str, Any]:
        device, platform = str(params.get("id", "")), str(params.get("platform", "android"))
        try:
            if platform == "android":
                argv = [android.adb_path(android.find_sdk()), "-s", device, "logcat", "-v", "time"]
            elif platform == "harmonyos":
                argv = harmony.hilog_argv(harmony.hdc_path(), device)
            else:
                raise RpcError(INVALID_PARAMS, f"no log source for platform {platform!r}")
        except ChError as exc:
            raise RpcError(INVALID_PARAMS, f"[{exc.code}] {exc}", {"code": exc.code}) from exc
        return {"id": self._start_stream("device", argv, label=f"{platform} logs of {device}")}

    def deploy(self, params: Dict[str, Any]) -> Dict[str, Any]:
        target = str(params.get("target", ""))
        if not target:
            raise RpcError(INVALID_PARAMS, "target is required")
        args = ["deploy", "--target", target, "--config", str(params.get("config", "Debug"))]
        if params.get("platform"):
            args += ["--platform", str(params["platform"])]
        if params.get("device"):
            args += ["--device", str(params["device"])]
        code, output = self.state.run_cli(args)
        return {"ok": code == 0, "output": output}

    # ------------------------------------------------------------------ packages
    def _index(self) -> RecipeIndex:
        store = PackageStore()
        return RecipeIndex(store, store.registries(), self.state.root)

    def packages_search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        text = str(params.get("text", "")).lower()
        index = self._index()
        found = []
        for name in index.names():
            if text in name.lower():
                versions = index.versions(name)
                found.append({"name": name, "versions": list(reversed(versions))})
        return {"packages": found[:100]}

    def packages_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        from ..pkg import lock as lock_mod

        workspace = self.state.require()
        lock = lock_mod.load(workspace.root)
        packages = [] if lock is None else [{"name": n, "version": p.version, "requestedBy": list(p.requested_by)}
                                             for n, p in sorted(lock.packages.items())]
        return {"requires": list(workspace.requires), "locked": packages, "installed": lock is not None}

    def _edit_workspace_file(self, edit: Callable[[str], str]) -> Path:
        path = self.state.workspace_path()
        text = path.read_text(encoding="utf-8-sig")
        try:
            new = edit(text)
        except ChError as exc:
            raise RpcError(INVALID_PARAMS, f"[{exc.code}] {exc}", {"code": exc.code}) from exc
        if new != text:
            path.write_text(new, encoding="utf-8", newline="")
        return path

    def packages_add(self, params: Dict[str, Any]) -> Dict[str, Any]:
        spec = str(params.get("spec", "")).strip()
        name = spec.partition("@")[0]
        if not spec or not name or not self._index().versions(name):
            raise RpcError(INVALID_PARAMS, f"no recipe named {name!r} (see charpente pkg search)")
        self._edit_workspace_file(lambda text: dsl_edit.add_workspace_call(text, "requires", spec))
        self.state.load()
        return {"requires": list(self.state.require().requires)}

    def packages_remove(self, params: Dict[str, Any]) -> Dict[str, Any]:
        spec = str(params.get("spec", "")).strip()
        self._edit_workspace_file(lambda text: dsl_edit.remove_requirement(text, spec))
        self.state.load()
        return {"requires": list(self.state.require().requires)}

    def packages_install(self, params: Dict[str, Any]) -> Dict[str, Any]:
        code, output = self.state.run_cli(["pkg", "install"])
        if code == 0:
            self.state.load()                                      # the packages now exist: the notice goes away
        return {"ok": code == 0, "output": output}

    # ------------------------------------------------------------------ options
    def options_set(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Save option values in `.charpente/options.toml` (which every command reads; `--opt` still wins), then reload."""
        workspace = self.state.require()
        values = params.get("values")
        if not isinstance(values, dict) or not values:
            raise RpcError(INVALID_PARAMS, "values must be an object {name: value}")
        saved = dsl_edit.load_saved_options(self.state.root)
        for name, raw in values.items():
            spec = workspace.options.get(name)
            if spec is None:
                raise RpcError(INVALID_PARAMS, f"unknown option {name!r} (known: {', '.join(sorted(workspace.options)) or 'none'})")
            text = ("true" if raw else "false") if isinstance(raw, bool) else str(raw)
            try:
                dsl_api.parse_option_value(spec, text)             # refuses a value the option does not accept
            except ChError as exc:
                raise RpcError(INVALID_PARAMS, f"[{exc.code}] {exc}", {"code": exc.code}) from exc
            saved[name] = text
        dsl_edit.save_options(self.state.root, saved)
        self.state.load()
        return self.state.info()

    # ------------------------------------------------------------------ terminal
    def terminal_run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run a program in the project's environment (toolchain on PATH, CC/CXX/AR) and stream its output. `argv` is a list: no shell."""
        argv = params.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise RpcError(INVALID_PARAMS, "argv must be a non-empty list of strings")
        from ..commands._common import toolchain_for

        try:
            import argparse

            _, toolchain = toolchain_for(argparse.Namespace(platform=params.get("platform"), toolchain=None), self.state.require())
        except ChError as exc:
            raise RpcError(INVALID_PARAMS, f"[{exc.code}] {exc}", {"code": exc.code}) from exc
        env = dict(os.environ)
        env.update(shellenv.overrides(toolchain, os.environ, root=self.state.root, platform_name=toolchain.target))
        program = shutil.which(argv[0], path=env.get("PATH") or env.get("Path"))
        if program is None:
            raise RpcError(INVALID_PARAMS, f"{argv[0]!r} was not found on the project's PATH")
        return {"id": self._start_stream("terminal", [program, *argv[1:]], cwd=str(self.state.root), env=env, label=" ".join(argv))}


def register(d: Dispatcher, state: ServerState, notify: Notify) -> StudioApi:
    api = StudioApi(state, notify)

    def method(name: str, fn: Callable[[Dict[str, Any]], Any]) -> None:
        def call(params: Any) -> Any:
            if params is not None and not isinstance(params, dict):
                raise RpcError(INVALID_PARAMS, "params must be an object")
            return fn(params or {})
        d.add_method(name, call)

    method("charpente/files/list", api.files_list)
    method("charpente/files/read", api.files_read)
    method("charpente/files/write", api.files_write)
    method("charpente/files/create", api.files_create)
    method("charpente/dsl/schema", api.dsl_schema)
    method("charpente/lsp/start", api.lsp_start)
    method("charpente/lsp/send", api.lsp_send)
    method("charpente/lsp/stop", api.lsp_stop)
    method("charpente/format", api.format)
    method("charpente/debug/available", api.debug_available)
    method("charpente/debug/start", api.debug_start)
    method("charpente/debug/send", api.debug_send)
    method("charpente/debug/stop", api.debug_stop)
    method("charpente/profile", api.profile)
    method("charpente/headers", api.headers)
    method("charpente/git/status", api.git_status)
    method("charpente/git/diff", api.git_diff)
    method("charpente/git/log", api.git_log)
    method("charpente/git/stage", api.git_stage)
    method("charpente/git/apply", api.git_apply)
    method("charpente/git/commit", api.git_commit)
    method("charpente/devices", api.devices)
    method("charpente/devices/logs", api.device_logs)
    method("charpente/deploy", api.deploy)
    method("charpente/packages/search", api.packages_search)
    method("charpente/packages/list", api.packages_list)
    method("charpente/packages/add", api.packages_add)
    method("charpente/packages/remove", api.packages_remove)
    method("charpente/packages/install", api.packages_install)
    method("charpente/options/set", api.options_set)
    method("charpente/terminal/run", api.terminal_run)
    method("charpente/stream/stop", api.stop_stream)
    d.on_close(api.close)
    return api
