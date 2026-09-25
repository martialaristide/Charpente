"""GitHub Actions annotations: compiler diagnostics become inline warnings and
errors on the pull request (`::error file=...,line=...::message`)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, TextIO

from ..events import Event, EventBus, Subscription


def escape_data(text: str) -> str:
    """Workflow-command message escaping (the documented %, CR, LF rules)."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(text: str) -> str:
    return escape_data(text).replace(":", "%3A").replace(",", "%2C")


def running_on_github() -> bool:
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def annotation(level: str, message: str, *, file: Optional[str] = None, line: Optional[int] = None,
               column: Optional[int] = None, title: Optional[str] = None) -> str:
    props = []
    if file:
        props.append(f"file={escape_property(file)}")
    if line:
        props.append(f"line={line}")
    if column:
        props.append(f"col={column}")
    if title:
        props.append(f"title={escape_property(title)}")
    head = f"::{level}" + (" " + ",".join(props) if props else "")
    return f"{head}::{escape_data(message)}"


class GitHubAnnotations:
    """Prints an annotation for every warning/error diagnostic. Paths are made
    relative to the repository (`GITHUB_WORKSPACE`, else the workspace root)."""

    _LEVELS = {"error": "error", "warning": "warning", "note": "notice"}

    def __init__(self, bus: EventBus, root: Optional[Path] = None, out: Optional[TextIO] = None) -> None:
        base = os.environ.get("GITHUB_WORKSPACE") or (str(root) if root else "")
        self._base = Path(base) if base else None
        self._out = out
        self.subscription: Subscription = bus.subscribe(self._on_event, name="github",
                                                        types=["diagnostic.emitted"])

    def _relative(self, file: Optional[str]) -> Optional[str]:
        if not file:
            return None
        if self._base is not None:
            try:
                return Path(file).resolve().relative_to(self._base.resolve()).as_posix()
            except (ValueError, OSError):
                pass
        return file.replace("\\", "/")

    def _on_event(self, event: Event) -> None:
        p = event.payload
        level = self._LEVELS.get(str(p.get("severity")), "notice")
        text = annotation(level, str(p["message"]), file=self._relative(p.get("file")), line=p.get("line"),
                          column=p.get("column"), title=p.get("code") or None)
        out = self._out if self._out is not None else sys.stdout
        print(text, file=out)
        out.flush()
