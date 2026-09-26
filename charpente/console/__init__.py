"""The console interface shown by `charpente` alone in a terminal (see app.py)."""
from __future__ import annotations

import os
import sys


def wanted(argv_empty: bool, env: "dict[str, str] | None" = None) -> bool:
    """Whether a bare `charpente` should open the menu: only on a real terminal, and not when CHARPENTE_CONSOLE=off."""
    env = dict(os.environ) if env is None else env
    if not argv_empty or env.get("CHARPENTE_CONSOLE", "").strip().lower() == "off":
        return False
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def run() -> int:
    from .app import real_console

    return real_console().run()
