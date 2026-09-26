"""Charpente's own toolchain providers, registered through the same extension
point a third-party module uses (no special path in the core).

The preference order of v0.1.0 is preserved: on Windows MSVC, then clang-cl,
then MinGW; on Linux GCC, then Clang; on macOS Apple Clang.
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional

from .. import toolchains
from ..dsl.model import OS
from .registry import ExtensionRegistry


class BuiltinToolchain:
    """One detector: the toolchain called `name`, when the host OS matches."""

    def __init__(self, name: str, host_os: Optional[OS], detect_fn: Callable[..., List[Any]]) -> None:
        self.name = name
        self._host_os = host_os
        self._detect = detect_fn

    def detect(self, host_os: Any, which: Callable[[str], Optional[str]]) -> List[Any]:
        if self._host_os is not None and host_os != self._host_os:
            return []
        return [t for t in self._detect(which) if t.name == self.name]


def register_builtins(registry: ExtensionRegistry) -> None:
    for name, os_, fn in (
        ("msvc", OS.WINDOWS, toolchains.detect_windows),
        ("clang-cl", OS.WINDOWS, toolchains.detect_windows),
        ("mingw", OS.WINDOWS, toolchains.detect_windows),
        ("gcc", OS.LINUX, toolchains.detect_linux),
        ("clang", OS.LINUX, toolchains.detect_linux),
        ("apple-clang", OS.MACOS, toolchains.detect_macos),
        ("zig", None, toolchains.detect_zig),          # a cross compiler: usable from any host
        ("emscripten", None, toolchains.detect_emscripten),
        ("ndk", None, toolchains.detect_ndk),
    ):
        registry.add_builtin("toolchain", name, BuiltinToolchain(name, os_, fn))
