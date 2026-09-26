"""`charpente menu` -- the guided console interface (also what a bare `charpente` opens in a terminal)."""
from __future__ import annotations

import argparse
from typing import List


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente menu", description="A guided menu for the terminal: create, build, run, test, package, diagnose.")
    parser.parse_args(args)
    from ..console import run

    return run()
