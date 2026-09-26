"""The environment of a project shell: the chosen toolchain's directories on PATH, and CC/CXX/AR pointing at it.

`charpente shell` gives a terminal where `cc`-style tools and other build systems (`make`, `cmake`, a Python `setup.py`)
see the same compiler Charpente builds with -- including a cross toolchain (`--platform wasm32-wasi`) or one Charpente
installed for you that is not on the machine's PATH. Everything here is a pure function of its inputs.
"""
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from .core import process
from .toolchains import Toolchain

FORMATS = ("sh", "powershell", "cmd", "json")


def _command(executable: str, args: Sequence[str], windows: bool) -> str:
    argv = [executable, *args]
    return process.windows_command_line(argv) if windows else shlex.join(argv)


def tool_dirs(toolchain: Toolchain) -> List[str]:
    """The folders that hold the toolchain's programs, in order, without duplicates (only programs given by full path)."""
    seen: List[str] = []
    for tool in (toolchain.cxx_compiler, toolchain.c_compiler, toolchain.archiver, toolchain.linker):
        if os.path.isabs(tool):
            folder = str(Path(tool).parent)
            if folder not in seen:
                seen.append(folder)
    return seen


def _path_key(base: Mapping[str, str]) -> str:
    for key in base:
        if key.upper() == "PATH":
            return key
    return "PATH"


def overrides(toolchain: Toolchain, base: Mapping[str, str], *, root: Path, config: str = "Debug", platform_name: str = "",
              windows: Optional[bool] = None) -> Dict[str, str]:
    """The variables a project shell sets or changes (PATH comes back complete, with the toolchain's folders first)."""
    windows = os.name == "nt" if windows is None else windows
    changes: Dict[str, str] = {}
    key = _path_key(base)
    folders = tool_dirs(toolchain)
    for name, value in toolchain.env:
        if name.upper() == "PATH":                    # a toolchain that extends PATH: its entries come first too
            folders += [p for p in value.split(os.pathsep) if p and p not in folders]
    if folders:
        current = base.get(key, "")
        changes[key] = os.pathsep.join(folders + ([current] if current else []))
    changes["CC"] = _command(toolchain.c_compiler, toolchain.c_args, windows)
    changes["CXX"] = _command(toolchain.cxx_compiler, toolchain.cxx_args, windows)
    changes["AR"] = _command(toolchain.archiver, toolchain.ar_args, windows)
    changes["CHARPENTE_ROOT"] = str(root)
    changes["CHARPENTE_CONFIG"] = config
    changes["CHARPENTE_TOOLCHAIN"] = toolchain.name
    changes["CHARPENTE_PLATFORM"] = platform_name or toolchain.target
    changes["CHARPENTE_SHELL"] = "1"
    for name, value in toolchain.env:
        if name.upper() != "PATH":
            changes[name] = value
    return changes


def render(changes: Mapping[str, str], fmt: str) -> str:
    """The changes as text a shell can evaluate (`sh`, `powershell`, `cmd`) or as JSON."""
    if fmt == "json":
        return json.dumps(dict(changes), indent=2, ensure_ascii=False)
    if fmt == "sh":
        return "\n".join(f"export {k}={shlex.quote(v)}" for k, v in changes.items())
    if fmt == "powershell":
        return "\n".join("$env:%s = '%s'" % (k, v.replace("'", "''")) for k, v in changes.items())
    if fmt == "cmd":
        return "\n".join(f'set "{k}={v}"' for k, v in changes.items())
    raise ValueError(f"unknown format {fmt!r} (use one of {', '.join(FORMATS)})")


def default_format(windows: Optional[bool] = None) -> str:
    return "powershell" if (os.name == "nt" if windows is None else windows) else "sh"


def find_shell(env: Mapping[str, str], which: Optional[Callable[[str], Optional[str]]] = None,
               windows: Optional[bool] = None) -> List[str]:
    """The argv of an interactive shell for this machine, or an empty list when none can be found."""
    import shutil

    which = which or (lambda name: shutil.which(name, path=env.get(_path_key(env))))
    windows = os.name == "nt" if windows is None else windows
    if windows:
        for name in ("pwsh", "powershell"):
            found = which(name)
            if found:
                return [found, "-NoLogo"]
        comspec = env.get("COMSPEC") or which("cmd")
        return [comspec] if comspec else []
    configured = env.get("SHELL")
    if configured and which(configured):
        return [configured]
    found = which("bash") or which("sh")
    return [found] if found else []
