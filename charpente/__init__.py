"""Charpente: a cross-platform C/C++ build system driven by a Python DSL.

`from charpente import *` gives a .charpente file everything it needs:
Workspace, Target, Kind, Language, OS.
"""
from ._version import __author__, __email__, __version__
from .dsl.api import Kind, Language, OS, Target, Workspace, current_workspace

__all__ = [
    "__version__", "__author__", "__email__",
    "Workspace", "Target", "Kind", "Language", "OS", "current_workspace",
]
