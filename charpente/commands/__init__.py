from typing import Callable, Dict, List

from . import ask, build, clean, init, package, run, test

COMMANDS: Dict[str, Callable[[List[str]], int]] = {
    "init": init.execute,
    "build": build.execute,
    "run": run.execute,
    "clean": clean.execute,
    "test": test.execute,
    "package": package.execute,
    "ask": ask.execute,
}

__all__ = ["COMMANDS"]
