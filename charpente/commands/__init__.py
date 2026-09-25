from typing import Callable, Dict, List

from . import ask, build, cache, clean, explain, headers, history, init, package, replay, run, test, why

COMMANDS: Dict[str, Callable[[List[str]], int]] = {
    "init": init.execute,
    "build": build.execute,
    "run": run.execute,
    "clean": clean.execute,
    "test": test.execute,
    "package": package.execute,
    "ask": ask.execute,
    "explain": explain.execute,
    "why": why.execute,
    "history": history.execute,
    "diff-build": history.execute_diff,
    "cache": cache.execute,
    "headers": headers.execute,
    "replay": replay.execute,
}

__all__ = ["COMMANDS"]
