"""`charpente toolchain` -- list the compilers Charpente can see, install cross toolchains, remove them."""
from __future__ import annotations

import argparse
import shutil
import sys
from typing import Callable, List, Optional

from .. import toolchain_install
from ..core.toolid import ToolIdentities
from ..flags import family
from ..modules.runtime import get_registry
from ..platform import host_os


def _list() -> int:
    target_os = host_os()
    registry = get_registry()
    tools = ToolIdentities()
    found = 0
    first = True
    for extension in registry.all("toolchain"):
        for toolchain in extension.obj.detect(target_os, shutil.which):
            found += 1
            identity = tools.identify(toolchain.cxx_compiler, family(toolchain))
            marker = "*" if first else " "
            first = False
            print(f"{marker} {toolchain.name:<12} {toolchain.cxx_compiler}")
            print(f"    version: {identity.version or 'unknown'}   provided by: {extension.module}")
            if toolchain.targets:
                print(f"    can also build for: {', '.join(toolchain.targets)}")
    if not found:
        print(f"No C/C++ toolchain found for {target_os.value}. Run `charpente doctor` for what to install.")
        return 1
    print("\n* = the default (first in preference order)")
    installed = toolchain_install.installed()
    if installed:
        print("\nInstalled by Charpente:")
        for name, version, directory in installed:
            print(f"  {name}@{version}   {directory}")
    return 0


def _progress() -> Optional[Callable[[int, Optional[int]], None]]:
    if not sys.stderr.isatty():
        return None
    state = {"last": -1}

    def show(done: int, total: Optional[int]) -> None:
        if not total:
            return
        percent = done * 100 // total
        if percent != state["last"] and percent % 5 == 0:
            state["last"] = percent
            print(f"\r  downloading... {percent}%", end="", file=sys.stderr, flush=True)
    return show


def _install(spec: str) -> int:
    name, _, version = spec.partition("@")
    if name == "emsdk":
        directory = toolchain_install.install_emsdk(version or "latest")
        print(f"Installed in {directory}")
        print("Build for the web with `charpente build --platform wasm32-emscripten`.")
        return 0
    if name != "zig":
        from ..errors import ChError

        raise ChError("CH8005", name=spec, detail="only `zig` and `emsdk` can be installed for now "
                                                  "(Android NDK and wasmtime are planned)")
    print(f"Installing zig{'@' + version if version else ' (latest release)'} ...")
    directory = toolchain_install.install_zig(version or None, progress=_progress())
    print(f"Installed in {directory}")
    print("Build for another platform with `charpente build --platform linux-arm64` "
          "(`charpente platforms` lists them).")
    return 0


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente toolchain", description="Inspect and install toolchains.")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="List detected toolchains")
    install = sub.add_parser("install", help="Download a toolchain into ~/.charpente/toolchains (zig, emsdk)")
    install.add_argument("spec", help="NAME or NAME@VERSION, e.g. zig or zig@0.16.0")
    remove = sub.add_parser("remove", help="Delete a toolchain installed by Charpente")
    remove.add_argument("spec", help="NAME or NAME@VERSION")
    parsed = parser.parse_args(args)

    if parsed.action == "install":
        return _install(parsed.spec)
    if parsed.action == "remove":
        directory = toolchain_install.remove(parsed.spec)
        print(f"Removed {directory}")
        return 0
    return _list()
