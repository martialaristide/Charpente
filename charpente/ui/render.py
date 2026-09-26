"""The styled build display: an event subscriber that prints a build the way `Style` describes (stages, one line per target, warnings, a progress bar, a result box).

It is the only component of the console style that writes to the screen, and it does so from the events of the bus -- nothing else is asked of the engine, and no event or
field was added for it. It is used for `--output auto` on a real terminal (the human default); `plain`, `jsonl` and `rich` are untouched.

Rules it keeps:

* **It never fails a build.** A closed stream, an encoding that cannot write a character, a broken pipe or a bug in formatting is swallowed; at worst the display stops.
* **The progress bar is transient**: it is the last line while the build runs and is erased before any other line is printed (with carriage returns and spaces, never an escape
  sequence, so it also works with `NO_COLOR`); the final bar is printed once, just before the result box.
* **Compiler output is not hidden**: a failed target shows the first lines of its output under the failure line; the text of a *successful* action (warnings) is summarised as
  a count, and shown as it was when it did not come with a parsed warning (`charpente build -v` shows everything).
"""
from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, TextIO, Tuple

from ..events import Event, EventBus, Subscription
from ..i18n import ui as words
from .banner import Theme, theme_named
from .style import Style
from .term import Caps, detect

MAX_NAME_WIDTH = 24
ERROR_LINES = 12
OUTPUT_LINES = 6
_VERSION = re.compile(r"\d+(?:\.\d+)+")


def display_path(path: str, cwd: Optional[Path] = None) -> str:
    """A path as shown: relative to `cwd` when it is below it, with forward slashes."""
    try:
        candidate = Path(path)
        if cwd is not None:
            try:
                candidate = candidate.resolve().relative_to(cwd.resolve())
            except (ValueError, OSError):
                pass
        return str(candidate).replace("\\", "/")
    except (TypeError, ValueError):
        return str(path)


def tool_label(name: str, version_line: str = "") -> str:
    """`gcc 13.2.0`: the toolchain's name and the version number found in what the compiler printed; just the name when there is none."""
    matches = _VERSION.findall(version_line or "")
    return f"{name} {matches[-1]}" if matches else name


def resolve_tool_label(toolchain: Any) -> str:
    """The label of a detected toolchain (its name and version). Asks the tool once (remembered on disk by the engine); never raises."""
    try:
        from ..core.toolid import ToolIdentities
        from ..flags import family

        identity = ToolIdentities().identify(toolchain.cxx_compiler, family(toolchain))
        return tool_label(toolchain.name, identity.version if identity.resolved else "")
    except Exception:
        return str(getattr(toolchain, "name", ""))


def styled_wanted(stream: Optional[TextIO] = None, env: Optional[Mapping[str, str]] = None) -> bool:
    """Whether `--output auto` should use the styled display: a real terminal, not CI, not a dumb terminal."""
    env = os.environ if env is None else env
    caps = detect(env, stream)
    return caps.tty and not caps.ci and env.get("TERM", "") != "dumb"


class StyledRenderer:
    def __init__(self, bus: EventBus, *, out: Optional[TextIO] = None, caps: Optional[Caps] = None, theme: Optional[Theme] = None, lang: Optional[str] = None,
                 context: Optional[Mapping[str, str]] = None, target_names: Sequence[str] = (), cwd: Optional[Path] = None,
                 env: Optional[Mapping[str, str]] = None) -> None:
        self._out = out
        env = os.environ if env is None else env
        self.caps = caps or detect(env, out)
        self.theme = theme or theme_named(env.get("CHARPENTE_THEME"))
        self.lang = lang or _current_lang()
        self.style = Style(_usable(self.caps), self.theme, self.lang)
        self.context = dict(context or {})
        self.cwd = cwd
        self.name_width = min(MAX_NAME_WIDTH, max((len(n) for n in target_names), default=0))
        self._lock = threading.RLock()
        self._dead = False                               # the output broke: stop writing, keep the build going
        self._bar_shown = False
        self._bar_on = False
        self.reset()
        self.subscription: Subscription = bus.subscribe(
            self._on_event, name="styled",
            types=["session.started", "session.interrupted", "session.finished", "workspace.loaded", "graph.analyzed", "target.*", "action.finished", "action.cache_hit",
                   "action.up_to_date", "action.failed", "action.output", "diagnostic.emitted", "hint.emitted", "bus.dropped"])

    # ------------------------------------------------------------ state
    def reset(self) -> None:
        self.config = ""
        self.total = 0
        self.done = 0
        self.saved = 0                                   # actions not executed: cache hits and up-to-date
        self.ok_targets = 0
        self.failed_targets: List[str] = []
        self.analyzed = False
        self.interrupted = False
        self._action_target: Dict[str, str] = {}
        self._outputs: Dict[str, str] = {}               # target -> what it produced (from its last finished action)
        self._warnings: Dict[str, int] = {}
        self._errors: Dict[str, str] = {}                # target -> first error message
        self._diagnosed: Set[str] = set()                # actions that produced a parsed diagnostic
        self._pending_output: Dict[str, str] = {}

    # ------------------------------------------------------------ writing (never raises)
    @property
    def out(self) -> TextIO:
        return self._out if self._out is not None else sys.stdout

    def _write(self, text: str) -> None:
        if self._dead:
            return
        try:
            try:
                self.out.write(text)
            except UnicodeEncodeError:                   # a character of a path or message the terminal cannot write: show it as `?`
                encoding = getattr(self.out, "encoding", None) or "ascii"
                self.out.write(text.encode(encoding, "replace").decode(encoding, "replace"))
            self.out.flush()
        except (OSError, ValueError, AttributeError):    # broken pipe, closed stream
            self._dead = True

    def _line(self, text: str = "") -> None:
        with self._lock:
            self._erase_bar()
            self._write(text + "\n")
            self._draw_bar()

    def _draw_bar(self) -> None:
        if not (self._bar_on and self.caps.tty and self.total > 0) or self._dead:
            return
        self._write("\r" + self.style.progress(self.done, self.total))
        self._bar_shown = True

    def _erase_bar(self) -> None:
        if self._bar_shown:
            self._write("\r" + " " * max(0, self.style.caps.width) + "\r")
            self._bar_shown = False

    def finish(self) -> None:
        """Take the transient bar off the screen (idempotent), so the caller can print normally."""
        with self._lock:
            self._bar_on = False
            self._erase_bar()

    # ------------------------------------------------------------ events
    def _on_event(self, event: Event) -> None:
        try:
            with self._lock:
                self._handle(event.type, event.payload)
        except Exception:                                # a formatting bug must never take the build down
            pass

    def t(self, key: str, **values: Any) -> str:
        return words.t(key, self.lang, **values)

    def _plural(self, prefix: str, n: int) -> str:
        return words.t(f"{prefix}.{words.plural_key(self.lang, n)}", self.lang, n=n)

    def _handle(self, kind: str, p: Mapping[str, Any]) -> None:
        if kind == "session.started":
            self.config = str(p.get("config") or "")
        elif kind == "workspace.loaded":
            self._line(self.style.stage(self.t("stage.loading")))
            pairs = [(self.t("context.workspace"), str(p.get("name", ""))), (self.t("context.config"), self.config or self.context.get("config", "")),
                     (self.t("context.platform"), self.context.get("platform", "")), (self.t("context.tools"), self.context.get("tools", ""))]
            self._line(self.style.context(pairs))
        elif kind == "graph.analyzed":
            self.analyzed = True
            self.total = int(p.get("actions") or 0)
            self._bar_on = True
            self._line()
            self._line(self.style.stage(self.t("stage.building")))
        elif kind == "hint.emitted":
            self._line(self.style.note("hint: " + str(p.get("message", ""))))
        elif kind == "bus.dropped":
            self._line(self.style.note(f"{p.get('count')} events were dropped for {p.get('subscriber')}"))
        elif kind == "session.interrupted":
            self.interrupted = True
        elif kind.startswith("action."):
            self._action(kind, p)
        elif kind == "diagnostic.emitted":
            self._diagnostic(p)
        elif kind.startswith("target."):
            self._target(kind, p)
        elif kind == "session.finished":
            self._finished(p)

    def _action(self, kind: str, p: Mapping[str, Any]) -> None:
        action, target = str(p.get("action", "")), str(p.get("target", ""))
        self._action_target[action] = target
        if kind == "action.output":
            self._pending_output[action] = self._pending_output.get(action, "") + str(p.get("text", ""))
            return
        self.done += 1
        if kind in ("action.cache_hit", "action.up_to_date"):
            self.saved += 1
        if kind in ("action.finished", "action.cache_hit"):
            outputs = p.get("outputs") or []
            if isinstance(outputs, (list, tuple)) and outputs and p.get("kind") != "compile":
                self._outputs[target] = str(outputs[0])          # what the link or archive produced; an object file is not what a target "makes"
        if kind == "action.finished":
            self._show_output(action)
        elif kind == "action.cache_hit":
            self._pending_output.pop(action, None)
        elif kind == "action.failed":
            self._pending_output.pop(action, None)
        self._draw_bar_now()

    def _show_output(self, action: str) -> None:
        """Text a successful action printed and that no parsed warning accounts for: shown, dimmed, so nothing useful is hidden."""
        text = self._pending_output.pop(action, "").strip()
        if not text or action in self._diagnosed:
            return
        for line in text.splitlines()[:OUTPUT_LINES]:
            self._line(self.style.detail(line))

    def _draw_bar_now(self) -> None:
        with self._lock:
            self._erase_bar()
            self._draw_bar()

    def _diagnostic(self, p: Mapping[str, Any]) -> None:
        action = str(p.get("action") or "")
        target = self._action_target.get(action, "") or (action.split(":")[1] if action.count(":") >= 2 else "")
        if action:
            self._diagnosed.add(action)
        severity = str(p.get("severity", ""))
        if severity == "warning":
            self._warnings[target] = self._warnings.get(target, 0) + 1
        elif severity == "error" and target not in self._errors:
            location = f"{display_path(str(p.get('file') or ''), self.cwd)}:{p.get('line')}: " if p.get("file") and p.get("line") else ""
            self._errors[target] = f"{location}{p.get('message', '')}"

    def _target(self, kind: str, p: Mapping[str, Any]) -> None:
        name = str(p.get("target", ""))
        if kind == "target.finished":
            self.ok_targets += 1
            executed, cached = int(p.get("executed") or 0), int(p.get("cached") or 0)
            if executed == 0 and cached > 0:
                self._line(self.style.target_cached(name, self.t("target.cached"), self.name_width))
            else:
                output = self._outputs.get(name, "")
                self._line(self.style.target_ok(name, display_path(output, self.cwd) if output else "", p.get("duration"), self.name_width))
            self._show_warnings(name)
        elif kind == "target.up_to_date":
            self.ok_targets += 1
            self._line(self.style.target_cached(name, self.t("target.up_to_date"), self.name_width))
        elif kind == "target.failed":
            self.failed_targets.append(name)
            summary = self._errors.get(name) or self.t("target.failed")
            code = p.get("code")
            self._line(self.style.target_failed(name, f"{summary} [{code}]" if code else summary, self.name_width))
            self._show_warnings(name)
            for line in _error_lines(str(p.get("error", "")), summary, ERROR_LINES):
                self._line(self.style.detail(line))

    def _show_warnings(self, name: str) -> None:
        count = self._warnings.pop(name, 0)
        if count:
            self._line(self.style.warning(self.t("warnings.one" if count == 1 else "warnings.many", target=name, count=count)))

    def _finished(self, p: Mapping[str, Any]) -> None:
        self.finish()
        if not self.analyzed:                            # nothing was built (an error before the build, or a command that does not build): no summary to show
            return
        if self.total > 0:
            self._write(self.style.progress(self.done, self.total) + "\n")
        self._write("\n")
        ok = bool(p.get("ok")) and not self.failed_targets and not self.interrupted
        rows: List[Tuple[str, str]] = []
        if self.interrupted:
            rows.append((self.t("result.targets"), self.t("result.interrupted")))
        elif not (self.ok_targets or self.failed_targets):
            rows.append((self.t("result.targets"), self.t("result.no_targets")))
        else:
            parts = [self._plural("result.ok", self.ok_targets)]
            if self.failed_targets:
                parts.append(self._plural("result.failed", len(self.failed_targets)))
            rows.append((self.t("result.targets"), ", ".join(parts)))
        if self.total > 0:
            rows.append((self.t("result.cache"), self.t(f"result.cache.{words.plural_key(self.lang, self.saved)}", cached=self.saved, total=self.total)))
        try:
            rows.append((self.t("result.duration"), self.style.duration(float(p.get("duration") or 0.0))))
        except (TypeError, ValueError):
            pass
        if self.failed_targets:
            rows.append((self.t("result.next"), f"charpente why {self.failed_targets[0]}"))
        for line in self.style.result_box(self.t("result.title"), rows, ok):
            self._write(line + "\n")


def _current_lang() -> str:
    from ..i18n import current_lang

    return current_lang()


def _usable(caps: Caps) -> Caps:
    """The capabilities as the lines are drawn for them: one column less than the terminal, because writing into the last column makes some Windows consoles wrap early."""
    from dataclasses import replace

    return replace(caps, width=max(10, caps.width - 1))


def _error_lines(error: str, summary: str, limit: int) -> List[str]:
    """The lines of a failed target's output worth showing under its failure line: not blank, not the summary again, at most `limit` (with a note about the rest)."""
    lines = [line.rstrip() for line in error.replace("\r\n", "\n").split("\n") if line.strip()]
    lines = [line for line in lines if line.strip() != summary.strip()]
    if len(lines) <= limit:
        return lines
    return lines[:limit] + [f"... (+{len(lines) - limit})"]
