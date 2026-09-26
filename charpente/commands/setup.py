"""`charpente setup` -- a guided first run: checks the machine and offers to fix what is missing."""
from __future__ import annotations

import argparse
import sys
from typing import Callable, List, Optional

from .. import onboarding, settings
from . import doctor


def _interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def execute(args: List[str], *, ask: Optional[Callable[[str], str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="charpente setup", description="Guided first run: check this machine and offer to fix what is missing.")
    parser.add_argument("--yes", action="store_true", help="Accept every offer that only downloads open tools (never a vendor licence)")
    parser.add_argument("--lang", choices=list(settings.KEYS["lang"]), help="Remember this language for messages (CHARPENTE_LANG still overrides it)")
    parsed = parser.parse_args(args)
    interactive = ask is not None or _interactive()
    question = ask or input

    if parsed.lang:
        settings.set_value("lang", parsed.lang)
        print(f"Language remembered: {parsed.lang}")

    report = doctor.gather()
    print(f"Charpente {report['charpente']}, host {report['host']}, "
          f"{len(report['toolchains'])} compiler(s), can build {len(report['buildable'])} platform(s) now.")
    todo = onboarding.steps(report, lang_chosen=settings.get("lang"))
    if not todo:
        print("Everything Charpente looks for is here. Try `charpente init hello --template console-cpp && cd hello && charpente run`.")
        return 0

    from ..cli import main as run_charpente

    unresolved = 0
    for step in todo:
        print()
        for line in onboarding.describe(step):
            print(line)
        if step.options:
            if not interactive:
                print(f"    (run `charpente setup --lang {step.options[0]}` or `--lang {step.options[1]}` to choose)")
                continue
            choice = question(f"    choose [{'/'.join(step.options)}, Enter to skip]: ").strip().lower()
            if choice in step.options:
                settings.set_value("lang", choice)
                print(f"    remembered: {choice}")
            continue
        if step.command is None:
            unresolved += 1
            continue
        go = parsed.yes or (interactive and question("    do it now? [y/N] ").strip().lower() in ("y", "yes"))
        if not go:
            print("    skipped (not done).")
            unresolved += 1
            continue
        code = run_charpente(step.command)
        if code != 0:
            print(f"    that did not work (exit code {code}); nothing else was changed.", file=sys.stderr)
            unresolved += 1
    print()
    print("Run `charpente doctor` to see the result." if unresolved else "Done. Run `charpente doctor` to see the result.")
    return 0
