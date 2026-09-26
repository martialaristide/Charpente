"""`charpente check` -- the quality gate."""
from __future__ import annotations

import argparse
import json
from typing import List

from ..quality import gate
from ..quality.model import LEVEL_ALIASES
from ._common import find_root


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente check", description="Run the quality gate.")
    parser.add_argument("--level", choices=sorted(LEVEL_ALIASES), help="rapide (pre-commit), standard (pre-push), strict "
                                                                         "(release/PR); default: [gate] level in .charpente/quality.toml")
    parser.add_argument("--changed", action="store_true", help="Only the files modified since the last commit")
    parser.add_argument("--fix", action="store_true", help="Apply safe automatic fixes (formatting, clang-tidy), then re-verify")
    parser.add_argument("--only", action="append", default=[], metavar="CHECK", help="Run just this check (repeatable)")
    parser.add_argument("--skip", action="append", default=[], metavar="CHECK", help="Skip this check (repeatable)")
    parser.add_argument("--platform", help="Build for this platform in the build check")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON")
    parser.add_argument("--list", action="store_true", help="List the checks and the level of each, then exit")
    parser.add_argument("--init", action="store_true", help="Write a starter .charpente/quality.toml, then exit")
    parser.add_argument("--hook", choices=["pre-commit", "pre-push"], help=argparse.SUPPRESS)
    parsed = parser.parse_args(args)

    root = find_root()
    if parsed.init:
        path = root / gate.CONFIG_PATH
        if path.exists():
            print(f"{gate.CONFIG_PATH} already exists; not overwritten.")
            return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(gate.DEFAULT_CONFIG, encoding="utf-8")
        print(f"Wrote {gate.CONFIG_PATH}. Edit it, commit it, and run `charpente hooks install`.")
        return 0
    if parsed.list:
        config = gate.load_config(root)
        for check in gate.all_checks():
            state = "" if config.enabled(check.name) else "  (disabled in quality.toml)"
            print(f"  {check.level:<9} {check.name:<11} {check.description}{state}")
        return 0

    from ..events import EventBus

    bus = EventBus()
    if parsed.json:
        say = lambda text: None                                        # noqa: E731
    else:
        say = print
        from ..output import PlainRenderer

        PlainRenderer(bus, verbose=False)
    result = gate.run_gate(root, level=parsed.level, changed=parsed.changed, fix=parsed.fix, only=parsed.only,
                           skip=parsed.skip, bus=bus, platform=parsed.platform, say=say)
    tree = gate.index_tree(root) if (parsed.hook or result.ok) else None
    gate.write_record(root, result, tree=tree if parsed.hook == "pre-commit" or (result.ok and not parsed.changed) else None)
    if parsed.json:
        print(json.dumps({**result.to_dict(), "findings": [
            {"check": r.name, "message": f.message, "file": f.file, "line": f.line, "severity": f.severity}
            for r in result.results for f in r.findings]}, indent=1))
    else:
        print(gate.render(result))
    return 0 if result.ok else 1

