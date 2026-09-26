"""What a terminal can show, and the low-level pieces to draw for it: capability detection, colour conversion, text measurement.

`detect` is a pure function of the environment, the output stream and a few probes passed in, so every case (a pipe, `NO_COLOR`, a dumb terminal, Windows without
ANSI support...) is tested without a terminal. Nothing in this module ever raises because of the terminal: a stream that is closed, has no encoding, or reports a nonsense
width yields a plainer result (no colour, ASCII, 80 columns), never an exception -- a display problem must degrade the picture, not fail a build.

Environment, in order of authority:

* `NO_COLOR` (any non-empty value) and `CHARPENTE_COLOR=never` switch colour off, whatever else is set;
* `FORCE_COLOR` (1, 2, 3 = 16, 256, 24-bit; anything else non-empty = on; `0` = ignored) and `CHARPENTE_COLOR=always` switch it on even when the output is not a terminal;
* otherwise colour needs a terminal and `TERM` other than `dumb`;
* depth: 24-bit for `COLORTERM=truecolor|24bit`, Windows Terminal (`WT_SESSION`), VS Code, iTerm and a Windows 10 console with ANSI processing on; 256 colours when
  `TERM` contains `256`; else the 16 basic colours;
* `CHARPENTE_ASCII=1` (or an encoding that cannot write the drawing characters) selects the ASCII look.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from typing import Callable, List, Mapping, Optional, Sequence, TextIO, Tuple

NONE, BASIC, EXTENDED, TRUE = "none", "16", "256", "truecolor"
DEFAULT_WIDTH = 80
MAX_WIDTH = 1000
RESET = "\x1b[0m"
CI_VARIABLES = ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "TF_BUILD", "JENKINS_URL", "TEAMCITY_VERSION")
#: every character the banner and the build lines can use; a stream that cannot write all of them gets the ASCII look
UNICODE_PROBE = "╔═╗║╚╝╭─╮│╰╯━▸✔✘◆▲█·"
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_TOKEN = re.compile(r"(\x1b\[[0-9;?]*[A-Za-z])|(.)", re.DOTALL)
RGB = Tuple[int, int, int]


# ---------------------------------------------------------------------- measuring text
def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def char_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def visible_len(text: str) -> int:
    """Columns the text takes on screen (colour codes take none; wide characters take two)."""
    return sum(char_width(c) for c in strip_ansi(text))


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - visible_len(text))


def clip(text: str, width: int, ellipsis: str = "") -> str:
    """Cut `text` to at most `width` columns, keeping colour codes intact (and resetting them if the cut falls inside a coloured run)."""
    if width <= 0:
        return ""
    if visible_len(text) <= width:
        return text
    room = width - visible_len(ellipsis)
    out: List[str] = []
    used = 0
    coloured = False
    for match in _TOKEN.finditer(text):
        code, char = match.group(1), match.group(2)
        if code:
            out.append(code)
            coloured = code != RESET
            continue
        w = char_width(char)
        if used + w > room:
            break
        out.append(char)
        used += w
    out.append(ellipsis)
    if coloured:
        out.append(RESET)
    return "".join(out)


def truncate_middle(text: str, width: int, ellipsis: str = "...") -> str:
    """A long path shortened in the middle: the start and the end are what people recognise. Plain text only."""
    if visible_len(text) <= width:
        return text
    if width <= visible_len(ellipsis) + 2:
        return text[: max(0, width)]
    keep = width - len(ellipsis)
    head = (keep + 1) // 2
    return text[:head] + ellipsis + text[len(text) - (keep - head):]


# ---------------------------------------------------------------------- Windows
def enable_windows_vt() -> bool:
    """Ask the Windows console to understand ANSI sequences (Windows 10 and later), without starting a process. False when it cannot."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        kernel = ctypes.windll.kernel32                     # type: ignore[attr-defined,unused-ignore]   # only exists on Windows
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))    # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        return False


# ---------------------------------------------------------------------- what the terminal can do
@dataclass(frozen=True)
class Caps:
    """The facts a drawing function needs. Every field has a safe default, so a test builds one with only what it cares about."""

    tty: bool = False
    color: str = NONE            # none | 16 | 256 | truecolor
    unicode: bool = True
    width: int = DEFAULT_WIDTH
    ci: bool = False

    @property
    def colored(self) -> bool:
        return self.color != NONE


def _flag(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _width(size: Optional[Callable[[], Tuple[int, int]]]) -> int:
    try:
        columns = (size() if size is not None else shutil.get_terminal_size((DEFAULT_WIDTH, 24)))[0]
        columns = int(columns)
    except Exception:
        return DEFAULT_WIDTH
    if columns <= 0:
        return DEFAULT_WIDTH              # some environments report 0 for "unknown"
    return min(columns, MAX_WIDTH)


def can_encode(stream: Optional[TextIO], text: str = UNICODE_PROBE) -> bool:
    """Whether the stream's encoding can write every character of `text` (an unknown or missing encoding counts as ASCII)."""
    try:
        encoding = getattr(stream, "encoding", None) or "ascii"
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError, TypeError, ValueError):
        return False
    return True


def _is_tty(stream: Optional[TextIO]) -> bool:
    try:
        return bool(stream is not None and stream.isatty())
    except (AttributeError, ValueError, OSError):        # closed stream, no isatty
        return False


def _forced_depth(value: str) -> Optional[str]:
    """What FORCE_COLOR asks for: a depth, or "auto" for "on, whatever the terminal supports"; None when it does not ask for colour."""
    text = value.strip().lower()
    if text in ("", "0", "false", "no", "off"):
        return None
    return {"1": BASIC, "2": EXTENDED, "3": TRUE}.get(text, "auto")


def _depth(env: Mapping[str, str], windows_ansi: bool) -> str:
    if env.get("COLORTERM", "").lower() in ("truecolor", "24bit") or env.get("WT_SESSION") or env.get("TERM_PROGRAM", "") in ("vscode", "iTerm.app") \
            or windows_ansi:
        return TRUE
    if "256" in env.get("TERM", ""):
        return EXTENDED
    return BASIC


def detect(env: Optional[Mapping[str, str]] = None, stream: Optional[TextIO] = None, *, platform: Optional[str] = None,
           enable_vt: Callable[[], bool] = enable_windows_vt, size: Optional[Callable[[], Tuple[int, int]]] = None) -> Caps:
    """The capabilities of `stream` (default: standard output) in `env` (default: the process environment). Never raises."""
    try:
        env = os.environ if env is None else env
        stream = sys.stdout if stream is None else stream
        platform = sys.platform if platform is None else platform
        tty = _is_tty(stream)
        windows = platform == "win32"
        ascii_only = _flag(env.get("CHARPENTE_ASCII"))
        unicode = not ascii_only and can_encode(stream)
        ci = any(env.get(name) for name in CI_VARIABLES)
        mode = env.get("CHARPENTE_COLOR", "auto").strip().lower()
        forced = _forced_depth(env.get("FORCE_COLOR", ""))
        color = NONE
        if not (env.get("NO_COLOR") or mode == "never"):        # the user said no: nothing overrides it
            forced_on = mode == "always" or forced is not None
            windows_ansi = False
            usable = True
            if windows and tty:
                windows_ansi = bool(enable_vt())                # a Windows console needs ANSI processing switched on first
                usable = windows_ansi                            # ...and if it refuses, plain text (even when forced)
            if usable and (tty or forced_on) and (forced_on or env.get("TERM", "") != "dumb"):
                color = forced if forced in (BASIC, EXTENDED, TRUE) else _depth(env, windows_ansi)
        return Caps(tty=tty, color=color, unicode=unicode, width=_width(size), ci=ci)
    except Exception:                                    # whatever went wrong, show the plainest picture rather than fail
        return Caps()


# ---------------------------------------------------------------------- colours
_BASIC_PALETTE: Sequence[RGB] = (
    (0, 0, 0), (205, 49, 49), (13, 188, 121), (229, 229, 16), (36, 114, 200), (188, 63, 188), (17, 168, 205), (229, 229, 229),
    (102, 102, 102), (241, 76, 76), (35, 209, 139), (245, 245, 67), (59, 142, 234), (214, 112, 214), (41, 184, 219), (255, 255, 255))


def clamp(value: int) -> int:
    return max(0, min(255, int(value)))


def rgb_to_256(rgb: RGB) -> int:
    """The nearest xterm 256-colour index: the 6x6x6 cube (16-231) or the grey ramp (232-255) for greys."""
    r, g, b = (clamp(c) for c in rgb)
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + round((r - 8) / 247 * 24)          # 232..255: never 256 because r <= 248 here
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)


def rgb_to_16(rgb: RGB) -> int:
    """The index (0-15) of the nearest of the 16 basic colours."""
    r, g, b = (clamp(c) for c in rgb)
    return min(range(16), key=lambda i: (r - _BASIC_PALETTE[i][0]) ** 2 + (g - _BASIC_PALETTE[i][1]) ** 2 + (b - _BASIC_PALETTE[i][2]) ** 2)


def sgr(caps: Caps, fg: Optional[RGB] = None, *, bold: bool = False, dim: bool = False, bg: Optional[RGB] = None) -> str:
    """The escape sequence that starts a style, for the terminal's colour depth; "" when colour is off."""
    if not caps.colored:
        return ""
    parts: List[str] = []
    if bold:
        parts.append("1")
    if dim:
        parts.append("2")
    for color, base in ((fg, 30), (bg, 40)):
        if color is None:
            continue
        r, g, b = (clamp(c) for c in color)
        if caps.color == TRUE:
            parts.append(f"{base + 8};2;{r};{g};{b}")
        elif caps.color == EXTENDED:
            parts.append(f"{base + 8};5;{rgb_to_256((r, g, b))}")
        else:
            index = rgb_to_16((r, g, b))
            parts.append(str(base + index if index < 8 else base + 60 + index - 8))
    return f"\x1b[{';'.join(parts)}m" if parts else ""


def paint(caps: Caps, text: str, fg: Optional[RGB] = None, *, bold: bool = False, dim: bool = False, bg: Optional[RGB] = None) -> str:
    """`text` in a colour (and weight); unchanged when colour is off or there is nothing to style."""
    start = sgr(caps, fg, bold=bold, dim=dim, bg=bg)
    return f"{start}{text}{RESET}" if start and text else text
