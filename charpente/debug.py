"""Debugging with the Debug Adapter Protocol (DAP): a thin adapter in front of gdb or lldb-dap that knows how to build the target first.

The debuggers speak DAP themselves (`gdb --interpreter=dap` since GDB 14, `lldb-dap` from LLVM), so nothing is re-implemented here. The adapter
forwards messages both ways unchanged, except one: a `launch` request naming a Charpente **target** (`{"target": "app", "config": "Debug"}`)
is turned into a launch of that target's freshly built program (`{"program": ".../app.exe", ...}`). A `launch` that already has a `program`
is passed through, so any executable can be debugged. Microsoft's proprietary debug adapter (licensed only for its own products) is not used.
"""
from __future__ import annotations

import re
import shutil
import threading
from pathlib import Path
from typing import IO, Any, Callable, Dict, List, Optional, Sequence

from .core import process
from .errors import ChError
from .serve.rpc import RpcError, encode_message, read_message

EVENT_SEQ_BASE = 1_000_000            # sequence numbers of the messages we send ourselves, far from the debugger's own
MIN_GDB = (14, 0)


class LaunchRefused(Exception):
    """The launch cannot proceed (build failed, unknown target...); the message goes back to the client as the error."""


def _gdb_version(gdb: str, run: Callable[..., process.ProcessResult] = process.run) -> Optional[Sequence[int]]:
    result = run([gdb, "--version"], timeout=30)
    match = re.search(r"(\d+)\.(\d+)", result.stdout.splitlines()[0] if result.stdout else "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def find_debuggers(which: Callable[[str], Optional[str]] = shutil.which,
                   run: Callable[..., process.ProcessResult] = process.run) -> List[Dict[str, Any]]:
    """Every usable debugger, in preference order: [{name, argv, version}]. gdb older than 14 has no DAP mode and is not offered."""
    found: List[Dict[str, Any]] = []
    for name in ("lldb-dap", "lldb-vscode"):
        path = which(name)
        if path:
            found.append({"name": "lldb-dap", "argv": [path], "version": ""})
            break
    gdb = which("gdb")
    if gdb:
        version = _gdb_version(gdb, run)
        if version is not None and tuple(version) >= MIN_GDB:
            found.append({"name": "gdb", "argv": [gdb, "-q", "--interpreter=dap"], "version": ".".join(str(v) for v in version)})
    return found


def choose_debugger(preference: Optional[str] = None, which: Callable[[str], Optional[str]] = shutil.which,
                    run: Callable[..., process.ProcessResult] = process.run) -> Dict[str, Any]:
    debuggers = find_debuggers(which, run)
    if preference:
        debuggers = [d for d in debuggers if d["name"] == preference]
    if not debuggers:
        raise ChError("CH8023", wanted=preference or "gdb (14 or newer) or lldb-dap")
    return debuggers[0]


class DapProxy:
    """Sits between an editor (`client_in`/`client_out`) and a debugger process; see the module docstring."""

    def __init__(self, debugger_argv: Sequence[str], client_in: IO[bytes], client_out: IO[bytes], prepare_launch: Callable[[Dict[str, Any], Callable[[str], None]], Dict[str, Any]],
                 cwd: Optional[str] = None) -> None:
        self._argv = list(debugger_argv)
        self._in, self._out = client_in, client_out
        self._prepare = prepare_launch
        self._cwd = cwd
        self._lock = threading.Lock()
        self._seq = EVENT_SEQ_BASE
        self.done = threading.Event()
        self.exit_code = 0

    # ------------------------------------------------------------------ to the client
    def _to_client(self, data: bytes) -> None:
        with self._lock:
            try:
                self._out.write(data)
                self._out.flush()
            except (OSError, ValueError):
                self.done.set()

    def _send(self, message: Dict[str, Any]) -> None:
        with self._lock:
            self._seq += 1
            message["seq"] = self._seq
        self._to_client(encode_message(message))

    def say(self, text: str, category: str = "console") -> None:
        self._send({"type": "event", "event": "output", "body": {"category": category, "output": text if text.endswith("\n") else text + "\n"}})

    def _refuse(self, request: Dict[str, Any], reason: str) -> None:
        self.say(reason, "stderr")
        self._send({"type": "response", "request_seq": request.get("seq", 0), "success": False, "command": request.get("command", "launch"), "message": reason})
        self._send({"type": "event", "event": "terminated", "body": {}})

    # ------------------------------------------------------------------ the loop
    def run(self) -> int:
        try:
            debugger = process.Duplex(self._argv, self._to_client, self._on_exit, cwd=self._cwd)
        except ChError as exc:
            self.say(f"[{exc.code}] {exc}", "stderr")
            return 1
        try:
            while not self.done.is_set():
                try:
                    message = read_message(self._in)
                except RpcError:
                    continue
                if message is None:
                    break
                if message.get("type") == "request" and message.get("command") in ("launch", "attach") and isinstance(message.get("arguments"), dict):
                    try:
                        message["arguments"] = self._prepare(message["arguments"], self.say)
                    except LaunchRefused as exc:
                        self._refuse(message, str(exc))
                        continue
                if not debugger.write(encode_message(message)):
                    break
            debugger.close_input()                                   # the client is done: let the debugger finish answering, then end it
            self.done.wait(timeout=10)
        finally:
            debugger.stop()
        return self.exit_code

    def _on_exit(self, code: int) -> None:
        self.exit_code = code
        self.done.set()


def program_launch(root: Path, arguments: Dict[str, Any], say: Callable[[str], None],
                   build: Callable[[str, str], Any], names: Callable[[], List[str]]) -> Dict[str, Any]:
    """Turn `{target, config, args, cwd}` into the debugger's launch arguments. `build(target, config)` returns the program path or raises
    LaunchRefused; `names()` lists the runnable targets (to pick the only one, or explain the choice)."""
    if "program" in arguments:
        arguments = dict(arguments)
        arguments.setdefault("cwd", str(root))
        return arguments
    target = arguments.get("target")
    if not target:
        candidates = names()
        if len(candidates) != 1:
            raise LaunchRefused("say which target to debug (launch argument \"target\"): " + (", ".join(candidates) or "this workspace has no program"))
        target = candidates[0]
    config = str(arguments.get("config", "Debug"))
    if arguments.get("platform"):
        raise LaunchRefused(f"debugging {arguments['platform']} from here is not supported: only programs that run on this machine (remote debugging is not implemented)")
    say(f"Building {target} ({config})...")
    program = build(str(target), config)
    launch = {k: v for k, v in arguments.items() if k not in ("target", "config", "platform")}
    launch["program"] = str(program)
    launch.setdefault("args", [])
    launch.setdefault("cwd", str(root))
    say(f"Debugging {program}")
    return launch
