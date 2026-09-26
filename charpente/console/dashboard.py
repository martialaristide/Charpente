"""What the console interface shows about where you are: the project in the current folder, its targets, the last build, the compiler.

`gather` never raises and never runs a project file that you have not approved: a `.charpente` file is code, so it is loaded here only when it is already trusted
(Charpente asks before running it the first time you build). Everything it reads comes through small functions passed in, so tests give it fakes.
"""
from __future__ import annotations

import contextlib
import io
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .. import _version


@dataclass(frozen=True)
class TargetInfo:
    name: str
    kind: str


@dataclass(frozen=True)
class LastBuild:
    ok: bool
    when: float              # seconds since the epoch
    duration: float
    config: str
    command: str


@dataclass
class Dashboard:
    version: str = _version.__version__
    host: str = ""
    compiler: str = ""
    root: Optional[Path] = None
    file: Optional[Path] = None
    name: str = ""
    targets: List[TargetInfo] = field(default_factory=list)
    state: str = "none"          # none | ok | untrusted | error | ambiguous
    detail: str = ""
    last: Optional[LastBuild] = None

    @property
    def has_project(self) -> bool:
        return self.state in ("ok", "untrusted", "error") and self.file is not None

    def runnable(self) -> List[TargetInfo]:
        return [t for t in self.targets if t.kind in ("executable", "test", "xr_app", "web_app")]


LoadResult = Tuple[str, Path, List[TargetInfo], Optional[LastBuild]]


def _find(cwd: Path) -> Path:
    from ..workspace_finder import find_workspace_file

    return find_workspace_file(cwd)


def _trusted(path: Path) -> bool:
    from ..dsl.trust import TRUST_ALL_ENV, is_trusted

    if os.environ.get(TRUST_ALL_ENV, "").strip().lower() in ("1", "true", "yes"):     # the same switch the commands honour (a CI you control)
        return True
    return path.suffix.lower() == ".toml" or is_trusted(path)


def _load(path: Path) -> LoadResult:
    from ..builder import state_dir
    from ..commands._common import load
    from ..core import history

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):     # lint notes must not break the screen
        workspace = load(str(path), None, materialize_packages=False)
    targets = [TargetInfo(name, target.kind.value) for name, target in workspace.targets.items() if not target.external]
    sessions = history.list_sessions(state_dir(workspace) / "history.db", 1)
    last = None
    if sessions:
        s = sessions[0]
        last = LastBuild(s.ok, s.started, s.duration, s.config, s.command)
    return workspace.name, Path(workspace.root), targets, last


def _compiler() -> str:
    from .. import toolchains
    from ..platform import host_os

    found = toolchains.detect(host_os())
    if not found:
        return ""
    return f"{found[0].name} ({Path(found[0].cxx_compiler).name})"


def _host() -> str:
    from .. import platforms

    return platforms.host().name


def gather(cwd: Path, *, find: Callable[[Path], Path] = _find, trusted: Callable[[Path], bool] = _trusted,
           load: Callable[[Path], LoadResult] = _load, compiler: Callable[[], str] = _compiler,
           host: Callable[[], str] = _host) -> Dashboard:
    dash = Dashboard()
    for attr, source in (("compiler", compiler), ("host", host)):
        try:
            setattr(dash, attr, source())
        except Exception:                                    # a missing piece of information is shown as missing, never as a crash
            setattr(dash, attr, "")
    try:
        path = find(cwd)
    except Exception as exc:
        code = getattr(exc, "code", "")
        if code == "CH1003":
            dash.state, dash.detail = "ambiguous", str(getattr(exc, "message", exc))
        return dash                                          # CH1002 (no project here) and anything unexpected: no project
    dash.file, dash.root, dash.name = path, path.parent, path.stem
    if not trusted(path):
        dash.state = "untrusted"
        return dash
    try:
        dash.name, dash.root, dash.targets, dash.last = load(path)
        dash.state = "ok"
    except Exception as exc:
        dash.state, dash.detail = "error", str(getattr(exc, "message", exc))
    return dash
