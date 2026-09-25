"""A scriptable stand-in for a GNU-style compiler toolchain, used by engine tests.

It behaves like the real thing where the engine can observe it: a compile
creates the object (and writes a `-MF` depfile listing the headers it is told
the source includes), an archive/link creates its output. Every call is
recorded (thread-safely) and can be delayed or made to fail.
"""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from charpente.dsl.model import Kind, Target, Workspace
from charpente.toolchains import Toolchain

GCC = Toolchain(name="gcc", c_compiler="gcc", cxx_compiler="g++", archiver="ar", linker="g++")


class FakeToolchain:
    def __init__(self, headers: Optional[Dict[str, List[str]]] = None, fail_on: Iterable[str] = (),
                 delay: float = 0.0, on_call: Optional[Callable[[List[str]], None]] = None) -> None:
        self.headers = headers or {}          # source stem -> header paths it "includes"
        self.fail_on = set(fail_on)
        self.delay = delay
        self.on_call = on_call
        self.calls: List[List[str]] = []
        self.compiles: List[str] = []         # stems compiled, in order
        self.concurrent = 0
        self.max_concurrent = 0
        self._lock = threading.Lock()

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        with self._lock:
            self.calls.append(argv)
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            if self.on_call:
                self.on_call(argv)
            if self.delay:
                time.sleep(self.delay)
            return self._run(argv)
        finally:
            with self._lock:
                self.concurrent -= 1

    def _run(self, argv):
        if "-c" in argv:
            src = Path(argv[argv.index("-c") + 1])
            obj = Path(argv[argv.index("-o") + 1])
            with self._lock:
                self.compiles.append(src.stem)
            if src.stem in self.fail_on:
                return subprocess.CompletedProcess(
                    argv, 1, stdout="", stderr=f"{src}:1:1: error: compiling {src.name} failed")
            obj.parent.mkdir(parents=True, exist_ok=True)
            obj.write_text(f"object of {src.name}: {src.read_text()}")
            if "-MF" in argv:
                dep = Path(argv[argv.index("-MF") + 1])
                dep.parent.mkdir(parents=True, exist_ok=True)
                names = " ".join(str(h).replace(" ", "\\ ") for h in self.headers.get(src.stem, []))
                dep.write_text(f"{obj}: {src} {names}\n")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if "rcs" in argv:
            out = Path(argv[argv.index("rcs") + 1])
        elif "-o" in argv:
            out = Path(argv[argv.index("-o") + 1])
        else:
            return subprocess.CompletedProcess(argv, 0, stdout="fake 1.0\n", stderr="")
        if out.stem in self.fail_on:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="link error")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("binary")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def make_workspace(tmp_path: Path, sources: Dict[str, str], *, kind: Kind = Kind.EXECUTABLE,
                   name: str = "app", **target_kwargs) -> Workspace:
    for rel, text in sources.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    ws = Workspace(name="Demo", location=tmp_path)
    ws.add_target(Target(name=name, kind=kind, source_patterns=["**/*.cpp"], location=tmp_path, **target_kwargs))
    return ws


def collect_events(bus, patterns=None):
    events: List = []
    bus.subscribe(events.append, sync=True, types=patterns)
    return events
