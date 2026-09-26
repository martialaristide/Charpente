"""`python -m charpente.ui`: the demonstration of the banner and of a build session."""
import io
import subprocess
import sys

import pytest

from charpente.ui import banner, demo
from charpente.ui.term import strip_ansi, visible_len


class Out(io.StringIO):
    encoding = "utf-8"


def show(*args, env=None):
    out = Out()
    assert demo.run(["--delay", "0", *args], out=out, env=env if env is not None else {}) == 0
    return out.getvalue()


def screen(text):
    return [line.split("\r")[-1] for line in text.split("\n")]


def test_the_default_demo_matches_the_design():
    text = show("--color", "never", "--lang", "fr", "--width", "100", "--symbols", "modern")
    lines = screen(text)
    assert lines[0].startswith("╔") and "██████╗" in text and "Système de build C/C++ multiplateforme" in text
    assert "  ✔ moteur        build/Debug/moteur/libmoteur.a  2,4 s" in lines
    assert any(x.startswith("  ◆ shaders") for x in lines) and "  ▲ app : 2 avertissements, voir charpente build -v" in lines
    assert any(x.startswith("  ✘ tests_moteur") for x in lines) and any("38/40" in x for x in lines)
    assert any("3 réussies, 1 échec" in x for x in lines) and any("charpente why tests_moteur" in x for x in lines)


def test_a_clean_build_can_be_shown():
    text = show("--color", "never", "--lang", "en", "--ok", "--width", "100")
    assert "38/38" in text and "4 succeeded" in text and "next" not in text and "failed" not in text.split("Result")[-1]


def test_the_language_switch():
    assert "Multi-platform C/C++ Build System" in show("--lang", "en", "--color", "never") and "multiplateforme" in show("--lang", "fr", "--color", "never")


@pytest.mark.parametrize("theme", sorted(banner.THEMES))
def test_every_theme_can_be_shown_in_colour(theme):
    text = show("--theme", theme, "--color", "always", "--width", "100", "--lang", "en", env={"COLORTERM": "truecolor"})
    t = banner.THEMES[theme]
    assert f"38;2;{t.shadow[0]};{t.shadow[1]};{t.shadow[2]}" in text and "\x1b[" in text
    assert "\r" not in text                                                                 # not a terminal: no transient bar


def test_no_colour_means_no_escape_sequence_and_ascii_means_ascii():
    assert "\x1b" not in show("--color", "never")
    text = show("--color", "never", "--ascii", "--width", "100", "--lang", "fr")
    assert all(ord(c) < 128 for c in text) and "[x]" in text and "+=" in text


def test_a_narrow_terminal_gets_the_compact_banner_and_no_line_overflows():
    text = show("--color", "never", "--width", "50")
    assert "C H A R P E N T E" in text and "██████╗" not in text
    assert all(visible_len(strip_ansi(line)) <= 50 for line in screen(text))


def test_the_banner_can_be_left_out():
    text = show("--no-banner", "--color", "never", "--symbols", "modern")
    assert "╔" not in text and "▸ " in text


def test_the_theme_can_come_from_the_environment():
    text = show("--color", "always", env={"CHARPENTE_THEME": "neon", "COLORTERM": "truecolor"})
    assert "38;2;255;190;225" in text                                                       # neon's light shadow too
    assert "38;2;255;45;150" in text
    basic = show("--color", "always", env={})                                              # no colour depth known: the 16 basic colours
    assert "\x1b[" in basic and "38;2;" not in basic and "38;5;" not in basic


def test_bad_arguments_are_reported_by_argparse():
    with pytest.raises(SystemExit):
        demo.run(["--theme", "nope"], out=Out(), env={})
    assert "╔" in show("--width", "0", "--color", "never")                                # a nonsense width falls back to the terminal's own


def test_it_runs_as_a_module():
    result = subprocess.run([sys.executable, "-m", "charpente.ui", "--delay", "0", "--color", "never", "--width", "100", "--lang", "en"], capture_output=True, encoding="utf-8",
                            errors="replace", timeout=120, stdin=subprocess.DEVNULL, env=None)
    assert result.returncode == 0 and "Result" in result.stdout and "tests_moteur" in result.stdout


def test_the_safe_symbols_of_a_classic_windows_console_can_be_shown():
    text = show("--color", "never", "--lang", "fr", "--width", "100", "--symbols", "safe")
    assert "  √ moteur" in text and "  ♦ shaders" in text and "  × tests_moteur" in text and "  ▲ app" in text and "  ► Construction" in text
    assert "✔" not in text and "✘" not in text and "◆" not in text and "▸" not in text and "╭" not in text and "▬" in text
    assert "┌─ Résultat" in text
