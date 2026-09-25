"""Compiler discovery. One function per host OS, all built on the same
primitive (shutil.which), so detection is trivially mockable in tests
without touching a real machine's PATH."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Callable, List, Optional

from .dsl.model import OS
from .errors import ChError


@dataclass(frozen=True)
class Toolchain:
    name: str          # e.g. "msvc", "clang-cl", "mingw", "gcc", "clang", "apple-clang"
    c_compiler: str
    cxx_compiler: str
    archiver: str
    linker: str         # usually == cxx_compiler; kept distinct for clarity at call sites


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
    candidates = detect(target_os, which)
    if not candidates:
        raise NoToolchainFoundError("CH2001", os=target_os.value)
    return candidates[0]
