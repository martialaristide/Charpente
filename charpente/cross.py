"""Choosing a toolchain for a target platform, and turning it into one that
produces code for that platform.

Native builds are unchanged: with no `--platform` the first detected toolchain
is used exactly as before. Asking for another platform selects a toolchain
that *declares* it can target it (`Toolchain.targets`) and specialises it --
for `zig`, that means `zig cc -target aarch64-linux-gnu`. Nothing is guessed:
if nothing installed can build the platform, the error says what to install.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, List, Optional, Tuple

from . import platforms, toolchains
from .dsl.model import OS
from .errors import ChError
from .platform import host_os
from .toolchains import Toolchain

DetectFn = Callable[[OS], List[Toolchain]]

# Which ABI of a platform's triples a given toolchain family means when the user just says "linux-x64".
_ZIG_ABI = {"windows": "gnu", "linux": "gnu"}


def os_of(platform: platforms.Platform) -> OS:
    """The `OS` member for a platform's operating system."""
    return OS(platform.os)


def variant_name(config: str, toolchain: Toolchain) -> str:
    """The build sub-directory: `Debug` natively, `Debug-linux-arm64` when cross-compiling, so
    two platforms never overwrite each other's objects."""
    return f"{config}-{toolchain.target}" if toolchain.target else config


def can_target(toolchain: Toolchain, platform: platforms.Platform) -> bool:
    return platform.name in toolchain.targets


def specialise(toolchain: Toolchain, platform: platforms.Platform, android_api: Optional[int] = None) -> Toolchain:
    """A copy of `toolchain` that builds for `platform`. `android_api` is the minimum Android API level
    (the manifest's minSdkVersion) when the platform is Android."""
    if not can_target(toolchain, platform):
        raise ChError("CH8002", platform=platform.name, hint=_hint(platform))
    if toolchain.name == "ndk":
        from . import android

        return android.specialise_ndk(toolchain, platform.name, android_api or android.DEFAULT_API)
    if toolchain.name == "zig":
        triple = platform.triple(_ZIG_ABI.get(platform.os))
        target = ("-target", triple)
        return replace(toolchain, c_args=("cc", *target), cxx_args=("c++", *target),
                       ar_args=("ar",), ld_args=("c++", *target), target=platform.name)
    # Toolchains whose driver already targets one platform (emscripten, the NDK's clang wrappers, ...)
    return replace(toolchain, target=platform.name)


def _hint(platform: platforms.Platform) -> str:
    if platform.needs:
        return f"{platform.name} needs {platform.needs}."
    return ("Install a cross toolchain: `charpente toolchain install zig` covers Windows, Linux, macOS, "
            "FreeBSD and WASI targets.")


def select(platform_name: Optional[str], toolchain_name: Optional[str], *,
           detect: Optional[DetectFn] = None, android_api: Optional[int] = None) -> Tuple[OS, Toolchain]:
    """(target OS, toolchain) for the requested platform/toolchain (either may be None)."""
    find = detect or toolchains.detect
    here = host_os()
    if not platform_name:
        candidates = [c for c in find(here) if not c.cross_only]
        if toolchain_name:
            return here, _named(candidates, toolchain_name)
        if not candidates:
            raise toolchains.NoToolchainFoundError("CH2001", os=here.value)
        return here, candidates[0]

    wanted = platforms.get(platform_name)
    candidates = find(here)
    if toolchain_name:
        candidates = [_named(candidates, toolchain_name)]
    if wanted.name == platforms.host().name:
        candidates = [c for c in candidates if not c.cross_only]
        if not candidates:
            raise toolchains.NoToolchainFoundError("CH2001", os=here.value)
        return here, candidates[0]
    for candidate in candidates:
        if can_target(candidate, wanted):
            return os_of(wanted), specialise(candidate, wanted, android_api)
    raise ChError("CH8002", platform=wanted.name, hint=_hint(wanted))


def _named(candidates: List[Toolchain], name: str) -> Toolchain:
    for candidate in candidates:
        if candidate.name == name:
            return candidate
    raise ChError("CH8003", name=name, available=", ".join(c.name for c in candidates) or "(none)")
