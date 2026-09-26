"""charpente.ui.banner: the font, the themes, the layout at every width, and when the banner is shown. Pure functions: no terminal is needed."""
import io

import pytest

from charpente.ui import banner
from charpente.ui.term import BASIC, EXTENDED, NONE, TRUE, Caps, strip_ansi, visible_len

ALL_DEPTHS = (NONE, BASIC, EXTENDED, TRUE)
DRAWING = set("█╔╗╚╝║═╭╮╰╯─│━")


def caps(color=NONE, width=100, unicode=True, tty=True, ci=False):
    return Caps(tty=tty, color=color, unicode=unicode, width=width, ci=ci)


def lines(text):
    return text.split("\n")


# ---------------------------------------------------------------------- the font
def test_every_letter_is_a_rectangle_of_six_rows():
    assert set(banner.FONT) == set("CHARPENT")
    for letter, rows in banner.FONT.items():
        assert len(rows) == banner.ROWS == 6, letter
        assert len({len(r) for r in rows}) == 1, f"the rows of {letter} have different widths"


def test_the_logo_rows_have_the_same_width():
    rows = banner.logo_rows()
    assert len(rows) == 6 and len({len(r) for r in rows}) == 1 and len(rows[0]) == banner.LOGO_WIDTH == 75
    assert banner.logo_size() == (75, 6)


def test_the_font_uses_only_blocks_shadow_lines_and_spaces():
    assert set("".join(banner.logo_rows())) <= set("█╔╗╚╝║═ ")


def test_the_word_is_charpente():
    assert banner.WORD == "CHARPENTE"
    assert banner.logo_rows()[0].startswith(" ██████╗██╗  ██╗") and banner.logo_rows()[2].endswith("█████╗  ")


# ---------------------------------------------------------------------- layout at every width
@pytest.mark.parametrize("depth", ALL_DEPTHS)
@pytest.mark.parametrize("theme", sorted(banner.THEMES))
@pytest.mark.parametrize("lang", ["en", "fr"])
def test_all_lines_of_the_banner_have_the_same_visible_width(depth, theme, lang):
    for width in (120, 83, 80, 79, 60, 40, 20):
        text = banner.render_banner(caps(depth, width), banner.THEMES[theme], lang, "0.13.0")
        widths = {visible_len(line) for line in lines(text)}
        assert len(widths) == 1, (width, widths)
        assert widths.pop() <= max(1, width - 1) or width < 8                              # the last column stays free


def test_the_full_logo_fits_in_80_columns_and_uses_the_widest_margin_that_fits():
    assert banner.choose_margin(120) == 3 and banner.choose_margin(83) == 3
    assert banner.choose_margin(82) == 2 and banner.choose_margin(81) == 2
    assert banner.choose_margin(80) == 1 and banner.choose_margin(79) == 1
    assert banner.choose_margin(78) is None and banner.choose_margin(0) is None
    at_80 = lines(banner.render_banner(caps(width=80), lang="en", version="1.0.0"))
    assert len(at_80) == 13 and {visible_len(x) for x in at_80} == {79}
    assert "█" in "".join(at_80) and "Multi-platform C/C++ Build System v1.0.0" in "\n".join(at_80)


def test_the_target_layout_matches_the_specification_at_84_columns():
    text = banner.render_banner(caps(width=84), lang="fr", version="0.13.0")            # 83 wide plus the free last column
    got = lines(text)
    assert got[0] == "╔" + "═" * 81 + "╗" and got[-1] == "╚" + "═" * 81 + "╝"
    assert got[1] == "║" + " " * 81 + "║" and got[8] == got[1] and got[11] == got[1]
    assert got[2].startswith("║    ██████╗██╗  ██╗ █████╗ ██████╗ ██████╗ ███████╗███╗   ██╗████████╗███████╗   ║")
    assert got[7].startswith("║    ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚══════╝   ║")
    assert got[9].strip("║ ") == "Système de build C/C++ multiplateforme v0.13.0" and got[10].strip("║ ") == "Moteur · Paquets · Kits · Studio"
    assert len(got) == 13


def test_a_narrow_terminal_gets_a_compact_frame_that_never_overflows():
    for width in range(1, 80):
        text = banner.render_banner(caps(width=width), lang="fr", version="0.13.0")
        assert all(visible_len(x) <= width for x in lines(text)), width
        assert len({visible_len(x) for x in lines(text)}) == 1
    compact = banner.render_banner(caps(width=60), lang="en", version="0.13.0")
    assert "C H A R P E N T E" in compact and "█" not in compact and "v0.13.0" in compact
    assert len(lines(compact)) == 4


def test_a_terminal_too_narrow_for_a_frame_gets_one_clipped_line():
    tiny = banner.render_banner(caps(width=5), version="0.13.0")
    assert "\n" not in tiny and visible_len(tiny) <= 5
    assert banner.render_banner(caps(width=1), version="0.13.0") != ""              # never empty, never an error


def test_the_compact_subtitle_is_clipped_with_an_ellipsis_not_cut_mid_frame():
    text = banner.render_banner(caps(width=30), lang="en", version="0.13.0")
    assert "…" in text and all(visible_len(x) <= 30 for x in lines(text))
    ascii_text = banner.render_banner(caps(width=30, unicode=False), lang="en", version="0.13.0")
    assert "..." in ascii_text and "…" not in ascii_text


# ---------------------------------------------------------------------- colour and characters
def test_without_colour_there_is_no_escape_sequence_at_all():
    for width in (120, 60):
        assert "\x1b" not in banner.render_banner(caps(NONE, width))


@pytest.mark.parametrize("depth", (BASIC, EXTENDED, TRUE))
def test_with_colour_the_text_is_the_same_as_without(depth):
    plain = banner.render_banner(caps(NONE, 100), lang="fr", version="0.13.0")
    coloured = banner.render_banner(caps(depth, 100), lang="fr", version="0.13.0")
    assert "\x1b[" in coloured and strip_ansi(coloured) == plain


def test_every_colour_run_is_closed():
    coloured = banner.render_banner(caps(TRUE, 100), lang="en", version="0.13.0")
    assert coloured.count("\x1b[0m") >= coloured.count("\x1b[") // 2                   # each style is followed by a reset
    for line in lines(coloured):
        assert not line.endswith("m") or line.endswith("\x1b[0m")


def test_blocks_and_shadow_have_different_colours_and_the_blocks_form_a_gradient():
    theme = banner.THEMES["bois"]
    assert theme.fill(0) != theme.fill(4) and theme.shadow not in (theme.fill(0), theme.fill(4))
    coloured = banner.render_banner(caps(TRUE, 100), theme, "en", "0.13.0")
    first_fill, last_fill = theme.fill(0), theme.fill(4)
    assert f"38;2;{first_fill[0]};{first_fill[1]};{first_fill[2]}" in coloured and f"38;2;{last_fill[0]};{last_fill[1]};{last_fill[2]}" in coloured
    assert f"38;2;{theme.shadow[0]};{theme.shadow[1]};{theme.shadow[2]}" in coloured
    assert f"38;2;{theme.frame[0]};{theme.frame[1]};{theme.frame[2]}" in coloured


def test_the_neon_theme_has_a_flat_pink_fill():
    neon = banner.THEMES["neon"]
    assert neon.fill(0) == neon.fill(3) == neon.fill(5) == (255, 45, 150)


def test_the_gradient_endpoints_and_steps():
    for theme in banner.THEMES.values():
        assert theme.fill(0) == theme.top and theme.fill(4) == theme.bottom            # rows 0-4 carry blocks; row 5 is only shadow
        assert theme.fill(5) == theme.bottom and theme.fill(-3) == theme.top and theme.fill(99) == theme.bottom      # out-of-range rows are clamped
    ocean = [banner.THEMES["ocean"].fill(i) for i in range(5)]
    reds = [c[0] for c in ocean]
    assert reds == sorted(reds, reverse=True) and len(set(ocean)) == 5                # steadily changing, no repeated step


def test_the_ascii_look_uses_no_drawing_character_and_only_ascii():
    text = banner.render_banner(caps(NONE, 100, unicode=False), lang="fr", version="0.13.0")
    assert not (DRAWING & set(text)) and all(ord(c) < 128 for c in text)
    assert lines(text)[0].startswith("+=") and lines(text)[1].startswith("|") and "Systeme de build" in text
    assert len({visible_len(x) for x in lines(text)}) == 1
    assert all(ord(c) < 128 for c in banner.render_banner(caps(NONE, 40, unicode=False), lang="fr"))


def test_coloured_ascii_is_still_ascii_plus_escape_codes():
    text = strip_ansi(banner.render_banner(caps(TRUE, 100, unicode=False), lang="fr"))
    assert all(ord(c) < 128 for c in text)


def test_fold_ascii():
    assert banner.fold_ascii("Système · Kits — Paquets…") == "Systeme | Kits - Paquets..."
    assert banner.fold_ascii("日本") == "??" and banner.fold_ascii("héllo") == "hello"


def test_render_is_pure_and_repeatable():
    args = (caps(TRUE, 100), banner.THEMES["foret"], "fr", "0.13.0")
    assert banner.render_banner(*args) == banner.render_banner(*args)


# ---------------------------------------------------------------------- themes, language, version
def test_theme_lookup_is_forgiving():
    assert banner.theme_named("NEON").name == "neon" and banner.theme_named(" ocean ").name == "ocean"
    for bad in (None, "", "nope", "bois "):
        assert banner.theme_named(bad).name == "bois"


def test_the_four_themes_exist_and_differ():
    assert sorted(banner.THEMES) == ["bois", "foret", "neon", "ocean"]
    assert len({t.frame for t in banner.THEMES.values()}) >= 3 and len({t.shadow for t in banner.THEMES.values()}) == 4


def test_language_and_version_come_from_the_arguments_and_the_defaults():
    fr = banner.render_banner(caps(width=100), lang="fr", version="9.9.9")
    en = banner.render_banner(caps(width=100), lang="en", version="9.9.9")
    assert "Système de build C/C++ multiplateforme v9.9.9" in fr and "Multi-platform C/C++ Build System v9.9.9" in en
    assert "Moteur" in fr and "Engine" in en
    from charpente import _version

    assert f"v{_version.__version__}" in banner.render_banner(caps(width=100), lang="en")


# ---------------------------------------------------------------------- when the banner is shown
def show(command="build", **kw):
    return banner.should_show_banner(command, kw.pop("caps", caps()), env=kw.pop("env", {}), **kw)


def test_it_is_shown_for_the_interactive_commands_on_a_terminal():
    for command in ("build", "run", "test", "package", "deploy", "dev", "init", "setup", "studio", "menu", None):
        assert show(command), command


def test_it_is_never_shown_for_commands_read_by_programs():
    for command in ("--version", "explain", "serve", "debug-adapter", "shell", "why", "history", "doctor", "cache", "pkg", "sbom", "generate"):
        assert not show(command), command


def test_it_is_never_shown_in_plain_or_json_output():
    assert not show(mode="plain") and not show(mode="jsonl")
    assert show(mode="auto") and show(mode="rich")


def test_it_is_never_shown_off_a_terminal_in_ci_or_when_asked_not_to():
    assert not show(caps=caps(tty=False))
    assert not show(caps=caps(ci=True))
    for value in ("1", "true", "YES"):
        assert not show(env={"CHARPENTE_NO_BANNER": value})
    assert show(env={"CHARPENTE_NO_BANNER": "0"}) and show(env={"CHARPENTE_NO_BANNER": ""})


def test_it_is_shown_only_once_per_process():
    assert show() and not show(shown=True)


# ---------------------------------------------------------------------- printing it
class Stream(io.StringIO):
    def __init__(self, tty=True):
        super().__init__()
        self._tty = tty

    def isatty(self):
        return self._tty

    encoding = "utf-8"


@pytest.fixture(autouse=True)
def _fresh():
    banner.reset()
    yield
    banner.reset()


def test_print_banner_writes_nothing_into_a_pipe_unless_forced():
    pipe = Stream(tty=False)
    assert banner.print_banner(pipe, env={}, lang="en") is False and pipe.getvalue() == ""
    assert banner.print_banner(pipe, env={}, lang="en", force=True) is True and "CHARPENTE" in pipe.getvalue().upper().replace(" ", "") or "█" in pipe.getvalue()


def test_print_banner_writes_once_on_a_terminal():
    tty = Stream()
    assert banner.print_banner(tty, env={"NO_COLOR": "1"}, caps=caps(width=100), lang="fr", version="0.13.0") is True
    first = tty.getvalue()
    assert first.startswith("╔") and first.endswith("\n\n") and "\x1b" not in first
    assert banner.print_banner(tty, env={}, caps=caps(width=100)) is False and tty.getvalue() == first      # once per process
    assert banner.already_shown()


def test_the_theme_comes_from_the_environment():
    tty = Stream()
    banner.print_banner(tty, env={"CHARPENTE_THEME": "neon"}, caps=caps(TRUE, 100), lang="en", version="1")
    assert "38;2;255;45;150" in tty.getvalue()                                    # neon's pink blocks


def test_print_banner_never_raises_whatever_the_stream_does():
    class Hostile(io.StringIO):
        encoding = "utf-8"

        def isatty(self):
            return True

        def write(self, text):
            raise OSError("broken pipe")

    class Closed(io.StringIO):
        def isatty(self):
            raise ValueError("closed")

    assert banner.print_banner(Hostile(), env={}, caps=caps(), lang="en") is False
    assert banner.print_banner(Closed(), env={}, lang="en") is False
    assert banner.print_banner(Stream(), env={"CHARPENTE_THEME": None}, caps=caps(), lang="en") in (True, False)   # type: ignore[dict-item]


def test_a_stream_that_cannot_flush_is_fine():
    class NoFlush(Stream):
        def flush(self):
            raise ValueError("closed")

    assert banner.print_banner(NoFlush(), env={}, caps=caps(), lang="en") is True


def test_the_default_stream_is_standard_output(capsys):
    assert banner.print_banner(env={}, caps=caps(NONE, 100), lang="en", version="1.2.3") is True
    assert "v1.2.3" in capsys.readouterr().out
