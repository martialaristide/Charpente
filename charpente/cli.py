"""`charpente <command> [args...]` -- top-level dispatch. Kept intentionally
thin: argument parsing for each command lives in that command's own module
(commands/*.py), not here."""
from __future__ import annotations

import os
import sys
from typing import List, Optional

from ._version import __version__
from .commands import COMMANDS
from .errors import ChError


def _module_commands() -> "dict[str, str]":
    """Commands contributed by enabled modules (never fatal: a broken module is skipped)."""
    try:
        from .modules.runtime import get_registry

        return {e.name: str(getattr(e.obj, "help", "")) for e in get_registry().all("command")}
    except Exception:
        return {}


def _print_help() -> None:
    print("charpente -- a cross-platform C/C++ build system\n")
    print("Usage: charpente <command> [options]\n")
    print("Commands:")
    for name in COMMANDS:
        print(f"  {name}")
    extra = _module_commands()
    if extra:
        print("Commands from modules:")
        for name, help_text in sorted(extra.items()):
            print(f"  {name}" + (f"  -- {help_text}" if help_text else ""))
    print("\nRun `charpente <command> --help` for command-specific options.")


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    if not argv or argv[0] in ("-h", "--help"):
        _print_help()
        return 0 if argv else 1

    if argv[0] in ("-v", "--version"):
        print(f"charpente {__version__}")
        return 0

    command_name, rest = argv[0], argv[1:]
    command = COMMANDS.get(command_name)
    if command is None:
        try:
            from .modules.runtime import get_registry

            extension = get_registry().get("command", command_name)
        except Exception:  # a broken module must never make `charpente` unusable
            extension = None
        if extension is not None:
            command = extension.obj
    if command is None:
        print(f"charpente: unknown command {command_name!r}\n", file=sys.stderr)
        _print_help()
        return 1

    try:
        return command(rest)
    except ChError as e:
        print(f"charpente: {e.format()}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ncharpente: interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # a bug: report it in Charpente's own format; keep the traceback on request
        if os.environ.get("CHARPENTE_DEBUG") == "1":
            raise
        internal = ChError("CH9002", detail=f"{type(exc).__name__}: {exc}")
        print(f"charpente: {internal.format()}\n  (set CHARPENTE_DEBUG=1 to see the full traceback)",
              file=sys.stderr)
        return 70


if __name__ == "__main__":
    sys.exit(main())
