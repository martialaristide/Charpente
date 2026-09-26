"""The look of the lines a build prints: one method per kind of line. Pure: (data, terminal capabilities, theme) in, text out.

Nothing here writes to the screen or reads the terminal; `StyledRenderer` (render.py) decides *when* to print each line. Every line is clipped to the terminal width (with an
ellipsis), so a long path or message can never wrap and break the layout, and every symbol has an ASCII form for terminals that cannot draw:

    ▸ stage title          ✔ target built          ◆ served by the cache       ▲ warning       ✘ failure
    [ok]/[=]/[!]/[x] and > in ASCII;  ━ and ─ in the progress bar become = and -;  the result box is drawn with + - | instead of ╭ ─ ╮ │ ╰ ╯
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .banner import THEMES, Theme, fold_ascii
from .term import RGB, Caps, clip, pad, paint, visible_len

OK: RGB = (72, 200, 120)
WARN: RGB = (240, 196, 64)
ERR: RGB = (240, 84, 84)
MUTED: RGB = (140, 140, 150)
FAINT: RGB = (105, 105, 115)
TEXT: RGB = (235, 235, 240)
DEFAULT_INDENT = 2
MIN_BAR = 8
MAX_BAR = 30


@dataclass(frozen=True)
class Symbols:
    stage: str
    ok: str
    cached: str
    warn: str
    fail: str
    sep: str
    bar_on: str
    bar_off: str
    ellipsis: str
    box: Tuple[str, str, str, str, str, str]      # top-left, top-right, bottom-left, bottom-right, horizontal, vertical


UNICODE_SYMBOLS = Symbols("▸", "✔", "◆", "▲", "✘", "│", "━", "─", "…", ("╭", "╮", "╰", "╯", "─", "│"))
ASCII_SYMBOLS = Symbols(">", "[ok]", "[=]", "[!]", "[x]", "|", "=", "-", "...", ("+", "+", "+", "+", "-", "|"))


def symbols_for(caps: Caps) -> Symbols:
    return UNICODE_SYMBOLS if caps.unicode else ASCII_SYMBOLS


def format_duration(seconds: float, lang: Optional[str] = None) -> str:
    """`2.4 s` (`2,4 s` in French), `0.08 s` below a tenth, `1 min 05 s` from a minute. Negative or absurd values are shown as 0."""
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds != seconds or seconds < 0:                # NaN or negative
        seconds = 0.0
    if seconds >= 60:
        minutes, rest = divmod(int(round(seconds)), 60)
        return f"{minutes} min {rest:02d} s"
    text = f"{seconds:.2f}" if 0 < seconds < 0.1 else f"{seconds:.1f}"
    return text.replace(".", ",") + " s" if lang == "fr" else text + " s"


class Style:
    """Formats the lines of a build for one terminal (`caps`), one theme and one language."""

    def __init__(self, caps: Caps, theme: Optional[Theme] = None, lang: Optional[str] = None, indent: int = DEFAULT_INDENT) -> None:
        self.caps = caps
        self.theme = theme or THEMES["bois"]
        self.lang = lang
        self.indent = " " * max(0, indent)
        self.sym = symbols_for(caps)

    # ------------------------------------------------------------ helpers
    def _fit(self, line: str) -> str:
        """The line made to fit: clipped to the terminal width, and in ASCII when the terminal cannot show more."""
        if not self.caps.unicode:
            line = fold_ascii(line)
        return clip(line, self.caps.width, self.sym.ellipsis)

    def _symbol(self, text: str, color: RGB, bold: bool = True) -> str:
        return paint(self.caps, pad(text, 4 if not self.caps.unicode else 1), color, bold=bold)

    def duration(self, seconds: float) -> str:
        return format_duration(seconds, self.lang)

    # ------------------------------------------------------------ lines
    def stage(self, title: str) -> str:
        """`  ▸ Construction`: the start of a phase."""
        return self._fit(f"{self.indent}{paint(self.caps, self.sym.stage, self.theme.frame)} {paint(self.caps, title, TEXT, bold=True)}")

    def context(self, pairs: Sequence[Tuple[str, str]]) -> str:
        """`  espace Demo │ config Debug │ ...`: labels grey, values bold, separated by a grey bar. Pairs with an empty value are left out."""
        parts = [f"{paint(self.caps, label, MUTED)} {paint(self.caps, value, TEXT, bold=True)}" for label, value in pairs if value]
        separator = f" {paint(self.caps, self.sym.sep, MUTED)} "
        return self._fit(self.indent + separator.join(parts))

    def target_ok(self, name: str, output: str = "", seconds: Optional[float] = None, name_width: int = 0) -> str:
        """`  ✔ moteur          build/Debug/moteur/libmoteur.a  2.4 s`"""
        return self._target(self.sym.ok, OK, name, output, seconds, name_width)

    def target_cached(self, name: str, note: str, name_width: int = 0) -> str:
        """`  ◆ shaders         up to date, served by the cache`"""
        return self._target(self.sym.cached, self.theme.frame, name, note, None, name_width)

    def _target(self, symbol: str, color: RGB, name: str, detail: str, seconds: Optional[float], name_width: int) -> str:
        head = f"{self.indent}{self._symbol(symbol, color)} {paint(self.caps, pad(name, name_width), TEXT, bold=True)}"
        tail = f"  {paint(self.caps, detail, MUTED)}" if detail else ""
        if seconds is not None:
            tail += f"  {paint(self.caps, self.duration(seconds), FAINT)}"
        return self._fit(head + tail)

    def warning(self, text: str) -> str:
        """`  ▲ app : 2 warnings, see charpente build -v`"""
        return self._fit(f"{self.indent}{self._symbol(self.sym.warn, WARN)} {paint(self.caps, text, WARN)}")

    def target_failed(self, name: str, message: str, name_width: int = 0) -> str:
        """`  ✘ tests_moteur    link failed`: the name and the message in red."""
        head = f"{self.indent}{self._symbol(self.sym.fail, ERR)} {paint(self.caps, pad(name, name_width), ERR, bold=True)}"
        return self._fit(head + (f"  {paint(self.caps, message, ERR)}" if message else ""))

    def note(self, text: str) -> str:
        """A muted line at the margin (a hint)."""
        return self._fit(f"{self.indent}{paint(self.caps, text, MUTED)}")

    def detail(self, text: str) -> str:
        """An indented, dimmed line under a failure (a line of compiler output)."""
        return self._fit(f"{self.indent}    {paint(self.caps, text, MUTED)}")

    def progress(self, done: int, total: int, width: Optional[int] = None) -> str:
        """`  ━━━━━━━━━━━━──── 38/40`: the bar is bounded (never wider than the terminal, never more than full, never negative)."""
        try:
            total = max(0, int(total))
            done = min(max(0, int(done)), total) if total else 0
        except (TypeError, ValueError):
            total = done = 0
        counter = f"{done}/{total}"
        room = self.caps.width - len(self.indent) - len(counter) - 1
        size = min(MAX_BAR, room) if width is None else min(width, room)
        if size < MIN_BAR:                               # no room for a bar: the counter alone
            return self._fit(self.indent + paint(self.caps, counter, MUTED))
        filled = round(size * done / total) if total else 0
        bar = paint(self.caps, self.sym.bar_on * filled, self.theme.fill(2)) + paint(self.caps, self.sym.bar_off * (size - filled), FAINT)
        return self._fit(f"{self.indent}{bar} {paint(self.caps, counter, MUTED)}")

    def result_box(self, title: str, rows: Sequence[Tuple[str, str]], ok: bool) -> List[str]:
        """The rounded box that ends a session: green when everything succeeded, red otherwise. Returns its lines (all the same width, none wider than the terminal)."""
        color = OK if ok else ERR
        tl, tr, bl, br, horizontal, vertical = self.sym.box
        if not self.caps.unicode:
            title, rows = fold_ascii(title), [(fold_ascii(a), fold_ascii(b)) for a, b in rows]
        label_w = max((visible_len(label) for label, _ in rows), default=0)
        body = [f"  {paint(self.caps, pad(label, label_w), MUTED)}   {paint(self.caps, value, TEXT, bold=True)}" for label, value in rows]
        inner = max([visible_len(line) for line in body] + [visible_len(title) + 4]) + 2
        inner = max(4, min(inner, self.caps.width - len(self.indent) - 2))
        head_text = clip(f" {title} ", inner - 2)
        rest = horizontal * max(0, inner - 1 - visible_len(head_text)) + tr
        lines = [self.indent + paint(self.caps, tl + horizontal, color) + paint(self.caps, head_text, color, bold=True) + paint(self.caps, rest, color)]
        for line in body:
            line = fold_ascii(line) if not self.caps.unicode else line
            lines.append(self.indent + paint(self.caps, vertical, color) + pad(clip(line, inner, self.sym.ellipsis), inner) + paint(self.caps, vertical, color))
        lines.append(self.indent + paint(self.caps, bl + horizontal * inner + br, color))
        return lines
