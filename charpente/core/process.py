"""The ONLY place in Charpente allowed to start an operating-system process.

Rules enforced here (and by tests/test_process_layer.py, which fails if any
other module imports `subprocess` or enables the shell):

* a command is always a list of arguments -- a plain string is refused;
* the shell is never used: there is no parameter that could enable it;
* a missing executable becomes a `ChError` (CH2002), not a bare traceback;
* output is always decoded to `str` without ever raising on odd bytes
  (compilers on Windows may emit OEM code pages).

Tests inject a fake `runner` (same call shape as `subprocess.run`), which is
how the pure parts of the build stay testable without a compiler.
"""
from __future__ import annotations

import locale
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from ..errors import ChError

Argv = Sequence[str]
CompletedProcess = subprocess.CompletedProcess
Runner = Callable[..., "subprocess.CompletedProcess[Any]"]


@dataclass(frozen=True)
class ProcessResult:
    """What a finished process looked like. Immutable and comparable."""

    argv: "tuple[str, ...]"
    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        """stdout and stderr joined, non-empty parts only (a compiler may split
        one failure across both streams)."""
        parts = [s for s in (self.stdout, self.stderr) if s and s.strip()]
        return "\n".join(parts).strip()


def _decode(data: Union[bytes, str, None]) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(locale.getpreferredencoding(False) or "utf-8", errors="replace")


def _check_argv(argv: Any) -> "list[str]":
    if isinstance(argv, (str, bytes)):
        raise ChError("CH9001", command=_shorten(argv))
    try:
        items = [os.fspath(a) if not isinstance(a, str) else a for a in argv]
    except TypeError as exc:
        raise ChError("CH9001", command=_shorten(argv)) from exc
    if not items or not all(isinstance(a, str) for a in items) or not items[0]:
        raise ChError("CH9001", command=_shorten(items))
    return items


def _shorten(value: Any, limit: int = 80) -> str:
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def raw_run(argv: Argv, *, capture_output: bool = True, cwd: Optional[str] = None,
            env: Optional[Mapping[str, str]] = None, timeout: Optional[float] = None,
            input: Optional[str] = None, **_ignored: Any) -> "subprocess.CompletedProcess[str]":
    """`subprocess.run`-compatible primitive (the shape tests replace).

    Accepts and ignores the legacy `text=`/`shell=` keywords, so code that
    used to call `subprocess.run(argv, capture_output=True, text=True,
    shell=False)` can pass through unchanged -- but `shell` is never forwarded.
    """
    items = _check_argv(argv)
    # A child whose output is captured is not interactive: it gets no stdin (rather than ours), so a tool that waits for
    # input fails at once, and a server that speaks over stdin/stdout never has its channel read by a child.
    extra: "dict[str, Any]" = {"stdin": subprocess.DEVNULL} if capture_output and input is None else {}
    try:
        completed = subprocess.run(
            items,
            shell=False,
            capture_output=capture_output,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            timeout=timeout,
            input=input.encode("utf-8") if isinstance(input, str) else input,
            **extra,
        )
    except FileNotFoundError as exc:
        raise ChError("CH2002", tool=items[0]) from exc
    except PermissionError as exc:
        raise ChError("CH2004", tool=items[0]) from exc
    return subprocess.CompletedProcess(
        completed.args, completed.returncode,
        _decode(completed.stdout), _decode(completed.stderr),
    )


def windows_command_line(argv: Sequence[str]) -> str:
    """`argv` quoted the way Windows programs parse a command line (for display and environment variables; never executed)."""
    return subprocess.list2cmdline([str(a) for a in argv])


def run(argv: Argv, *, capture: bool = True, cwd: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None, timeout: Optional[float] = None,
        input: Optional[str] = None, runner: Optional[Runner] = None) -> ProcessResult:
    """Run `argv` to completion and return a `ProcessResult`.

    capture=False lets the child inherit this process's stdin/stdout/stderr
    (used to run the user's own program: its output goes straight to the
    terminal).
    """
    items = _check_argv(argv)
    start = time.monotonic()
    call = runner or raw_run
    completed = call(items, capture_output=capture, text=True, shell=False,
                     cwd=cwd, env=env, timeout=timeout, input=input)
    return ProcessResult(
        argv=tuple(items),
        returncode=completed.returncode,
        stdout=_decode(completed.stdout),
        stderr=_decode(completed.stderr),
        duration=time.monotonic() - start,
    )
