"""Build flavours of a toolchain: sanitizers and coverage.

A flavour is the same compiler with extra flags and its own build directory (`build/Debug-san-address/`), so
instrumented and normal objects never mix and switching between them rebuilds nothing. Whether a toolchain *can*
build a flavour is found by trying it (`probe`), not by guessing from its name.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

from .core import process
from .errors import ChError
from .flags import family
from .toolchains import Toolchain

SANITIZERS = ("address", "undefined", "thread", "memory", "leak")


def _need_gnu(toolchain: Toolchain, what: str) -> None:
    if family(toolchain) == "msvc":
        raise ChError("CH8011", what=what, reason=f"{toolchain.name} takes different options (/fsanitize=address only) "
                                                 "which Charpente does not drive yet")


def with_flags(toolchain: Toolchain, variant: str, compile_flags: Tuple[str, ...], link_flags: Tuple[str, ...]) -> Toolchain:
    return replace(toolchain, variant=variant, c_args=(*toolchain.c_args, *compile_flags),
                   cxx_args=(*toolchain.cxx_args, *compile_flags), ld_args=(*toolchain.ld_args, *link_flags))


def sanitize(toolchain: Toolchain, kinds: Iterable[str]) -> Toolchain:
    """`-fsanitize=address,undefined`: the flavour is named `san-address-undefined`."""
    chosen = sorted(set(kinds))
    unknown = [k for k in chosen if k not in SANITIZERS]
    if not chosen or unknown:
        raise ChError("CH8011", what="sanitizers", reason=f"unknown sanitizer(s) {', '.join(unknown) or '(none given)'}; "
                                                          f"choose among {', '.join(SANITIZERS)}")
    _need_gnu(toolchain, "sanitizers")
    flags = (f"-fsanitize={','.join(chosen)}", "-fno-omit-frame-pointer")
    return with_flags(toolchain, "san-" + "-".join(chosen), flags, (f"-fsanitize={','.join(chosen)}",))


def coverage(toolchain: Toolchain) -> Toolchain:
    """`--coverage` (gcov-compatible instrumentation): the flavour is named `cov`."""
    _need_gnu(toolchain, "coverage")
    return with_flags(toolchain, "cov", ("--coverage", "-O0"), ("--coverage",))


def _reason(output: str, fallback: str) -> str:
    """The most informative line of a failed probe: the tool's own words about what is missing or unsupported."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in lines:
        if re.search(r"(?i)cannot find|unsupported|unrecognized|not found|no such|undefined reference|unknown", line):
            return line[:300]
    if lines and "ld returned" in lines[-1]:
        return lines[-1][:200] + " (the sanitizer/coverage runtime is probably missing from this toolchain)"
    return lines[-1][:300] if lines else fallback


def probe(toolchain: Toolchain, *, run: Callable[..., process.ProcessResult] = process.run,
          execute: bool = True) -> Optional[str]:
    """Try a trivial program with the flavour's flags: None when it builds (and runs), else the reason it cannot."""
    with tempfile.TemporaryDirectory() as tmp:
        source, obj = Path(tmp) / "probe.c", Path(tmp) / "probe.o"
        exe = Path(tmp) / ("probe.exe" if toolchain.name in ("mingw", "msvc", "clang-cl") else "probe")
        source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
        steps = [[toolchain.c_compiler, *toolchain.c_args, "-c", str(source), "-o", str(obj)],
                 [toolchain.linker, *toolchain.ld_args, str(obj), "-o", str(exe)]]
        for argv in steps:
            try:
                result = run(argv, timeout=120)
            except ChError as exc:
                return str(exc)
            if result.returncode != 0:
                return _reason(result.output, f"{Path(argv[0]).name} failed")
        if execute and not toolchain.target:
            result = run([str(exe)], timeout=60)
            if result.returncode != 0:
                return _reason(result.output, f"the instrumented program exited with {result.returncode}")
    return None


def require(toolchain: Toolchain, what: str, *, run: Callable[..., process.ProcessResult] = process.run) -> Toolchain:
    """`toolchain` if it can really build its flavour, else CH8011 with the compiler's own reason."""
    reason = probe(toolchain, run=run)
    if reason is not None:
        raise ChError("CH8011", what=what, reason=reason)
    return toolchain
