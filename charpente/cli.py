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


def _peek_output_mode(args: List[str]) -> str:
    """The `--output` value a command was given (`auto` when it was not): enough to know whether a person or a program reads the output."""
    for index, arg in enumerate(args):
        if arg == "--output" and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith("--output="):
            return arg.split("=", 1)[1]
    return "auto"


def _banner(command_name: str, args: List[str]) -> None:
    """The banner, once, for the interactive commands on a real terminal (see charpente/ui/banner.py). Never raises."""
    try:
        if command_name == "menu" or "-h" in args or "--help" in args or "--json" in args:
            return                                          # the menu draws its own; help and JSON are read by programs
        from .ui import banner
        from .ui.term import detect

        caps = detect()
        if banner.should_show_banner(command_name, caps, mode=_peek_output_mode(args)):
            banner.print_banner(caps=caps)
    except Exception:                                       # a picture must never stop a command
        pass


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    if not argv:
        from . import console

        if console.wanted(True):                         # a person at a terminal gets the guided menu; scripts and pipes keep the plain help
            try:
                return console.run()
            except ChError as e:
                print(f"charpente: {e.format()}", file=sys.stderr)
                return 1
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

    _banner(command_name, rest)
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
