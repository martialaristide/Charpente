"""Host OS detection. Kept to one tiny function so every other module can
depend on it without pulling in anything heavier."""
from __future__ import annotations

import platform as _platform

from .dsl.model import OS


def host_os() -> OS:
    system = _platform.system()
    if system == "Windows":
        return OS.WINDOWS
    if system == "Darwin":
        return OS.MACOS
    if system == "Linux":
        return OS.LINUX
    raise RuntimeError(f"Unsupported host OS: {system!r}")
