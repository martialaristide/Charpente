"""charpente.ui.term: what a terminal can show, colour conversion and text measurement. Every case is a pure function of its arguments: no terminal is needed."""
import io
import os

import pytest

from charpente.ui import term
from charpente.ui.term import BASIC, EXTENDED, NONE, RESET, TRUE, Caps

RED, GREEN = (255, 0, 0), (0, 200, 0)


class Stream(io.StringIO):
    def __init__(self, tty=True, encoding="utf-8"):
        super().__init__()
        self._tty = tty
        self._encoding = encoding

    def isatty(self):
        if self.closed:
            raise ValueError("I/O operation on closed file")            # what a real closed file does
        return self._tty

    @property
    def encoding(self):
        return self._encoding


def caps(env=None, *, tty=True, platform="linux", vt=True, encoding="utf-8", size=(100, 30)):
    return term.detect(env or {}, Stream(tty, encoding), platform=platform, enable_vt=lambda: vt, size=lambda: size)


# ---------------------------------------------------------------------- colour on or off
def test_a_terminal_gets_colour_and_a_pipe_does_not():
    assert caps({"TERM": "xterm"}).color == BASIC
    assert caps({}, tty=False).color == NONE and not caps({}, tty=False).tty


def test_no_color_beats_everything():
    for env in ({"NO_COLOR": "1"}, {"NO_COLOR": "x", "FORCE_COLOR": "3"}, {"NO_COLOR": "1", "CHARPENTE_COLOR": "always"}, {"NO_COLOR": "1", "COLORTERM": "truecolor"}):
        assert caps(env).color == NONE and caps(env, tty=False).color == NONE
    assert caps({"NO_COLOR": ""}).colored                                          # an empty NO_COLOR does not count


def test_charpente_color_never_and_always():
    assert caps({"CHARPENTE_COLOR": "never", "FORCE_COLOR": "1"}).color == NONE
    assert caps({"CHARPENTE_COLOR": "ALWAYS"}, tty=False).color == BASIC             # forced even into a file; case does not matter
    assert caps({"CHARPENTE_COLOR": "sometimes"}).colored and not caps({"CHARPENTE_COLOR": "sometimes"}, tty=False).colored     # unknown value: auto


@pytest.mark.parametrize("value,expected", [("1", BASIC), ("2", EXTENDED), ("3", TRUE), ("true", BASIC), ("yes", BASIC)])
def test_force_color_levels(value, expected):
    if value in ("1", "2", "3"):
        assert caps({"FORCE_COLOR": value}, tty=False).color == expected
    else:
        assert caps({"FORCE_COLOR": value}, tty=False).colored                        # "on": whatever the terminal supports
    assert caps({"FORCE_COLOR": "0"}, tty=False).color == NONE                        # 0 does not force


def test_a_dumb_terminal_gets_no_colour_unless_forced():
    assert caps({"TERM": "dumb"}).color == NONE
    assert caps({"TERM": "dumb", "FORCE_COLOR": "1"}).colored


# ---------------------------------------------------------------------- colour depth
@pytest.mark.parametrize("env,expected", [
    ({"COLORTERM": "truecolor"}, TRUE), ({"COLORTERM": "24bit"}, TRUE), ({"WT_SESSION": "abc"}, TRUE), ({"TERM_PROGRAM": "vscode"}, TRUE),
    ({"TERM_PROGRAM": "iTerm.app"}, TRUE), ({"TERM": "xterm-256color"}, EXTENDED), ({"TERM": "screen-256color"}, EXTENDED), ({"TERM": "xterm"}, BASIC), ({}, BASIC)])
def test_colour_depth_from_the_environment(env, expected):
    assert caps(env).color == expected


def test_truecolor_beats_a_256_colour_term():
    assert caps({"TERM": "xterm-256color", "COLORTERM": "truecolor"}).color == TRUE


def test_a_forced_level_beats_detection():
    assert caps({"COLORTERM": "truecolor", "FORCE_COLOR": "1"}).color == BASIC


def test_windows_needs_ansi_processing_to_be_switched_on():
    assert caps({}, platform="win32", vt=True).color == TRUE                          # Windows 10 console with VT: 24-bit colour
    assert caps({}, platform="win32", vt=False).color == NONE                         # cannot: plain text
    assert caps({"FORCE_COLOR": "3"}, platform="win32", vt=False).color == NONE       # even when forced: it would print raw escape codes
    assert caps({"FORCE_COLOR": "3"}, platform="win32", vt=False, tty=False).color == TRUE    # into a file the codes are fine


def test_ansi_switch_is_only_attempted_on_a_windows_terminal():
    calls = []

    def vt():
        calls.append(1)
        return True

    term.detect({}, Stream(True), platform="linux", enable_vt=vt, size=lambda: (80, 24))
    term.detect({}, Stream(False), platform="win32", enable_vt=vt, size=lambda: (80, 24))
    assert calls == []
    term.detect({}, Stream(True), platform="win32", enable_vt=vt, size=lambda: (80, 24))
    assert calls == [1]


# ---------------------------------------------------------------------- unicode, width, CI
def test_unicode_needs_an_encoding_that_can_write_the_drawing_characters():
    assert caps().unicode
    for encoding in ("ascii", "cp1252", "latin-1"):
        assert not caps(encoding=encoding).unicode
    assert not caps({"CHARPENTE_ASCII": "1"}).unicode and not caps({"CHARPENTE_ASCII": "true"}).unicode
    assert caps({"CHARPENTE_ASCII": "0"}).unicode and caps({"CHARPENTE_ASCII": ""}).unicode


def test_an_unknown_or_missing_encoding_counts_as_ascii():
    class Odd(Stream):
        @property
        def encoding(self):
            return "no-such-codec"

    class NoEncoding(io.StringIO):
        encoding = None

    assert not term.detect({}, Odd(), platform="linux", size=lambda: (80, 24)).unicode
    assert not term.detect({}, NoEncoding(), platform="linux", size=lambda: (80, 24)).unicode
    assert not term.can_encode(object())                                              # not even a stream


@pytest.mark.parametrize("size,expected", [((100, 30), 100), ((0, 0), 80), ((-5, 10), 80), ((1, 10), 1), ((99999, 10), 1000)])
def test_width_is_sane_whatever_the_terminal_says(size, expected):
    assert caps(size=size).width == expected


def test_a_failing_size_probe_gives_the_default_width():
    def boom():
        raise OSError("no terminal")

    assert term.detect({}, Stream(), platform="linux", size=boom).width == 80


def test_ci_is_recognised():
    for name in term.CI_VARIABLES:
        assert caps({name: "1"}).ci
    assert not caps({}).ci and not caps({"CI": ""}).ci


def test_a_closed_stream_and_a_stream_without_isatty_are_not_terminals():
    closed = Stream()
    closed.close()
    assert not term.detect({}, closed, platform="linux", size=lambda: (80, 24)).tty

    class Bare:
        encoding = "utf-8"

    assert not term.detect({}, Bare(), platform="linux", size=lambda: (80, 24)).tty     # type: ignore[arg-type]


def test_detect_never_raises_even_for_nonsense():
    class Hostile:
        def isatty(self):
            raise RuntimeError("boom")

        @property
        def encoding(self):
            raise RuntimeError("boom")

    assert isinstance(term.detect({}, Hostile(), platform="linux"), Caps)             # type: ignore[arg-type]
    assert term.detect(None, None) is not None                                        # the real process environment and stdout


def test_a_default_caps_is_the_plainest_safe_picture():
    plain = Caps()
    assert (plain.tty, plain.color, plain.width) == (False, NONE, 80) and not plain.colored


# ---------------------------------------------------------------------- colour conversion
def test_rgb_to_256():
    assert term.rgb_to_256((255, 0, 0)) == 196
    assert term.rgb_to_256((0, 0, 0)) == 16 and term.rgb_to_256((255, 255, 255)) == 231
    assert 232 <= term.rgb_to_256((128, 128, 128)) <= 255 and 232 <= term.rgb_to_256((10, 10, 10)) <= 255 and term.rgb_to_256((248, 248, 248)) == 255
    assert term.rgb_to_256((0, 255, 0)) == 46 and term.rgb_to_256((0, 0, 255)) == 21
    assert term.rgb_to_256((999, -5, 0)) == 196                                        # out-of-range values are clamped


def test_the_grey_ramp_is_monotonic():
    values = [term.rgb_to_256((v, v, v)) for v in range(8, 249)]
    assert values == sorted(values) and values[0] == 232 and values[-1] == 255


def test_rgb_to_16():
    assert term.rgb_to_16((0, 0, 0)) == 0 and term.rgb_to_16((255, 255, 255)) == 15
    assert term.rgb_to_16((250, 60, 60)) in (1, 9) and term.rgb_to_16((30, 30, 200)) == 4


def test_sgr_for_each_depth():
    assert term.sgr(Caps(color=TRUE), RED, bold=True) == "\x1b[1;38;2;255;0;0m"
    assert term.sgr(Caps(color=EXTENDED), RED) == "\x1b[38;5;196m"
    assert term.sgr(Caps(color=BASIC), RED) in ("\x1b[31m", "\x1b[91m")
    assert term.sgr(Caps(color=BASIC), (0, 0, 0), dim=True) == "\x1b[2;30m"
    assert term.sgr(Caps(color=TRUE), RED, bg=GREEN) == "\x1b[38;2;255;0;0;48;2;0;200;0m"
    assert term.sgr(Caps(color=BASIC), (255, 255, 255), bg=(0, 0, 0)) == "\x1b[97;40m"
    assert term.sgr(Caps(color=NONE), RED, bold=True) == "" and term.sgr(Caps(color=TRUE)) == ""


def test_paint_never_adds_escape_codes_without_colour():
    assert term.paint(Caps(color=NONE), "hi", RED, bold=True) == "hi"
    assert term.paint(Caps(color=TRUE), "hi", RED) == "\x1b[38;2;255;0;0mhi" + RESET
    assert term.paint(Caps(color=TRUE), "", RED) == "" and term.paint(Caps(color=TRUE), "x") == "x"


# ---------------------------------------------------------------------- measuring text
def test_visible_length_pad_and_clip():
    coloured = f"\x1b[31mabc{RESET}"
    assert term.visible_len(coloured) == 3 and term.visible_len("日本") == 4 and term.visible_len("e\u0301") == 1
    assert term.visible_len(term.pad(coloured, 6)) == 6
    cut = term.clip(f"\x1b[31m{'x' * 30}{RESET} tail", 10, "...")
    assert term.visible_len(cut) == 10 and cut.endswith("..." + RESET)
    assert term.clip("short", 10) == "short" and term.clip("anything", 0) == "" and term.clip("anything", -3) == ""
    assert term.strip_ansi(coloured) == "abc"


def test_truncate_middle_keeps_both_ends():
    path = "C:\\Users\\someone\\Documents\\projects\\game\\engine"
    short = term.truncate_middle(path, 30)
    assert len(short) == 30 and short.startswith("C:\\Users") and short.endswith("engine") and "..." in short
    assert term.truncate_middle("abc", 30) == "abc" and len(term.truncate_middle("abcdefghij", 3)) <= 3


def test_the_windows_switch_is_a_no_op_elsewhere():
    if os.name != "nt":
        assert term.enable_windows_vt() is False
    else:
        assert term.enable_windows_vt() in (True, False)                              # never raises, whether or not there is a console


# ---------------------------------------------------------------------- which symbols the font probably has
@pytest.mark.parametrize("env,platform,expected", [
    ({}, "linux", True), ({}, "darwin", True), ({}, "win32", False),                                   # a classic Windows console: no TERM, no WT_SESSION
    ({"WT_SESSION": "x"}, "win32", True), ({"TERM_PROGRAM": "vscode"}, "win32", True), ({"TERM": "xterm-256color"}, "win32", True),
    ({"ConEmuANSI": "ON"}, "win32", True), ({"CHARPENTE_SYMBOLS": "modern"}, "win32", True), ({"CHARPENTE_SYMBOLS": "safe"}, "linux", False),
    ({"CHARPENTE_SYMBOLS": "SAFE"}, "linux", False), ({"CHARPENTE_SYMBOLS": "nonsense"}, "win32", False), ({"CHARPENTE_SYMBOLS": "nonsense"}, "linux", True)])
def test_the_symbol_set_follows_the_terminal_and_can_be_overridden(env, platform, expected):
    assert caps(env, platform=platform).modern is expected


def test_the_default_caps_assume_a_modern_font():
    assert Caps().modern is True
