import pytest

from charpente import toolchains
from charpente.dsl.model import OS


def _fake_which(available: dict):
    return lambda cmd: available.get(cmd)


# =============================================================================
#  Windows
# =============================================================================
def test_windows_prefers_msvc_when_multiple_are_present():
    which = _fake_which({"cl": "C:/VS/cl.exe", "gcc": "C:/mingw/gcc.exe", "g++": "C:/mingw/g++.exe"})
    tc = toolchains.pick_default(OS.WINDOWS, which)
    assert tc.name == "msvc"


def test_windows_falls_back_to_mingw_without_msvc():
    which = _fake_which({"gcc": "C:/mingw/gcc.exe", "g++": "C:/mingw/g++.exe"})
    tc = toolchains.pick_default(OS.WINDOWS, which)
    assert tc.name == "mingw"


def test_windows_mingw_requires_both_gcc_and_gxx():
    which = _fake_which({"gcc": "C:/mingw/gcc.exe"})  # g++ missing
    found = toolchains.detect_windows(which)
    assert found == []


def test_windows_none_found_raises_actionable_error():
    which = _fake_which({})
    with pytest.raises(toolchains.NoToolchainFoundError, match="windows"):
        toolchains.pick_default(OS.WINDOWS, which)


# =============================================================================
#  Linux / macOS
# =============================================================================
def test_linux_prefers_gcc_over_clang():
    which = _fake_which({
        "gcc": "/usr/bin/gcc", "g++": "/usr/bin/g++",
        "clang": "/usr/bin/clang", "clang++": "/usr/bin/clang++",
    })
    tc = toolchains.pick_default(OS.LINUX, which)
    assert tc.name == "gcc"


def test_linux_falls_back_to_clang():
    which = _fake_which({"clang": "/usr/bin/clang", "clang++": "/usr/bin/clang++"})
    tc = toolchains.pick_default(OS.LINUX, which)
    assert tc.name == "clang"


def test_macos_detects_apple_clang():
    which = _fake_which({"clang": "/usr/bin/clang", "clang++": "/usr/bin/clang++"})
    tc = toolchains.pick_default(OS.MACOS, which)
    assert tc.name == "apple-clang"


def test_macos_none_found_raises():
    with pytest.raises(toolchains.NoToolchainFoundError):
        toolchains.pick_default(OS.MACOS, _fake_which({}))


def test_archiver_falls_back_when_preferred_tool_missing():
    which = _fake_which({"clang": "/usr/bin/clang", "clang++": "/usr/bin/clang++", "ar": "/usr/bin/ar"})
    tc = toolchains.pick_default(OS.LINUX, which)
    assert tc.name == "clang"
    assert tc.archiver == "/usr/bin/ar"  # llvm-ar absent, falls back to ar
