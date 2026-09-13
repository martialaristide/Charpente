"""`charpente <command> [args...]` -- top-level dispatch. Kept intentionally
thin: argument parsing for each command lives in that command's own module
(commands/*.py), not here."""
from __future__ import annotations

import sys
from typing import List, Optional

from ._version import __version__
from .commands import COMMANDS


def _print_help() -> None:
    print("charpente -- a cross-platform C/C++ build system\n")
    print("Usage: charpente <command> [options]\n")
    print("Commands:")
    for name in COMMANDS:
        print(f"  {name}")
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
        print(f"charpente: unknown command {command_name!r}\n", file=sys.stderr)
        _print_help()
        return 1

    from .commands._common import CommandError

    try:
        return command(rest)
    except CommandError as e:
        print(f"charpente: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ncharpente: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
