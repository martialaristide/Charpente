"""`python -m charpente.ui`: the banner and a made-up build session, to judge the look without building anything.

    python -m charpente.ui --theme neon --lang en            the four themes: bois (default), neon, foret, ocean
    python -m charpente.ui --fail                            the session ends with a failing target (the default shows the one in the design)
    python -m charpente.ui --color never | always --ascii    what a limited terminal gets
    python -m charpente.ui --width 60                        what a narrow terminal gets

The session goes through the real renderer, fed with events, exactly as a build does: what you see is what a build prints.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, TextIO, Tuple

from ..events import EventBus
from . import banner
from .render import StyledRenderer
from .term import Caps, detect

Event = Tuple[str, Dict[str, Any]]
TARGETS = ("moteur", "shaders", "app", "tests_moteur")


def session(fail: bool = True) -> List[Event]:
    """The events of a build in the design: one target compiled, one served by the cache, one built with warnings, and a last one that fails at the link (or, with
    `fail=False`, succeeds). When it fails two actions never run, so the bar stops at 38/40."""
    body: List[Event] = []
    for i in range(12):
        body.append(("action.finished", {"action": f"compile:moteur:{i}", "target": "moteur", "kind": "compile", "duration": 0.2, "outputs": [f"obj{i}.o"]}))
    body += [("action.finished", {"action": "archive:moteur", "target": "moteur", "kind": "archive", "duration": 0.1, "outputs": ["build/Debug/moteur/libmoteur.a"]}),
             ("target.finished", {"target": "moteur", "duration": 2.4, "executed": 13, "cached": 0, "up_to_date": 0})]
    for i in range(6):
        body.append(("action.cache_hit", {"action": f"compile:shaders:{i}", "target": "shaders", "kind": "compile"}))
    body.append(("target.up_to_date", {"target": "shaders"}))
    for i in range(14):
        body.append(("action.finished", {"action": f"compile:app:{i}", "target": "app", "kind": "compile", "duration": 0.05, "outputs": [f"a{i}.o"]}))
    body += [("diagnostic.emitted", {"file": "src/app.cpp", "line": 12, "column": 5, "severity": "warning", "message": "unused variable 'x'", "action": "compile:app:3"}),
             ("diagnostic.emitted", {"file": "src/app.cpp", "line": 30, "column": 9, "severity": "warning", "message": "comparison of integers of different signs", "action": "compile:app:7"}),
             ("action.finished", {"action": "link:app", "target": "app", "kind": "link", "duration": 0.3, "outputs": ["build/Debug/app/app"]}),
             ("target.finished", {"target": "app", "duration": 1.1, "executed": 15, "cached": 0, "up_to_date": 0})]
    for i in range(3):
        body.append(("action.cache_hit", {"action": f"compile:tests_moteur:{i}", "target": "tests_moteur", "kind": "compile"}))
    if fail:
        body += [("action.failed", {"action": "link:tests_moteur", "target": "tests_moteur", "kind": "link", "returncode": 1, "duration": 0.1, "output": "..."}),
                 ("target.failed", {"target": "tests_moteur", "error": "ld: cannot find -lmoteur_extra", "code": "CH3003"})]
    else:
        body += [("action.finished", {"action": "link:tests_moteur", "target": "tests_moteur", "kind": "link", "duration": 0.1, "outputs": ["build/Debug/tests_moteur/tests_moteur"]}),
                 ("target.finished", {"target": "tests_moteur", "duration": 0.4, "executed": 1, "cached": 3, "up_to_date": 0})]
    ran = sum(1 for kind, _ in body if kind.startswith("action."))
    total = ran + (2 if fail else 0)
    head: List[Event] = [("session.started", {"command": "build", "argv": ["build"], "cwd": ".", "version": "demo", "config": "Debug"}),
                         ("workspace.loaded", {"name": "CasqueDemo", "path": ".", "targets": len(TARGETS)}),
                         ("graph.analyzed", {"actions": total, "targets": len(TARGETS), "critical_path": 2.0, "config": "Debug"})]
    tail: List[Event] = [("session.finished", {"ok": not fail, "duration": 4.2, "exit_code": 1 if fail else 0})]
    return head + body + tail


def run(argv: Optional[Sequence[str]] = None, out: Optional[TextIO] = None, env: Optional[Mapping[str, str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m charpente.ui", description="Show the Charpente banner and a made-up build, to judge the console style.")
    parser.add_argument("--theme", choices=sorted(banner.THEMES), help="Colour theme (default: CHARPENTE_THEME, else bois)")
    parser.add_argument("--lang", choices=["en", "fr"], help="Language (default: the current one)")
    parser.add_argument("--color", choices=["auto", "always", "never"], help="Force colours on or off (default: auto)")
    parser.add_argument("--ascii", action="store_true", help="Draw with ASCII characters only")
    parser.add_argument("--symbols", choices=["modern", "safe"], help="Symbols for a modern terminal font, or the safe ones of a classic Windows console (default: detected)")
    parser.add_argument("--width", type=int, help="Pretend the terminal is this many columns wide")
    parser.add_argument("--fail", action="store_true", help="End with a failing target (the default, as in the design); use --ok for a clean build")
    parser.add_argument("--ok", action="store_true", help="A build without failure")
    parser.add_argument("--delay", type=float, default=0.03, help="Seconds between events, to see the progress bar move (default 0.03; 0 for none)")
    parser.add_argument("--no-banner", action="store_true", help="Only the build lines")
    args = parser.parse_args(list(argv) if argv is not None else None)

    out = sys.stdout if out is None else out
    environment = dict(os.environ if env is None else env)
    if args.theme:
        environment["CHARPENTE_THEME"] = args.theme
    if args.color:
        environment["CHARPENTE_COLOR"] = args.color
    if args.ascii:
        environment["CHARPENTE_ASCII"] = "1"
    if args.symbols:
        environment["CHARPENTE_SYMBOLS"] = args.symbols
    caps = detect(environment, out)
    if args.width and args.width > 0:
        caps = Caps(tty=caps.tty, color=caps.color, unicode=caps.unicode, width=min(args.width, 1000), ci=caps.ci, modern=caps.modern)
    theme = banner.theme_named(environment.get("CHARPENTE_THEME"))
    if not args.no_banner:
        banner.print_banner(out, caps=caps, env=environment, theme=theme, lang=args.lang, version=None, force=True)
    bus = EventBus()
    StyledRenderer(bus, out=out, caps=caps, theme=theme, lang=args.lang, target_names=TARGETS, env=environment, context={"platform": "linux-x64", "tools": "gcc 13.2"})
    for kind, payload in session(fail=not args.ok):
        bus.emit(kind, **payload)
        if args.delay > 0 and caps.tty:
            bus.flush()
            time.sleep(args.delay)
    bus.flush()
    bus.close()
    return 0
