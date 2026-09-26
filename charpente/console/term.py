"""Terminal basics for the console interface, standard library only: what the terminal can do, colours, text measurement, boxes and key input.

Everything that decides something is a pure function of its arguments (`detect`, `clip`, `box`, `decode_*`), so it is tested without a terminal. The parts that
touch the real console (`WindowsKeys`, `PosixKeys`, `enable_windows_vt`) are small and only reached on an interactive terminal; anything unexpected there
makes the interface fall back to plain line input instead of leaving the terminal in a strange state (keys are read one at a time and the terminal mode is
restored after each key, so an interrupted program never leaves a raw terminal behind).
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from typing import Callable, List, Mapping, Optional, Sequence, TextIO

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_TOKEN = re.compile(r"(\x1b\[[0-9;?]*[A-Za-z])|(.)", re.DOTALL)


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
            coloured = code != "\x1b[0m"
            continue
        w = char_width(char)
        if used + w > room:
            break
        out.append(char)
        used += w
    out.append(ellipsis)
    if coloured:
        out.append("\x1b[0m")
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


# ---------------------------------------------------------------------- what the terminal can do
@dataclass(frozen=True)
class Caps:
    interactive: bool        # standard input and output are both terminals
    ansi: bool               # cursor movement and screen clearing work
    color: bool
    unicode: bool
    width: int
    height: int


@dataclass(frozen=True)
class Glyphs:
    tl: str
    tr: str
    bl: str
    br: str
    h: str
    v: str
    marker: str              # the selected menu row
    dot: str
    ellipsis: str
    up_down: str
    brand: str


UNICODE_GLYPHS = Glyphs("┌", "┐", "└", "┘", "─", "│", "►", "●", "…", "↑↓", "■")
ASCII_GLYPHS = Glyphs("+", "+", "+", "+", "-", "|", ">", "*", "...", "up/down", "#")
_PROBE = "┌┐└┘─│►●…↑↓■·"


def glyphs_for(caps: Caps) -> Glyphs:
    return UNICODE_GLYPHS if caps.unicode else ASCII_GLYPHS


def _can_encode(stream: Optional[TextIO], text: str) -> bool:
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def enable_windows_vt() -> bool:
    """Ask the Windows console to understand ANSI sequences (Windows 10 and later). False when it cannot."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        kernel = ctypes.windll.kernel32                     # type: ignore[attr-defined,unused-ignore]
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))    # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        return False


def detect(stdin: Optional[TextIO] = None, stdout: Optional[TextIO] = None, env: Optional[Mapping[str, str]] = None, *,
           enable_vt: Callable[[], bool] = enable_windows_vt, size: Optional[Callable[[], os.terminal_size]] = None) -> Caps:
    """What this terminal supports. `CHARPENTE_CONSOLE=plain` forces plain line input; `NO_COLOR` and `TERM=dumb` are respected."""
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    env = os.environ if env is None else env
    try:
        tty = bool(stdin.isatty() and stdout.isatty())
    except (AttributeError, ValueError):
        tty = False
    plain = env.get("CHARPENTE_CONSOLE", "").strip().lower() == "plain" or env.get("TERM", "") == "dumb"
    ansi = tty and not plain
    if ansi and sys.platform == "win32":
        ansi = enable_vt()
    color = ansi and not env.get("NO_COLOR")
    measure = size or (lambda: shutil.get_terminal_size((80, 24)))
    columns, lines = measure()
    return Caps(interactive=tty and not plain, ansi=ansi, color=color, unicode=_can_encode(stdout, _PROBE), width=max(20, columns), height=max(8, lines))


# ---------------------------------------------------------------------- colours
class Style:
    """Semantic styles. With colour off every method returns its text unchanged, so callers never test for colour."""

    def __init__(self, color: bool) -> None:
        self.color = color

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.color and text else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def muted(self, text: str) -> str:
        return self._wrap("2", text)

    def accent(self, text: str) -> str:
        return self._wrap("1;36", text)

    def ok(self, text: str) -> str:
        return self._wrap("32", text)

    def warn(self, text: str) -> str:
        return self._wrap("33", text)

    def err(self, text: str) -> str:
        return self._wrap("31", text)

    def selected(self, text: str) -> str:
        return self._wrap("7", text)


# ---------------------------------------------------------------------- boxes
def box(lines: Sequence[str], width: int, glyphs: Glyphs, title: str = "", style: Optional[Style] = None) -> List[str]:
    """Lines framed to exactly `width` columns; an overlong line is clipped, never allowed to break the frame."""
    style = style or Style(False)
    inner = max(4, width - 4)
    label = f" {title} " if title else ""
    top = glyphs.tl + glyphs.h + style.bold(clip(label, inner)) + glyphs.h * max(0, inner - visible_len(clip(label, inner)) + 1) + glyphs.tr
    out = [top]
    for line in lines:
        out.append(f"{glyphs.v} {pad(clip(line, inner, glyphs.ellipsis), inner)} {glyphs.v}")
    out.append(glyphs.bl + glyphs.h * (inner + 2) + glyphs.br)
    return out


# ---------------------------------------------------------------------- key input
WINDOWS_SECOND = {"H": "up", "P": "down", "K": "left", "M": "right", "G": "home", "O": "end", "I": "pgup", "Q": "pgdn", "S": "delete"}
CSI_FINAL = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end"}
CSI_TILDE = {"1": "home", "7": "home", "4": "end", "8": "end", "5": "pgup", "6": "pgdn", "3": "delete"}
SIMPLE = {"\r": "enter", "\n": "enter", "\x1b": "esc", "\x08": "backspace", "\x7f": "backspace", "\t": "tab", "\x03": "ctrl-c", "\x04": "ctrl-d"}


def decode_windows(first: str, more: Callable[[], str]) -> str:
    """Windows console: arrows and function keys arrive as a prefix character (NUL or 0xE0) followed by a code."""
    if first in ("\x00", "\xe0"):
        return WINDOWS_SECOND.get(more(), "unknown")
    return SIMPLE.get(first, first)


def decode_posix(first: str, more: Callable[[], str]) -> str:
    """Terminals send `ESC [ A` for up, `ESC [ 5 ~` for page up, `ESC O H` for home. `more()` returns "" when nothing else is waiting (a lone Esc)."""
    if first != "\x1b":
        return SIMPLE.get(first, first)
    second = more()
    if second == "":
        return "esc"
    if second not in ("[", "O"):
        return "esc"
    digits = ""
    while True:
        char = more()
        if char == "":
            return "unknown"
        if char.isdigit() or char == ";":
            digits += char
            continue
        if char == "~":
            return CSI_TILDE.get(digits.split(";")[0], "unknown")
        return CSI_FINAL.get(char, "unknown")


class Keys:
    """Reads one key at a time and returns a token: a printable character, or one of up, down, left, right, enter, esc, backspace, tab, home, end, pgup, pgdn, delete, ctrl-c."""

    def read(self) -> str:
        raise NotImplementedError


class WindowsKeys(Keys):
    def read(self) -> str:
        import msvcrt  # only importable on Windows

        first = msvcrt.getwch()                              # type: ignore[attr-defined,unused-ignore]
        return decode_windows(first, lambda: msvcrt.getwch())   # type: ignore[attr-defined,unused-ignore]


class PosixKeys(Keys):
    def read(self) -> str:
        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)                        # type: ignore[attr-defined,unused-ignore]
        try:
            tty.setcbreak(fd)                                # type: ignore[attr-defined,unused-ignore]

            def one(timeout: Optional[float]) -> str:
                if timeout is not None and not select.select([fd], [], [], timeout)[0]:
                    return ""
                data = os.read(fd, 1)
                if not data:
                    raise EOFError
                lead = data[0]
                need = 3 if lead >= 0xF0 else 2 if lead >= 0xE0 else 1 if lead >= 0xC0 else 0
                while need:
                    data += os.read(fd, 1)
                    need -= 1
                return data.decode("utf-8", "replace")

            return decode_posix(one(None), lambda: one(0.05))
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)  # type: ignore[attr-defined,unused-ignore]


def native_keys() -> Optional[Keys]:
    """The key reader for this system, or None when there is none (line input is used then)."""
    if sys.platform == "win32":
        try:
            import msvcrt  # noqa: F401

            return WindowsKeys()
        except ImportError:
            return None
    try:
        import termios  # noqa: F401
        import tty  # noqa: F401

        return PosixKeys()
    except ImportError:
        return None
