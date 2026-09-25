from typing import Callable, Dict, List

from . import ask, build, clean, explain, init, package, run, test

COMMANDS: Dict[str, Callable[[List[str]], int]] = {
    "init": init.execute,
    "build": build.execute,
    "run": run.execute,
    "clean": clean.execute,
    "test": test.execute,
    "package": package.execute,
    "ask": ask.execute,
    "explain": explain.execute,
}

__all__ = ["COMMANDS"]
