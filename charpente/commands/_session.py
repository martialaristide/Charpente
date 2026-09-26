"""A command's session: the event bus, its subscribers and the session
start/finish events, in one place so every build-like command behaves alike.

Subscribers attached here:

* how the build is shown -- `--output auto` (default: a live progress bar on an
  interactive terminal when `rich` is installed, otherwise plain text),
  `plain`, `rich`, or `jsonl` (one JSON event per line, for scripts and editors);
* GitHub Actions annotations, automatically when running inside Actions;
* the replayable per-session log `build/.charpente/events/<session>.jsonl`;
* the build history database (`charpente history`, `charpente diff-build`);
* the workspace's own hooks (`@ws.on(...)`, `.charpente/hooks/`);
* event subscribers contributed by enabled modules (e.g. notifications).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Optional, Type

from .. import _version, hooks
from ..builder import state_dir
from ..core.history import HistoryRecorder
from ..dsl import trust
from ..dsl.model import Workspace
from ..events import EventBus
from ..output import JsonlStream, PlainRenderer, SessionLog, rich_renderer
from ..output import github as github_output

OUTPUT_MODES = ("auto", "plain", "rich", "jsonl")


def add_engine_args(parser: argparse.ArgumentParser, *, output: bool = True) -> None:
    parser.add_argument("-j", "--jobs", type=int, default=0, metavar="N",
                        help="Maximum parallel actions (default: one per CPU)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Do not read or write the content cache")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show every command that runs, and why")
    parser.add_argument("--opt", action="append", default=[], metavar="NAME=VALUE",
                        help="Set a workspace option declared with ws.option() (repeatable)")
    parser.add_argument("--platform", metavar="OS-ARCH", default=None,
                        help="Build for another platform (`charpente platforms` lists them), e.g. linux-arm64")
    parser.add_argument("--toolchain", metavar="NAME", default=None,
                        help="Use this toolchain instead of the first detected one (`charpente toolchain list`)")
    if output:
        parser.add_argument("--output", choices=OUTPUT_MODES, default="auto",
                            help="'auto' (default): live progress on a terminal, plain text otherwise; "
                                 "'plain'; 'rich' (needs `pip install charpente[rich]`); "
                                 "'jsonl' for scripts (one JSON event per line)")


class Session:
    def __init__(self, command: str, parsed: argparse.Namespace, workspace: Optional[Workspace] = None,
                 *, toolchain: str = "", config: str = "") -> None:
        self.command = command
        mode = getattr(parsed, "output", "plain")
        if mode == "auto":
            verbose = bool(getattr(parsed, "verbose", False))
            mode = "rich" if (not verbose and rich_renderer.wanted_by_default()) else "plain"
        self.machine = mode == "jsonl"
        self.bus = EventBus()
        self._started = time.monotonic()
        self._closed = False
        self.log: Optional[SessionLog] = None
        self.history: Optional[HistoryRecorder] = None
        self.renderer: Optional[rich_renderer.RichRenderer] = None
        if self.machine:
            JsonlStream(self.bus, sys.stdout)
        elif mode == "rich":
            self.renderer = rich_renderer.RichRenderer(self.bus)
        else:
            PlainRenderer(self.bus, verbose=bool(getattr(parsed, "verbose", False)))
        root = workspace.location if workspace is not None else None
        if not self.machine and github_output.running_on_github():
            github_output.GitHubAnnotations(self.bus, root)
        if workspace is not None and root is not None:
            base = state_dir(workspace)
            self.log = SessionLog(self.bus, base / "events")
            self.history = HistoryRecorder(self.bus, base / "history.db", command=command, config=config,
                                           toolchain=toolchain)
            self._attach_hooks(workspace, root)
        self._attach_module_subscribers(root)
        self.bus.emit("session.started", command=command, argv=list(sys.argv[1:]),
                      cwd=str(root or ""), version=_version.__version__, config=config or None)
        if workspace is not None:
            self.bus.emit("workspace.loaded", name=workspace.name, path=str(root or ""),
                          targets=len(workspace.targets))

    # --------------------------------------------------------------- hooks
    def _attach_hooks(self, workspace: Workspace, root: Path) -> None:
        if workspace.hooks:
            hooks.HookRunner(self.bus, list(workspace.hooks))
        scripts = hooks.discover_scripts(root)
        if not scripts:
            return
        key = str(root / hooks.HOOKS_DIR)
        if trust.ensure_trusted_digest(key, hooks.scripts_digest(scripts), label="hook scripts"):
            hooks.ScriptHooks(self.bus, scripts, root)
        else:
            print(f"charpente: the scripts in {hooks.HOOKS_DIR} were not run because they are not approved "
                  f"(run interactively once, or set CHARPENTE_TRUST_ALL=1 if you trust this repository).",
                  file=sys.stderr)

    def _attach_module_subscribers(self, root: Optional[Path]) -> None:
        """Event subscribers contributed by enabled modules (notifiers, hooks...)."""
        from ..modules import runtime

        try:
            manager = runtime.get_manager()
            manager.set_workspace(root)
            for extension in manager.registry.all("event_subscriber"):
                sub = extension.obj
                self.bus.subscribe(sub, name=sub.name, types=list(sub.patterns))
        except Exception as exc:  # a broken module must never break a build
            print(f"charpente: modules could not be attached: {exc}", file=sys.stderr)

    # ------------------------------------------------------------ lifecycle
    def finish(self, ok: bool, exit_code: Optional[int] = None) -> None:
        if self._closed:
            return
        self._closed = True
        self.bus.emit("session.finished", ok=ok, duration=time.monotonic() - self._started,
                      exit_code=exit_code)
        self.bus.close()
        if self.renderer is not None:
            self.renderer.finish()
        if self.log is not None:
            self.log.close()

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException],
                 tb: Optional[TracebackType]) -> None:
        if self._closed:
            return
        if exc_type is not None and issubclass(exc_type, KeyboardInterrupt):
            self.bus.emit("session.interrupted", reason="keyboard")
        self.finish(ok=exc_type is None, exit_code=None if exc_type is None else 1)

    # -------------------------------------------------------------- helpers
    def flush(self) -> None:
        """Let the renderers catch up, and stop any live display, before the caller prints."""
        self.bus.flush()
        if self.renderer is not None:
            self.renderer.finish()

    def say(self, text: str = "", **kwargs: Any) -> None:
        """Human-readable line; suppressed in machine output modes."""
        if not self.machine:
            print(text, **kwargs)
