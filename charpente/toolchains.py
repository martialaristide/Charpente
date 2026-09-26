"""Compiler discovery. One function per host OS, all built on the same
primitive (shutil.which), so detection is trivially mockable in tests
without touching a real machine's PATH."""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .dsl.model import OS
from .errors import ChError


@dataclass(frozen=True)
class Toolchain:
    name: str          # e.g. "msvc", "clang-cl", "mingw", "gcc", "clang", "apple-clang"
    c_compiler: str
    cxx_compiler: str
    archiver: str
    linker: str         # usually == cxx_compiler; kept distinct for clarity at call sites
    # Arguments that follow the executable, for drivers that need them: `zig cc -target X`,
    # `zig ar`. Empty for ordinary compilers.
    c_args: Tuple[str, ...] = ()
    cxx_args: Tuple[str, ...] = ()
    ar_args: Tuple[str, ...] = ()
    ld_args: Tuple[str, ...] = ()
    #: Platform names this toolchain can build for, beyond the host's own (empty = host only).
    targets: Tuple[str, ...] = ()
    #: The platform a specialised copy was made for ("" = not specialised: builds for the host).
    target: str = ""
    #: Environment variables every action of this toolchain runs with (name, value); part of the action key.
    env: Tuple[Tuple[str, str], ...] = ()
    #: True for toolchains that only produce code for other platforms (emscripten): never the native default.
    cross_only: bool = False
    #: Facts about the installation other modules need (name, value), e.g. the NDK's root directory.
    extras: Tuple[Tuple[str, str], ...] = ()


WhichFn = Callable[[str], Optional[str]]


def _which(which: WhichFn, *candidates: str) -> Optional[str]:
    for c in candidates:
        found = which(c)
        if found:
            return found
    return None


def detect_windows(which: WhichFn = shutil.which) -> List[Toolchain]:
    found: List[Toolchain] = []

    cl = which("cl")
    if cl:
        found.append(Toolchain(name="msvc", c_compiler=cl, cxx_compiler=cl,
                                archiver=_which(which, "lib") or "lib", linker=cl))

    clang_cl = which("clang-cl")
    if clang_cl:
        found.append(Toolchain(name="clang-cl", c_compiler=clang_cl, cxx_compiler=clang_cl,
                                archiver=_which(which, "llvm-lib", "lib") or "llvm-lib",
                                linker=clang_cl))

    gcc = which("gcc")
    gxx = which("g++")
    if gcc and gxx:
        found.append(Toolchain(name="mingw", c_compiler=gcc, cxx_compiler=gxx,
                                archiver=_which(which, "ar") or "ar", linker=gxx))

    return found


def detect_linux(which: WhichFn = shutil.which) -> List[Toolchain]:
    found: List[Toolchain] = []

    gcc = which("gcc")
    gxx = which("g++")
    if gcc and gxx:
        found.append(Toolchain(name="gcc", c_compiler=gcc, cxx_compiler=gxx,
                                archiver=_which(which, "ar") or "ar", linker=gxx))

    clang = which("clang")
    clangxx = which("clang++")
    if clang and clangxx:
        found.append(Toolchain(name="clang", c_compiler=clang, cxx_compiler=clangxx,
                                archiver=_which(which, "llvm-ar", "ar") or "ar", linker=clangxx))

    return found


def detect_macos(which: WhichFn = shutil.which) -> List[Toolchain]:
    found: List[Toolchain] = []
    clang = which("clang")
    clangxx = which("clang++")
    if clang and clangxx:
        found.append(Toolchain(name="apple-clang", c_compiler=clang, cxx_compiler=clangxx,
                                archiver=_which(which, "ar") or "ar", linker=clangxx))
    return found


_ZIG_PLATFORMS = ("windows-x64", "windows-arm64", "linux-x64", "linux-arm64", "linux-riscv64",
                  "macos-x64", "macos-arm64", "wasm32-wasi", "freebsd-x64", "netbsd-x64")


def toolchains_dir() -> Path:
    """Where `charpente toolchain install` puts the toolchains it downloaded."""
    from .dsl.trust import config_dir

    return config_dir() / "toolchains"


def _version_key(text: str) -> Tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text)[:4])


def installed_zigs() -> List[Path]:
    """Zig copies installed by Charpente, newest version first."""
    exe = "zig.exe" if os.name == "nt" else "zig"
    found = [d / exe for d in toolchains_dir().glob("zig-*") if (d / exe).is_file()]
    return sorted(found, key=lambda p: _version_key(p.parent.name[4:]), reverse=True)


def detect_zig(which: WhichFn = shutil.which) -> List[Toolchain]:
    """Zig as a C/C++ cross compiler: `zig cc` is clang with every libc bundled, so one
    binary builds for many platforms. Found on PATH or in Charpente's toolchain directory."""
    zig = which("zig")
    if not zig and which is shutil.which:            # an injected `which` (tests) keeps detection hermetic
        installed = installed_zigs()
        zig = str(installed[0]) if installed else None
    if not zig:
        return []
    return [Toolchain(name="zig", c_compiler=zig, cxx_compiler=zig, archiver=zig, linker=zig,
                      c_args=("cc",), cxx_args=("c++",), ar_args=("ar",), ld_args=("c++",),
                      targets=_ZIG_PLATFORMS)]


def _emscripten_from(root: Path) -> Optional[Toolchain]:
    """An emsdk directory (as `emsdk install/activate` leaves it) as a toolchain."""
    tools = root / "upstream" / "emscripten"

    def launcher(name: str) -> Path:
        # Windows emsdk ships `.exe` launchers (recent) or `.bat` scripts (older); elsewhere plain scripts.
        for suffix in ((".exe", ".bat") if os.name == "nt" else ("",)):
            if (tools / f"{name}{suffix}").is_file():
                return tools / f"{name}{suffix}"
        return tools / name

    emcc, empp, emar = launcher("emcc"), launcher("em++"), launcher("emar")
    if not (emcc.is_file() and empp.is_file() and emar.is_file()):
        return None
    env = [("EMSDK", str(root))]
    config = root / ".emscripten"
    if config.is_file():
        env.append(("EM_CONFIG", str(config)))
    python = sorted(root.glob("python/*/python.exe" if os.name == "nt" else "python/*/bin/python3"))
    if python:
        env.append(("EMSDK_PYTHON", str(python[-1])))
    return Toolchain(name="emscripten", c_compiler=str(emcc), cxx_compiler=str(empp), archiver=str(emar),
                     linker=str(empp), targets=("wasm32-emscripten",), env=tuple(env), cross_only=True)


def detect_emscripten(which: WhichFn = shutil.which) -> List[Toolchain]:
    """Emscripten (C/C++ to WebAssembly for browsers and Node): on PATH (an activated emsdk), or an emsdk
    that `charpente toolchain install emsdk` put in Charpente's toolchain directory."""
    emcc, empp, emar = which("emcc"), which("em++"), which("emar")
    if emcc and empp and emar:
        return [Toolchain(name="emscripten", c_compiler=emcc, cxx_compiler=empp, archiver=emar, linker=empp,
                          targets=("wasm32-emscripten",), cross_only=True)]
    if which is shutil.which:                        # an injected `which` (tests) keeps detection hermetic
        for root in sorted(toolchains_dir().glob("emsdk-*"), reverse=True):
            found = _emscripten_from(root)
            if found is not None:
                return [found]
    return []


def detect_ndk(which: WhichFn = shutil.which) -> List[Toolchain]:
    """The Android NDK's clang, from `ANDROID_NDK_HOME`, an SDK (`ANDROID_HOME`, Android Studio's default
    folder) or `charpente toolchain install ndk`. An injected `which` (tests) keeps detection hermetic."""
    if which is not shutil.which:
        return []
    from . import android

    sdk = android.find_sdk()
    if sdk is None or sdk.ndk is None:
        return []
    toolchain = android.ndk_toolchain(sdk.ndk)
    return [toolchain] if Path(toolchain.cxx_compiler).is_file() else []


_DETECTORS = {
    OS.WINDOWS: detect_windows,
    OS.LINUX: detect_linux,
    OS.MACOS: detect_macos,
}


def detect(target_os: OS, which: WhichFn = shutil.which) -> List[Toolchain]:
    """Every toolchain found, in preference order: Charpente's own providers
    first (the v0.1.0 order), then those contributed by modules. All of them
    are `toolchain` extensions registered through the module registry."""
    from .modules.runtime import get_registry

    found: List[Toolchain] = []
    seen = set()
    for extension in get_registry().all("toolchain"):
        for toolchain in extension.obj.detect(target_os, which):
            if toolchain.name not in seen:
                seen.add(toolchain.name)
                found.append(toolchain)
    return found


class NoToolchainFoundError(ChError):
    pass


def pick_default(target_os: OS, which: WhichFn = shutil.which) -> Toolchain:
    """The first toolchain detect() finds, in the order each detector
    lists them (a deliberate preference order, not just "whatever's
    first"). Raises a clear, actionable error if none are installed."""
    candidates = [c for c in detect(target_os, which) if not c.cross_only]
    if not candidates:
        raise NoToolchainFoundError("CH2001", os=target_os.value)
    return candidates[0]
