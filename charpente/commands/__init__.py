from typing import Callable, Dict, List

from . import (
    ask,
    build,
    cache,
    clean,
    explain,
    headers,
    history,
    init,
    lint,
    module,
    package,
    pkg,
    replay,
    run,
    test,
    toolchain,
    why,
)

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
    "module": module.execute,
    "pkg": pkg.execute,
    "sbom": pkg.execute_sbom,
    "lint": lint.execute,
    "migrate": lint.execute_migrate,
    "options": lint.execute_options,
    "toolchain": toolchain.execute,
    "headers": headers.execute,
    "replay": replay.execute,
}

__all__ = ["COMMANDS"]
