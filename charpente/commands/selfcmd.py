"""`charpente self uninstall` -- remove what Charpente stores on this machine (a dry run unless you say `--yes`)."""
from __future__ import annotations

import argparse
import os
import sys
from typing import List

from .. import selfmanage
from ..dsl.trust import config_dir


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente self", description="Manage Charpente's own files on this machine.")
    sub = parser.add_subparsers(dest="action", required=True)
    un = sub.add_parser("uninstall", help="Remove Charpente's cache, toolchains, packages, settings... (dry run unless --yes)")
    un.add_argument("--only", action="append", metavar="GROUP", help=f"Remove only these groups (repeatable). Groups: {', '.join(selfmanage.GROUPS)}")
    un.add_argument("--keys", action="store_true", help="Also remove the release signing keys (they cannot be recreated)")
    un.add_argument("--yes", action="store_true", help="Really remove (without it, only shows what would be removed)")
    parsed = parser.parse_args(args)

    config = config_dir()
    items, notes = selfmanage.plan(config, os.environ.get("CHARPENTE_CACHE_DIR"))
    chosen, refusals = selfmanage.select(items, parsed.only, parsed.keys)
    for line in refusals:
        print(f"note: {line}", file=sys.stderr)
    for line in notes:
        print(f"note: {line}", file=sys.stderr)
    if refusals and parsed.only and not chosen:
        return 2
    if not chosen:
        print(f"Nothing to remove under {config}.")
        return 0

    print(f"Charpente's files under {config}:")
    for item in chosen:
        what = selfmanage.GROUPS[item.group][0]
        print(f"  {item.group:<11} {selfmanage.humanize(item.size):>9}  {item.path}   ({what})" + ("   [link: only the link is removed]" if item.is_link else ""))
    print(f"  total {selfmanage.humanize(sum(i.size for i in chosen))}")
    if not parsed.yes:
        print("\nThis was a dry run: nothing was removed. Run again with --yes to remove the files listed above.")
        print("Your projects, and the `.charpente` files in them, are never touched.")
        return 0

    failed = 0
    for item in chosen:
        problem = selfmanage.remove(item)
        if problem:
            failed += 1
            print(f"  could not remove {item.path}: {problem}", file=sys.stderr)
        else:
            print(f"  removed {item.path}")
    try:
        config.rmdir()                                                # only succeeds when nothing else is left: a shared folder is never emptied
        print(f"  removed {config}")
    except OSError:
        pass
    print("\nTo remove the program itself:  " + " ".join(selfmanage.pip_command(sys.executable)))
    return 1 if failed else 0
