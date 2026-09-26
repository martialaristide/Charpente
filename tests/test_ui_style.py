"""charpente.ui.style (the build lines) and i18n/ui (their words). Pure functions: no terminal is needed."""
import string

import pytest

from charpente.i18n import ui as words
from charpente.ui import banner
from charpente.ui.style import ASCII_SYMBOLS, SAFE_SYMBOLS, UNICODE_SYMBOLS, Style, format_duration, symbols_for
from charpente.ui.term import BASIC, EXTENDED, NONE, TRUE, Caps, strip_ansi, visible_len

ALL_DEPTHS = (NONE, BASIC, EXTENDED, TRUE)
DRAWING = set("━─│╭╮╰╯▸✔✘◆▲…█")


def caps(color=NONE, width=100, unicode=True):
    return Caps(tty=True, color=color, unicode=unicode, width=width)


def sample(style, name_width=14):
    return [style.stage("Chargement de l'espace de travail"),
            style.context([("espace", "CasqueDemo"), ("config", "Debug"), ("plateforme", "linux-x64"), ("outils", "gcc 13.2")]),
            style.stage("Construction"),
            style.target_ok("moteur", "build/Debug/moteur/libmoteur.a", 2.4, name_width),
            style.target_cached("shaders", "à jour, servi par le cache", name_width),
            style.target_ok("app", "build/Debug/app/app", 1.1, name_width),
            style.warning("app : 2 avertissements, voir charpente build -v"),
            style.target_failed("tests_moteur", "échec de l'édition de liens", name_width),
            style.detail("src/main.cpp:9:1: error: expected unqualified-id"),
            style.progress(38, 40)] + style.result_box("Résultat", [("cibles", "3 réussies, 1 échec"), ("cache", "41 actions sur 57"), ("durée", "4,2 s"),
                                                                     ("suite", "charpente why tests_moteur")], False)


# ---------------------------------------------------------------------- the reference layout
def test_the_lines_match_the_reference_layout_without_colour():
    got = sample(Style(caps(), lang="fr"))
    assert got[:9] == [
        "  ▸ Chargement de l'espace de travail",
        "  espace CasqueDemo │ config Debug │ plateforme linux-x64 │ outils gcc 13.2",
        "  ▸ Construction",
        "  ✔ moteur          build/Debug/moteur/libmoteur.a  2,4 s",
        "  ◆ shaders         à jour, servi par le cache",
        "  ✔ app             build/Debug/app/app  1,1 s",
        "  ▲ app : 2 avertissements, voir charpente build -v",
        "  ✘ tests_moteur    échec de l'édition de liens",
        "      src/main.cpp:9:1: error: expected unqualified-id"]
    assert got[9] == "  " + "━" * 28 + "── 38/40"
    assert got[10:] == ["  ╭─ Résultat ────────────────────────────╮", "  │  cibles   3 réussies, 1 échec         │", "  │  cache    41 actions sur 57           │",
                        "  │  durée    4,2 s                       │", "  │  suite    charpente why tests_moteur  │", "  ╰───────────────────────────────────────╯"]


def test_the_ascii_look_matches_the_specified_replacements():
    got = sample(Style(caps(unicode=False), lang="fr"))
    assert got[3].startswith("  [ok] moteur") and got[4].startswith("  [=]  shaders") and got[6].startswith("  [!]  app") and got[7].startswith("  [x]  tests_moteur")
    assert got[0].startswith("  > ") and " | " in got[1] and "━" not in "".join(got) and got[10].startswith("  +- Resultat")
    assert all(ord(c) < 128 for line in got for c in line), "the ASCII look must be pure ASCII"
    assert not (DRAWING & set("".join(got)))
    assert "chec" in "".join(got) and "echec de l'edition" in got[7]                              # accents folded, words kept


def test_ascii_names_and_columns_still_line_up():
    got = sample(Style(caps(unicode=False), lang="fr"))
    assert len({line.index("moteur" if "moteur" in line and "ok" in line else "x") for line in got[3:4]}) == 1
    starts = [line.index(name) for line, name in ((got[3], "moteur"), (got[4], "shaders"), (got[5], "app"), (got[7], "tests_moteur"))]
    assert len(set(starts)) == 1                                                                 # the name column is aligned whatever the symbol


# ---------------------------------------------------------------------- colour
@pytest.mark.parametrize("depth", (BASIC, EXTENDED, TRUE))
def test_with_colour_the_text_is_the_same_as_without(depth):
    plain = sample(Style(caps(NONE), lang="fr"))
    coloured = sample(Style(caps(depth), lang="fr"))
    assert [strip_ansi(x) for x in coloured] == plain and any("\x1b[" in x for x in coloured)


def test_without_colour_there_is_no_escape_sequence():
    assert not any("\x1b" in line for line in sample(Style(caps(NONE))))


def test_each_kind_of_line_has_its_own_colour():
    style = Style(caps(TRUE), lang="en")
    ok, warn, fail, cached = style.target_ok("a"), style.warning("w"), style.target_failed("a", "m"), style.target_cached("a", "n")
    assert "38;2;72;200;120" in ok and "38;2;240;196;64" in warn and "38;2;240;84;84" in fail
    theme = style.theme
    assert f"38;2;{theme.frame[0]};{theme.frame[1]};{theme.frame[2]}" in cached
    assert len({ok.split("m")[0], warn.split("m")[0], fail.split("m")[0]}) == 3


def test_the_result_box_is_green_on_success_and_red_on_failure():
    good = "\n".join(Style(caps(TRUE)).result_box("R", [("a", "b")], True))
    bad = "\n".join(Style(caps(TRUE)).result_box("R", [("a", "b")], False))
    assert "38;2;72;200;120" in good and "38;2;240;84;84" not in good
    assert "38;2;240;84;84" in bad and "38;2;72;200;120" not in bad


def test_the_theme_colours_the_progress_bar_and_the_cached_symbol():
    for name, theme in banner.THEMES.items():
        line = Style(caps(TRUE), theme).progress(5, 10)
        f = theme.fill(2)
        assert f"38;2;{f[0]};{f[1]};{f[2]}" in line, name


# ---------------------------------------------------------------------- never wider than the terminal
@pytest.mark.parametrize("unicode", [True, False])
@pytest.mark.parametrize("depth", (NONE, TRUE))
def test_no_line_is_wider_than_the_terminal(unicode, depth):
    for width in (12, 20, 30, 40, 60, 80, 120):
        style = Style(caps(depth, width, unicode), lang="fr")
        lines = sample(style) + [style.target_ok("n" * 80, "p/" * 100, 123456.7, 90), style.warning("w " * 200), style.target_failed("f", "m" * 500),
                                 style.context([("a" * 50, "b" * 200)])]
        for line in lines:
            assert visible_len(line) <= width, (width, strip_ansi(line))


def test_a_clipped_line_ends_with_an_ellipsis_and_keeps_its_colour_balanced():
    line = Style(caps(TRUE, 30)).target_ok("name", "x" * 100, 1.0)
    assert visible_len(line) <= 30 and strip_ansi(line).endswith("…") and line.endswith("\x1b[0m")


def test_a_wide_character_never_splits_the_frame():
    box = Style(caps(NONE, 40)).result_box("日本語", [("名前", "値" * 30)], True)
    assert len({visible_len(x) for x in box}) == 1 and visible_len(box[0]) <= 40


# ---------------------------------------------------------------------- pieces
def test_progress_is_bounded_and_forgiving():
    style = Style(caps(NONE, 60))
    assert style.progress(0, 40).endswith(" 0/40") and "━" not in style.progress(0, 40)
    assert style.progress(40, 40).count("━") == style.progress(40, 40).count("━") > 0 and "─" not in style.progress(40, 40)
    over = style.progress(99, 40)
    assert over.endswith("40/40") and "─" not in over                                            # done is clamped to total
    assert style.progress(-5, 40).endswith("0/40")
    assert style.progress(3, 0).endswith("0/0") and "━" not in style.progress(3, 0)              # nothing to do: an empty bar, no division by zero
    assert style.progress("x", "y").endswith("0/0")                                              # type: ignore[arg-type]  # nonsense is shown as 0/0
    assert style.progress(1, 4, width=8).count("━") + style.progress(1, 4, width=8).count("─") == 8
    tiny = Style(caps(NONE, 10)).progress(3, 5)
    assert tiny.strip() == "3/5"                                                                 # no room for a bar: the counter alone


def test_the_progress_bar_fills_in_proportion():
    style = Style(caps(NONE, 100))
    half = style.progress(20, 40, width=20)
    assert half.count("━") == 10 and half.count("─") == 10


def test_context_leaves_out_empty_values():
    line = Style(caps()).context([("espace", "Demo"), ("plateforme", ""), ("outils", "gcc")])
    assert line == "  espace Demo │ outils gcc"
    assert Style(caps()).context([]) == "  " and Style(caps()).context([("a", "")]) == "  "


def test_target_lines_pad_names_to_the_column_and_omit_missing_parts():
    style = Style(caps(), lang="en")
    assert style.target_ok("a", "out", 0.05, 4) == "  ✔ a     out  0.05 s"
    assert style.target_ok("a") == "  ✔ a" and style.target_ok("a", "", 2.0) == "  ✔ a  2.0 s"
    assert style.target_failed("a", "") == "  ✘ a"


def test_the_result_box_is_a_rectangle_whatever_the_rows():
    for rows in ([], [("a", "b")], [("cibles", "3 réussies, 1 échec"), ("suite", "x" * 200)]):
        for width in (20, 60, 100):
            box = Style(caps(NONE, width)).result_box("Résultat", rows, True)
            assert len({visible_len(x) for x in box}) == 1 and visible_len(box[0]) <= width
            assert box[0].strip().startswith("╭") and box[-1].strip().startswith("╰")


def test_symbol_tables_are_complete():
    assert UNICODE_SYMBOLS.ok == "✔" and UNICODE_SYMBOLS.fail == "✘" and UNICODE_SYMBOLS.cached == "◆" and UNICODE_SYMBOLS.warn == "▲" and UNICODE_SYMBOLS.stage == "▸"
    assert (ASCII_SYMBOLS.ok, ASCII_SYMBOLS.cached, ASCII_SYMBOLS.warn, ASCII_SYMBOLS.fail, ASCII_SYMBOLS.stage, ASCII_SYMBOLS.sep) == ("[ok]", "[=]", "[!]", "[x]", ">", "|")
    assert all(ord(c) < 128 for field in ASCII_SYMBOLS.__dict__.values() for c in "".join(field))


@pytest.mark.parametrize("seconds,lang,expected", [
    (2.4, "en", "2.4 s"), (2.4, "fr", "2,4 s"), (0.08, "en", "0.08 s"), (0.0, "en", "0.0 s"), (59.94, "en", "59.9 s"), (65, "en", "1 min 05 s"),
    (3600, "fr", "60 min 00 s"), (-1, "en", "0.0 s"), (float("nan"), "en", "0.0 s"), (None, "en", "0.0 s"), ("x", "en", "0.0 s")])
def test_durations(seconds, lang, expected):
    assert format_duration(seconds, lang) == expected


# ---------------------------------------------------------------------- the words
def placeholders(text):
    return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name)


def test_both_languages_have_the_same_keys_and_the_same_placeholders():
    assert set(words.EN) == set(words.FR)
    for key in words.EN:
        assert placeholders(words.EN[key]) == placeholders(words.FR[key]), key
        assert words.EN[key].strip() and words.FR[key].strip(), key


def test_plurals():
    assert [words.plural_key("fr", n) for n in (0, 1, 2)] == ["one", "one", "many"]
    assert [words.plural_key("en", n) for n in (0, 1, 2)] == ["many", "one", "many"]
    assert words.t(f"result.failed.{words.plural_key('fr', 1)}", "fr") == "1 échec"
    assert words.t(f"result.failed.{words.plural_key('fr', 3)}", "fr", n=3) == "3 échecs"
    assert words.t(f"result.ok.{words.plural_key('en', 3)}", "en", n=3) == "3 succeeded"


def test_lookup_never_raises():
    assert words.t("no.such.key", "en") == "no.such.key" and words.t("stage.building", "xx") == "Building"
    assert words.t("warnings.many", "en", target="app") == "app: {count} warnings, see charpente build -v"           # a missing value stays visible
    assert words.t("stage.building", "fr") == "Construction"


def test_the_language_defaults_to_the_current_one(monkeypatch):
    monkeypatch.setenv("CHARPENTE_LANG", "fr")
    assert words.t("stage.building") == "Construction"
    monkeypatch.setenv("CHARPENTE_LANG", "en")
    assert words.t("stage.building") == "Building"


# ---------------------------------------------------------------------- the safe symbols of a classic console font
def test_the_symbol_set_is_chosen_from_the_capabilities():
    assert symbols_for(Caps(unicode=True, modern=True)) is UNICODE_SYMBOLS
    assert symbols_for(Caps(unicode=True, modern=False)) is SAFE_SYMBOLS
    assert symbols_for(Caps(unicode=False, modern=True)) is ASCII_SYMBOLS and symbols_for(Caps(unicode=False, modern=False)) is ASCII_SYMBOLS


def test_the_safe_symbols_avoid_the_glyphs_a_console_font_lacks():
    lacking = set("✔✘◆▸━╭╮╰╯")                                                                     # Consolas and Lucida Console have none of these
    got = sample(Style(Caps(tty=True, unicode=True, modern=False, width=100), lang="fr"))
    assert not (lacking & set("".join(got)))
    assert got[3].startswith("  √ moteur") and got[4].startswith("  ♦ shaders") and got[6].startswith("  ▲ app") and got[7].startswith("  × tests_moteur") and got[0].startswith("  ► ")
    assert "▬" in got[9] and got[10].startswith("  ┌─ Résultat") and got[-1].startswith("  └")
    assert len({visible_len(x) for x in got[10:]}) == 1                                             # the box is still a rectangle
    allowed = set("►√♦▲×│▬─…┌┐└┘éèàçÉ")                                                              # every non-ASCII character used is in the WGL4 set
    assert {c for c in "".join(got) if ord(c) > 127} <= allowed


def test_the_safe_look_still_has_a_distinct_bar_without_colour():
    line = Style(Caps(tty=True, unicode=True, modern=False, width=100)).progress(20, 40, width=20)
    assert line.count("▬") == 10 and line.count("─") == 10
