"""The Charpente banner: a big block logo with a shadow, in a double frame, with the subtitle and the version.

The look is drawn from a font defined here (`FONT`): six rows per letter, full blocks (`█`) form the letter and box-drawing lines (`╔ ╗ ╚ ╝ ║ ═`) form its shadow. Colour comes
from a theme (`CHARPENTE_THEME`): a vertical gradient over the blocks, a darker colour for the shadow, a contrasting frame, a bold white subtitle and a grey components line.

Every function that decides something is pure: `render_banner` takes the terminal's capabilities and returns a string, `should_show_banner` takes the situation and returns a
boolean. Only `print_banner` writes, once per process, and it can never fail a build: whatever goes wrong while printing is swallowed.

How it adapts (see docs/console.md): the full logo needs 79 columns (inner margin 1) and uses the widest margin, 3, 2 or 1, that fits; a narrower terminal gets a compact
frame; without Unicode (or with `CHARPENTE_ASCII=1`) the logo is drawn with `# = | +`; without colour there is no escape sequence at all.
"""
from __future__ import annotations

import os
import sys
import unicodedata
from dataclasses import dataclass
from typing import Callable, List, Mapping, Optional, Sequence, TextIO, Tuple

from .. import _version
from ..i18n import ui as words
from .term import RGB, Caps, clip, detect, pad, paint, visible_len

# ---------------------------------------------------------------------- the font
#: letter -> six rows, every row of a letter as wide as the letter (a rectangle)
FONT = {
    "C": (" ██████╗", "██╔════╝", "██║     ", "██║     ", "╚██████╗", " ╚═════╝"),
    "H": ("██╗  ██╗", "██║  ██║", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"),
    "A": (" █████╗ ", "██╔══██╗", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"),
    "R": ("██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██║  ██║", "╚═╝  ╚═╝"),
    "P": ("██████╗ ", "██╔══██╗", "██████╔╝", "██╔═══╝ ", "██║     ", "╚═╝     "),
    "E": ("███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"),
    "N": ("███╗   ██╗", "████╗  ██║", "██╔██╗ ██║", "██║╚██╗██║", "██║ ╚████║", "╚═╝  ╚═══╝"),
    "T": ("████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "),
}
WORD = "CHARPENTE"
ROWS = 6
FILL_ROWS = 5           # the rows that contain blocks; the sixth is the bottom of the shadow
FILL = "█"
#: how the drawing is written when the terminal cannot show box-drawing characters
ASCII_MAP = {"█": "#", "═": "=", "║": "|", "╔": "+", "╗": "+", "╚": "+", "╝": "+"}
DOUBLE = ("╔", "═", "╗", "║", "╚", "╝")
PLAIN = ("+", "=", "+", "|", "+", "+")
MARGINS = (3, 2, 1)


def logo_rows() -> List[str]:
    """The six rows of the logo (all the same width)."""
    return ["".join(FONT[letter][row] for letter in WORD) for row in range(ROWS)]


LOGO_WIDTH = len(logo_rows()[0])


# ---------------------------------------------------------------------- themes
@dataclass(frozen=True)
class Theme:
    name: str
    top: RGB                 # colour of the blocks on the first row
    bottom: RGB              # ... and on the last row (a vertical gradient in between)
    shadow: RGB
    frame: RGB
    text: RGB = (255, 255, 255)
    muted: RGB = (140, 140, 150)

    def fill(self, row: int) -> RGB:
        """The colour of the blocks on `row`. The gradient runs over the rows that have blocks (0 to 4: the last row of the font is all shadow), so `bottom` is really used."""
        t = min(max(row, 0), FILL_ROWS - 1) / (FILL_ROWS - 1)
        return tuple(round(a + (b - a) * t) for a, b in zip(self.top, self.bottom))  # type: ignore[return-value]


THEMES = {
    "bois": Theme("bois", (255, 224, 138), (207, 110, 40), (120, 66, 32), (38, 190, 178)),
    "neon": Theme("neon", (255, 45, 150), (255, 45, 150), (255, 190, 225), (38, 190, 178)),
    "foret": Theme("foret", (176, 232, 128), (36, 128, 66), (22, 74, 42), (224, 184, 64)),
    "ocean": Theme("ocean", (150, 214, 255), (34, 96, 208), (16, 44, 108), (255, 156, 56)),
}
DEFAULT_THEME = "bois"


def theme_named(name: Optional[str]) -> Theme:
    """The theme called `name` (case does not matter); the default one for a missing or unknown name."""
    return THEMES.get((name or "").strip().lower(), THEMES[DEFAULT_THEME])


# ---------------------------------------------------------------------- text helpers
def fold_ascii(text: str) -> str:
    """`text` for a terminal that can only write ASCII: accents removed, typographic characters replaced, anything else shown as `?` (never dropped silently)."""
    replaced = text.replace("·", "|").replace("…", "...").replace("—", "-").replace("–", "-").replace("’", "'")
    decomposed = unicodedata.normalize("NFKD", replaced)
    return "".join(c if ord(c) < 128 else "?" for c in decomposed if not unicodedata.combining(c))


def center(text: str, width: int) -> str:
    """`text` centred in `width` columns, clipped when it is too long."""
    text = clip(text, width)
    room = width - visible_len(text)
    left = room // 2
    return " " * left + text + " " * (room - left)


def subtitle(lang: Optional[str], version: str) -> str:
    return words.t("banner.subtitle", lang, version=version)


def components(lang: Optional[str]) -> str:
    return words.t("banner.components", lang)


# ---------------------------------------------------------------------- drawing
def _logo_line(caps: Caps, theme: Theme, row: int, text: str) -> str:
    """One row of the logo, coloured: blocks with the row's gradient colour, everything else (the shadow) in the shadow colour. Runs share one escape sequence."""
    if not caps.unicode:
        text = "".join(ASCII_MAP.get(c, c) for c in text)
    if not caps.colored:
        return text
    fill_char = FILL if caps.unicode else ASCII_MAP[FILL]
    out: List[str] = []
    run = ""
    run_kind = ""
    for char in text:
        if char == " ":
            run += char
            continue
        kind = "fill" if char == fill_char else "shadow"
        if kind != run_kind and run.strip():
            out.append(paint(caps, run, theme.fill(row) if run_kind == "fill" else theme.shadow))
            run = ""
        elif kind != run_kind:
            out.append(run)                              # only spaces so far: no need to colour them
            run = ""
        run_kind = kind
        run += char
    if run:
        out.append(paint(caps, run, theme.fill(row) if run_kind == "fill" else theme.shadow) if run.strip() else run)
    return "".join(out)


def choose_margin(width: int) -> Optional[int]:
    """The widest inner margin (3, 2 or 1 spaces) with which the framed logo fits in `width` columns; None when even the narrowest does not."""
    for margin in MARGINS:
        if LOGO_WIDTH + 2 * margin + 2 <= width:
            return margin
    return None


def render_banner(caps: Caps, theme: Optional[Theme] = None, lang: Optional[str] = None, version: Optional[str] = None) -> str:
    """The banner as text, ready to print (lines joined by newlines, no trailing newline). Pure: the same arguments always give the same string."""
    theme = theme or THEMES[DEFAULT_THEME]
    version = version if version is not None else _version.__version__
    sub, comp = subtitle(lang, version), components(lang)
    if not caps.unicode:
        sub, comp = fold_ascii(sub), fold_ascii(comp)
    margin = choose_margin(caps.width)
    frame = DOUBLE if caps.unicode else PLAIN
    tl, horizontal, tr, vertical, bl, br = frame

    def edge(char: str) -> str:
        return paint(caps, char, theme.frame)

    if margin is None:
        return _compact(caps, theme, frame, sub, version)
    inner = LOGO_WIDTH + 2 * margin
    lines = [edge(tl + horizontal * inner + tr)]

    def row(content: str) -> str:
        return edge(vertical) + content + edge(vertical)

    lines.append(row(" " * inner))
    for index, text in enumerate(logo_rows()):
        lines.append(row(" " * margin + _logo_line(caps, theme, index, text) + " " * margin))
    lines.append(row(" " * inner))
    lines.append(row(paint(caps, center(sub, inner), theme.text, bold=True)))
    lines.append(row(paint(caps, center(comp, inner), theme.muted)))
    lines.append(row(" " * inner))
    lines.append(edge(bl + horizontal * inner + br))
    return "\n".join(lines)


def _compact(caps: Caps, theme: Theme, frame: Sequence[str], sub: str, version: str) -> str:
    """The banner for a terminal too narrow for the logo: the name spaced out and the subtitle, in a frame no wider than the terminal."""
    tl, horizontal, tr, vertical, bl, br = frame
    name = words.t("banner.compact.name", None)
    ellipsis = "…" if caps.unicode else "..."
    need = max(visible_len(name), visible_len(sub)) + 2
    width = min(caps.width, need + 2)
    if width < 8:                                        # too narrow even for a frame: one clipped line
        return clip(f"CHARPENTE v{version}", max(1, caps.width))
    inner = width - 2
    text_width = inner - 2

    def edge(char: str) -> str:
        return paint(caps, char, theme.frame)

    def row(content: str, **style: object) -> str:
        return edge(vertical) + " " + paint(caps, pad(center(clip(content, text_width, ellipsis), text_width), text_width), **style) + " " + edge(vertical)  # type: ignore[arg-type]

    return "\n".join([edge(tl + horizontal * inner + tr), row(name, fg=theme.fill(2), bold=True), row(sub, fg=theme.text, bold=True), edge(bl + horizontal * inner + br)])


# ---------------------------------------------------------------------- when to show it
#: commands that get the banner; None stands for a bare `charpente` (the menu)
BANNER_COMMANDS = ("build", "run", "test", "package", "deploy", "dev", "init", "setup", "studio", "menu", None)


def _flag(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def should_show_banner(command: Optional[str], caps: Caps, *, mode: str = "auto", env: Optional[Mapping[str, str]] = None, shown: bool = False) -> bool:
    """Whether to print the banner: once per process, for the interactive commands, on a terminal, in the human output modes, never in CI, never with CHARPENTE_NO_BANNER."""
    env = os.environ if env is None else env
    if shown or command not in BANNER_COMMANDS:
        return False
    if mode in ("plain", "jsonl") or not caps.tty or caps.ci:
        return False
    return not _flag(env.get("CHARPENTE_NO_BANNER"))


_shown = False


def already_shown() -> bool:
    return _shown


def mark_shown() -> None:
    """Record that the banner was shown (or that the screen has its own): commands run afterwards in this process will not print it again."""
    global _shown
    _shown = True


def reset() -> None:
    """Forget that the banner was shown (for tests)."""
    global _shown
    _shown = False


def print_banner(stream: Optional[TextIO] = None, *, caps: Optional[Caps] = None, env: Optional[Mapping[str, str]] = None, theme: Optional[Theme] = None,
                 lang: Optional[str] = None, version: Optional[str] = None, force: bool = False, write: Optional[Callable[[str], None]] = None) -> bool:
    """Print the banner to `stream` (default: standard output). Returns whether it printed.

    Without `force` it prints only on a terminal and only once per process; with `force` (the demo, tests) it prints anywhere, every time. It never raises.
    """
    global _shown
    try:
        stream = sys.stdout if stream is None else stream
        env = os.environ if env is None else env
        caps = caps or detect(env, stream)
        if not force and (_shown or not caps.tty):
            return False
        theme = theme or theme_named(env.get("CHARPENTE_THEME"))
        text = render_banner(caps, theme, lang, version) + "\n\n"
        (write or stream.write)(text)
        try:
            stream.flush()
        except (AttributeError, OSError, ValueError):
            pass
        _shown = True
        return True
    except Exception:                                    # a picture that cannot be drawn must never stop the command
        return False


def logo_size() -> Tuple[int, int]:
    """(width, height) of the bare logo, for tests and for anyone laying it out."""
    return LOGO_WIDTH, ROWS
