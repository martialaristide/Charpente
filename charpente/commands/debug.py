"""`charpente debug` (build, then debug interactively) and `charpente debug-adapter` (DAP over stdio, for editors and Studio)."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

from .. import debug as debug_mod
from ..core import process
from ..dsl.model import Kind
from ..serve.rpc import RpcError
from ..serve.state import ServerState
from ._common import CommandError, find_root


def _builder(state: ServerState, root: Path) -> "tuple[Callable[[str, str], Path], Callable[[], List[str]]]":
    def names() -> List[str]:
        return sorted(n for n, t in state.own_targets().items() if t.kind in (Kind.EXECUTABLE, Kind.TEST))

    def build(target: str, config: str) -> Path:
        try:
            state.load()
            if target not in state.own_targets():
                raise debug_mod.LaunchRefused(f"unknown target {target!r} (known: {', '.join(names()) or 'none'})")
            ok, results, diagnostics = state.compile([target], config=config)
        except RpcError as exc:
            raise debug_mod.LaunchRefused(exc.message) from exc
        if not ok:
            problems = "\n".join(f"[{r['target']}] {r['error']}" for r in results if not r["ok"] and r["error"])
            raise debug_mod.LaunchRefused("the build failed, so there is nothing to debug:\n" + (problems or "\n".join(d.get("message", "") for d in diagnostics)))
        output = next((r["output"] for r in results if r["target"] == target and r["output"]), None)
        if not output:
            raise debug_mod.LaunchRefused(f"{target} produced no program to debug")
        return Path(output)

    return build, names


def execute_adapter(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente debug-adapter", description="Debug Adapter Protocol over stdio: builds the target, then drives gdb or lldb-dap.")
    parser.add_argument("--root", help="Project folder (default: found from the current folder)")
    parser.add_argument("--file", help="The .charpente file")
    parser.add_argument("--debugger", choices=["gdb", "lldb-dap"], help="Which debugger to drive (default: lldb-dap if installed, else gdb 14+)")
    parsed = parser.parse_args(args)
    debugger = debug_mod.choose_debugger(parsed.debugger)
    root = Path(parsed.root).resolve() if parsed.root else find_root()
    state = ServerState(root, parsed.file)
    build, names = _builder(state, root)

    def prepare(arguments: Dict[str, Any], say: Callable[[str], None]) -> Dict[str, Any]:
        return debug_mod.program_launch(state.root if state.workspace else root, arguments, say, build, names)

    proxy = debug_mod.DapProxy(debugger["argv"], sys.stdin.buffer, sys.stdout.buffer, prepare, cwd=str(root))
    return proxy.run()


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente debug", description="Build a target and debug it in gdb or lldb.")
    parser.add_argument("target", nargs="?", help="Target to debug (default: the only program of the workspace)")
    parser.add_argument("--file", help="The .charpente file")
    parser.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    parser.add_argument("--list", action="store_true", help="List the debuggers found (the DAP ones Studio and editors use) and exit")
    parser.add_argument("program_args", nargs=argparse.REMAINDER, help="Arguments for the program, after --")
    parsed = parser.parse_args(args)
    if parsed.list:
        found = debug_mod.find_debuggers()
        for item in found:
            print(f"  {item['name']:<10} {item['version']:<8} {' '.join(item['argv'])}")
        if not found:
            print("No debugger with a DAP mode found (needs gdb 14+ or lldb-dap).")
        return 0 if found else 1
    root = find_root()
    state = ServerState(root, parsed.file)
    build, names = _builder(state, root)
    try:
        candidates = names()
        target = parsed.target or (candidates[0] if len(candidates) == 1 else None)
        if target is None:
            raise CommandError("CH1009", workspace=state.require().name, count=len(candidates), known=", ".join(candidates))
        print(f"Building {target} ({parsed.config})...")
        program = build(target, parsed.config)
    except debug_mod.LaunchRefused as exc:
        print(f"charpente: {exc}", file=sys.stderr)
        return 1
    program_args = parsed.program_args[1:] if parsed.program_args[:1] == ["--"] else parsed.program_args
    gdb, lldb = shutil.which("gdb"), shutil.which("lldb")
    if gdb:
        argv = [gdb, "--args", str(program), *program_args]
    elif lldb:
        argv = [lldb, "--", str(program), *program_args]
    else:
        raise CommandError("CH8023", wanted="gdb or lldb")
    return process.run(argv, capture=False).returncode
