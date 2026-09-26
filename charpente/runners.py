"""How to execute a program built for a platform, from this machine.

A native binary runs as is. A binary for the same OS on a compatible CPU
(x64 on an arm64 Windows/macOS machine, which emulate it) runs as is. WebAssembly
needs a runtime: `wasmtime` if present, else Node's built-in WASI support.
Anything else (an Android or iOS binary, another OS) cannot run here and says so
(CH8004) instead of failing obscurely -- deploy it with the platform's own tooling.
"""
from __future__ import annotations

import shutil
from typing import Callable, List, Optional

from . import platforms
from .errors import ChError

WhichFn = Callable[[str], Optional[str]]

# Node's WASI: `node -e CODE program.wasm args...` leaves argv = [node, program.wasm, args...].
_NODE_WASI = (
    "const {WASI}=require('node:wasi');const fs=require('fs');"
    "const wasi=new WASI({version:'preview1',args:process.argv.slice(1),env:process.env,preopens:{'.':'.'}});"
    "WebAssembly.compile(fs.readFileSync(process.argv[1]))"
    ".then(m=>WebAssembly.instantiate(m,wasi.getImportObject()))"
    ".then(i=>{const c=wasi.start(i);process.exitCode=typeof c==='number'?c:0;})"
    ".catch(e=>{console.error(String(e));process.exitCode=1;});"
)


def runs_natively(target: platforms.Platform, host: platforms.Platform) -> bool:
    if target.name == host.name:
        return True
    if target.os != host.os:
        return False
    # Windows and macOS on arm64 execute x64 programs through emulation.
    return host.arch == "arm64" and target.arch == "x64" and host.os in ("windows", "macos")


def command(output: str, target_name: str, host: platforms.Platform, *, which: WhichFn = shutil.which,
            program_args: Optional[List[str]] = None) -> List[str]:
    """The argv that runs `output` (built for `target_name`)."""
    args = list(program_args or [])
    target = platforms.get(target_name)
    if runs_natively(target, host):
        return [output, *args]
    if target.os == "wasi":
        wasmtime = which("wasmtime")
        if wasmtime:
            return [wasmtime, "run", "--dir=.", output, *args]
        node = which("node")
        if node:
            return [node, "--no-warnings", "-e", _NODE_WASI, output, *args]
    if target.os == "wasm":
        node = which("node")
        if node:
            return [node, output, *args]
    raise ChError("CH8004", artifact=output, platform=target.name)
