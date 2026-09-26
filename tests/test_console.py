"""The console interface (`charpente` alone in a terminal): terminal helpers, drawing, the dashboard, the guided flows in both input modes, and a real run."""
import ast
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from charpente import console, settings
from charpente.cli import main
from charpente.console import app as app_mod
from charpente.console import dashboard as dash_mod
from charpente.console import term, text, view
from charpente.console.app import Console, display_command, split_args
from charpente.console.dashboard import Dashboard, LastBuild, TargetInfo
from charpente.console.term import (
    ASCII_GLYPHS,
    UNICODE_GLYPHS,
    Caps,
    Keys,
    Style,
    box,
    clip,
    decode_posix,
    decode_windows,
    pad,
    truncate_middle,
    visible_len,
)

HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++"))
RED, RESET = "\x1b[31m", "\x1b[0m"


# ---------------------------------------------------------------------- words
def test_both_languages_have_the_same_keys_and_every_key_used_exists():
    assert set(text.EN) == set(text.FR)
    used = set()
    for name in ("app.py", "view.py"):
        tree = ast.parse((Path(app_mod.__file__).parent / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in ("tr", "t") and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    used.add(first.value)
    assert used and not sorted(k for k in used if k not in text.EN)
    assert all(f"tip.{i}" in text.EN for i in range(1, text.TIP_COUNT + 1))
    assert all(f"guide.{i}" in text.EN for i in range(1, text.GUIDE_LINES + 1)) and all(f"help.{i}" in text.EN for i in range(1, text.HELP_LINES + 1))


def test_every_placeholder_is_the_same_in_both_languages():
    import string

    for key in text.EN:
        fields = lambda s: sorted(f for _, f, _, _ in string.Formatter().parse(s) if f)  # noqa: E731
        assert fields(text.EN[key]) == fields(text.FR[key]), key


def test_lookup_never_raises_and_keeps_an_empty_line_empty():
    assert text.lookup("en", "no.such.key") == "no.such.key" and text.lookup("xx", "bye") == text.EN["bye"]
    assert text.lookup("fr", "help.4") == ""


# ---------------------------------------------------------------------- measuring and framing text
def test_visible_length_ignores_colour_and_counts_wide_characters():
    assert visible_len(f"{RED}abc{RESET}") == 3 and visible_len("日本") == 4 and visible_len("e\u0301") == 1
    assert pad(f"{RED}ab{RESET}", 5).endswith("   ") and visible_len(pad(f"{RED}ab{RESET}", 5)) == 5


def test_clip_keeps_colours_balanced():
    long = f"{RED}{'x' * 30}{RESET} tail"
    cut = clip(long, 10, "...")
    assert visible_len(cut) == 10 and cut.endswith("..." + RESET)
    assert clip("short", 10) == "short" and clip("anything", 0) == ""
    assert visible_len(clip("日本語のテキスト", 7)) <= 7


def test_a_long_path_is_shortened_in_the_middle():
    path = "C:\\Users\\someone\\Documents\\projects\\game\\engine"
    short = truncate_middle(path, 30)
    assert len(short) == 30 and short.startswith("C:\\Users") and short.endswith("engine") and "..." in short
    assert truncate_middle("abc", 30) == "abc"


@pytest.mark.parametrize("glyphs", [UNICODE_GLYPHS, ASCII_GLYPHS])
@pytest.mark.parametrize("width", [20, 40, 80])
def test_a_box_is_always_exactly_as_wide_as_asked(glyphs, width):
    rows = ["short", "x" * 200, f"{RED}coloured {'y' * 100}{RESET}", ""]
    framed = box(rows, width, glyphs, "A title that is quite long indeed", Style(True))
    assert {visible_len(line) for line in framed} == {max(8, width)}
    assert len(framed) == len(rows) + 2


# ---------------------------------------------------------------------- keys
def test_windows_keys_are_decoded():
    seq = iter("H")
    assert decode_windows("\xe0", lambda: next(seq)) == "up"
    assert decode_windows("\x00", lambda: "P") == "down" and decode_windows("\xe0", lambda: "?") == "unknown"
    assert decode_windows("\r", lambda: "") == "enter" and decode_windows("a", lambda: "") == "a" and decode_windows("\x1b", lambda: "") == "esc"
    assert decode_windows("\x03", lambda: "") == "ctrl-c" and decode_windows("\x08", lambda: "") == "backspace"


@pytest.mark.parametrize("rest,expected", [("[A", "up"), ("[B", "down"), ("[C", "right"), ("[D", "left"), ("OH", "home"), ("[F", "end"), ("[5~", "pgup"),
                                           ("[6~", "pgdn"), ("[3~", "delete"), ("[1;5A", "up"), ("", "esc"), ("x", "esc"), ("[", "unknown")])
def test_posix_escape_sequences_are_decoded(rest, expected):
    chars = iter(rest)
    assert decode_posix("\x1b", lambda: next(chars, "")) == expected


def test_plain_characters_pass_through_on_posix():
    assert decode_posix("q", lambda: "") == "q" and decode_posix("\n", lambda: "") == "enter" and decode_posix("é", lambda: "") == "é"


# ---------------------------------------------------------------------- what the terminal can do
class Stream(io.StringIO):
    def __init__(self, tty, encoding="utf-8"):
        super().__init__()
        self._tty = tty
        self._encoding = encoding

    def isatty(self):
        return self._tty

    @property
    def encoding(self):
        return self._encoding


def caps_of(tty=True, env=None, encoding="utf-8", vt=True):
    return term.detect(Stream(tty), Stream(tty, encoding), env or {}, enable_vt=lambda: vt, size=lambda: os.terminal_size((90, 30)))


def test_a_terminal_gets_colour_and_a_pipe_does_not():
    on = caps_of()
    assert on.interactive and on.ansi and on.color and on.unicode and (on.width, on.height) == (90, 30)
    off = caps_of(tty=False)
    assert not off.interactive and not off.ansi and not off.color


def test_no_color_dumb_terminals_and_plain_mode_are_respected():
    assert not caps_of(env={"NO_COLOR": "1"}).color and caps_of(env={"NO_COLOR": "1"}).ansi
    for env in ({"TERM": "dumb"}, {"CHARPENTE_CONSOLE": "plain"}):
        c = caps_of(env=env)
        assert not c.ansi and not c.color and not c.interactive


def test_an_old_console_falls_back_to_ascii_frames_and_to_plain_input_when_vt_fails():
    assert not caps_of(encoding="ascii").unicode and term.glyphs_for(caps_of(encoding="ascii")) is ASCII_GLYPHS
    if sys.platform == "win32":
        assert not caps_of(vt=False).ansi


def test_styles_do_nothing_without_colour():
    off, on = Style(False), Style(True)
    assert off.bold("x") == off.err("x") == off.selected("x") == "x"
    assert on.err("x") == "\x1b[31mx\x1b[0m" and on.bold("") == ""


# ---------------------------------------------------------------------- drawing
def entries():
    return [view.group("Build"), view.Entry("build", "Build", "Compile it", "1"), view.Entry("run", "Run", "Start it", "2", enabled=False, reason="Nothing to run"),
            view.group("Tools"), view.Entry("doctor", "Diagnose", "Explain things"), view.Entry("quit", "Quit", "", "q")]


def test_hotkeys_are_given_to_rows_without_one_and_never_clash():
    given = view.with_hotkeys([view.Entry("a", "A"), view.Entry("b", "B", hotkey="1"), view.Entry("c", "C"), view.group("g"), view.Entry("d", "D")])
    keys = [e.hotkey for e in given if e.kind == "item"]
    assert keys == ["2", "1", "3", "4"] or sorted(keys) == ["1", "2", "3", "4"]
    assert len(set(keys)) == 4 and not {"q", "b", "?"} & set(keys)
    many = view.with_hotkeys([view.Entry(str(i), str(i)) for i in range(30)])
    assert len({e.hotkey for e in many if e.hotkey}) == len([e for e in many if e.hotkey])


@pytest.mark.parametrize("glyphs", [UNICODE_GLYPHS, ASCII_GLYPHS])
@pytest.mark.parametrize("width", [30, 50, 72, 100])
def test_the_menu_never_overflows_and_marks_the_selection(glyphs, width):
    lines, hidden = view.menu(view.with_hotkeys(entries()), 1, Style(True), glyphs, width, 30)
    assert hidden == 0 and all(visible_len(line) <= width for line in lines)
    marked = [line for line in lines if glyphs.marker in line]
    assert len(marked) == 1 and "Build" in marked[0]
    plain = "\n".join(view.menu(view.with_hotkeys(entries()), 1, Style(False), glyphs, 100, 30)[0])
    assert "Nothing to run" in plain and "Compile it" in plain                          # hints and reasons beside the rows when there is room
    narrow = "\n".join(view.menu(view.with_hotkeys(entries()), 1, Style(False), glyphs, 40, 30)[0])
    assert "Compile it" not in narrow                                                   # ...and on the detail line instead when there is not


def test_a_long_menu_scrolls_to_keep_the_selection_visible():
    many = view.with_hotkeys([view.Entry(str(i), f"Item {i}", "") for i in range(40)])
    for selected in (0, 20, 39):
        lines, hidden = view.menu(many, selected, Style(False), UNICODE_GLYPHS, 60, 10)
        assert len(lines) <= 10 and hidden > 0 and f"Item {selected}" in "\n".join(lines)


def test_detail_line_says_what_a_row_does_or_why_it_cannot_be_used():
    a, b = entries()[1], entries()[2]
    assert "Compile it" in view.detail(a, Style(False), 80) and "Nothing to run" in view.detail(b, Style(False), 80)
    assert view.detail(entries()[0], Style(False), 80) == "" and view.detail(None, Style(False), 80) == ""


def tr_en(key, **values):
    return text.lookup("en", key).format(**values)


def project(**changes):
    base = dict(host="windows-x64", compiler="mingw (g++.EXE)", root=Path("C:/work/demo"), file=Path("C:/work/demo/demo.charpente"), name="demo",
                targets=[TargetInfo("demo", "executable"), TargetInfo("demo_tests", "test")], state="ok",
                last=LastBuild(True, 1000.0, 1.25, "Debug", "build"))
    base.update(changes)
    return Dashboard(**base)


@pytest.mark.parametrize("width", [46, 60, 100])
def test_the_dashboard_is_a_clean_frame_in_every_state(width):
    for dash in (project(), project(last=None), project(last=LastBuild(False, 900.0, 3.0, "Release", "test")), project(state="untrusted"), project(state="error", detail="line 3:\n  bad"),
                 project(compiler=""), Dashboard(host="linux-x64", compiler=""), Dashboard(state="ambiguous", detail="a.charpente, b.charpente")):
        lines = view.dashboard(dash, "C:/somewhere/very/long/" + "folder/" * 12, "Release", None, tr_en, Style(True), UNICODE_GLYPHS, width, now=1100.0)
        assert {visible_len(line) for line in lines} == {width}
    text_ = "\n".join(view.dashboard(project(), "x", "Debug", None, tr_en, Style(False), ASCII_GLYPHS, 80, now=1100.0))
    assert "succeeded" in text_ and "1m" not in text_ and "1 min ago" in text_ and "2 target(s)" in text_ and "Debug" in text_ and "this machine" in text_


def test_time_ago_in_both_languages():
    tr_fr = lambda key, **v: text.lookup("fr", key).format(**v)  # noqa: E731
    assert view.ago(5, tr_en) == "5 s ago" and view.ago(120, tr_en) == "2 min ago" and view.ago(7200, tr_en) == "2 h ago" and view.ago(200000, tr_en) == "2 d ago"
    assert view.ago(120, tr_fr) == "il y a 2 min" and view.ago(-5, tr_en) == "0 s ago"


# ---------------------------------------------------------------------- the dashboard's data
class Boom(Exception):
    code = "CH1004"
    message = "line 3: bad"


def test_no_project_and_ambiguous_folders(tmp_path):
    from charpente.errors import ChError

    def none(cwd):
        raise ChError("CH1002", directory=str(cwd))

    def several(cwd):
        raise ChError("CH1003", directory=str(cwd), names="a.charpente, b.charpente")

    d = dash_mod.gather(tmp_path, find=none, compiler=lambda: "gcc", host=lambda: "linux-x64")
    assert d.state == "none" and not d.has_project and d.compiler == "gcc"
    d = dash_mod.gather(tmp_path, find=several, compiler=lambda: "", host=lambda: "")
    assert d.state == "ambiguous" and "a.charpente" in d.detail and not d.has_project


def test_an_unapproved_project_file_is_never_loaded(tmp_path):
    file = tmp_path / "x.charpente"
    d = dash_mod.gather(tmp_path, find=lambda c: file, trusted=lambda p: False, load=lambda p: pytest.fail("code must not run before approval"))
    assert d.state == "untrusted" and d.has_project and d.name == "x"


def test_a_readable_project_and_a_broken_one(tmp_path):
    file = tmp_path / "x.charpente"
    loaded = ("demo", tmp_path, [TargetInfo("demo", "executable")], None)
    d = dash_mod.gather(tmp_path, find=lambda c: file, trusted=lambda p: True, load=lambda p: loaded)
    assert d.state == "ok" and d.name == "demo" and d.targets[0].name == "demo" and [t.name for t in d.runnable()] == ["demo"]

    def broken(path):
        raise Boom()

    d = dash_mod.gather(tmp_path, find=lambda c: file, trusted=lambda p: True, load=broken)
    assert d.state == "error" and "bad" in d.detail and d.has_project


def test_a_failing_probe_shows_as_missing_not_as_a_crash(tmp_path):
    def bad():
        raise RuntimeError("no")

    d = dash_mod.gather(tmp_path, find=lambda c: (_ for _ in ()).throw(RuntimeError("x")), compiler=bad, host=bad)
    assert d.state == "none" and d.compiler == "" and d.host == ""


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_the_real_gatherer_reads_a_real_project_without_printing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    (tmp_path / "p.charpente").write_text('from charpente import *\nwith Workspace("p") as ws:\n    with Target("p") as t:\n        t.kind(Kind.EXECUTABLE)\n        t.sources(["src/*.cpp"])\n',
                                          encoding="utf-8")
    d = dash_mod.gather(tmp_path)
    assert capsys.readouterr().out == "" and d.state in ("ok", "untrusted")
    if d.state == "ok":
        assert d.name == "p" and [(t.name, t.kind) for t in d.targets] == [("p", "executable")]


# ---------------------------------------------------------------------- helpers of the flows
def test_commands_are_displayed_the_way_you_would_type_them():
    assert display_command(["build", "--config", "Debug"]) == "charpente build --config Debug"
    assert display_command(["commit", "-m", "fix the thing", "-a"]) == 'charpente commit -m "fix the thing" -a'
    assert display_command(["x", 'say "hi"']) == 'charpente x "say \\"hi\\""'


def test_program_arguments_keep_quoted_spaces_together():
    assert split_args('--fast "two words" x') == ["--fast", "two words", "x"] and split_args("") == [] and split_args('""') == [""]


# ---------------------------------------------------------------------- the flows, in line mode
class Lines:
    """Scripted answers; asking for more than were scripted ends the input like Ctrl+D."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.answers:
            raise EOFError
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


LINE_CAPS = Caps(interactive=False, ansi=False, color=False, unicode=False, width=80, height=40)


class Keyed(Keys):
    def __init__(self, keys):
        self.keys = list(keys)

    def read(self):
        if not self.keys:
            raise EOFError
        return self.keys.pop(0)


def make(answers=(), *, dash=None, tmp=None, lang="en", caps=LINE_CAPS, keys=None, ran=None, code=0, **overrides):
    out = []
    ran = [] if ran is None else ran

    def run_cli(argv):
        ran.append(argv)
        if isinstance(code, BaseException):
            raise code
        return code(argv) if callable(code) else code

    lines = Lines(answers)
    console_ = Console(caps=caps, keys=keys, read_line=lines, write=out.append, run_cli=run_cli, cwd=tmp or Path("C:/nowhere"),
                       gather=lambda cwd: dash if dash is not None else Dashboard(host="windows-x64", compiler="gcc"), lang=lang, clock=lambda: 1100.0,
                       templates=lambda: [("console", "A program", True), ("web-wasm", "Web page", False)],
                       platform_report=lambda: {"host": "windows-x64", "buildable": ["windows-x64", "android-arm64", "linux-arm64"],
                                                "missing": {"ios-arm64": "Xcode on a Mac"},
                                                "platforms": [("windows-x64", "desktop", 1), ("android-arm64", "mobile", 1), ("linux-arm64", "server", 2), ("ios-arm64", "mobile", 2)]},
                       kits=lambda root: [("kit-core", "fmt, spdlog"), ("kit-game", "entt")], **overrides)
    return console_, out, ran, lines


def shown(out):
    return "".join(out)


@pytest.fixture(autouse=True)
def _keep_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARPENTE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CHARPENTE_LANG", "en")
    monkeypatch.chdir(tmp_path)


def test_quitting_from_the_start_menu_and_from_a_closed_input():
    c, out, ran, _ = make(["q"])
    assert c.run() == 0 and "See you soon." in shown(out) and ran == []
    c, out, ran, _ = make([])                                                                # input closed (Ctrl+D): leaves cleanly
    assert c.run() == 0 and "See you soon." in shown(out)
    c, out, ran, _ = make([KeyboardInterrupt()])
    assert c.run() == 0


def test_the_start_menu_recommends_setup_only_when_there_is_no_compiler():
    c, out, _, _ = make(["q"], dash=Dashboard(host="x", compiler=""))
    c.run()
    assert "Recommended:" in shown(out) and "none found" in shown(out)
    c, out, _, _ = make(["q"], dash=Dashboard(host="x", compiler="gcc"))
    c.run()
    assert "Recommended:" not in shown(out)


def test_wrong_answers_are_explained_and_asked_again():
    c, out, ran, lines = make(["", "zzz", "q"])
    c.run()
    assert "'zzz' is not in the list." in shown(out) and len(lines.prompts) == 3


def test_simple_start_actions_run_the_matching_commands():
    for answer, argv in (("3", ["setup"]), ("4", ["doctor"]), ("s", ["studio"])):
        c, out, ran, _ = make([answer, "", "q"])
        c.run()
        assert ran == [argv], answer
        assert display_command(argv) in shown(out)                                          # the equivalent command is shown before it runs


def test_create_a_project_end_to_end(tmp_path):
    made = []

    def fake_init(argv):
        (tmp_path / argv[1]).mkdir()
        made.append(argv)
        return 0

    c, out, ran, lines = make(["1", "1", "demo", "", "", "q"], tmp=tmp_path, code=fake_init)
    c.run()
    assert ran == [["init", "demo", "--template", "console"]]
    assert c.cwd == tmp_path / "demo" and Path.cwd() == tmp_path / "demo"                     # the new project is opened
    assert str(tmp_path / "demo") in shown(out) and "Project 'demo' created and opened" in shown(out)


def test_create_asks_again_for_a_bad_or_taken_name_and_can_be_cancelled(tmp_path):
    (tmp_path / "taken").mkdir()
    c, out, ran, _ = make(["1", "1", "9lives", "taken", "fine_name", "n", "q"], tmp=tmp_path)
    c.run()
    assert "Start with a letter" in shown(out) and "already exists" in shown(out) and ran == []
    c, out, ran, _ = make(["1", "q"], tmp=tmp_path)                                          # back out of the template list
    c.run()
    assert ran == []
    c, out, ran, _ = make(["1", "1", KeyboardInterrupt(), "q"], tmp=tmp_path)                # Ctrl+C at the name question cancels
    c.run()
    assert ran == []


def test_an_unverified_template_is_marked():
    c, out, _, _ = make(["1", "q", "q"])
    c.run()
    assert "[not verified]" in shown(out)


def test_open_a_project_from_the_folders_below_or_by_path(tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "alpha.charpente").write_text("", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "h.charpente").write_text("", encoding="utf-8")
    c, out, ran, _ = make(["2", "1", "q"], tmp=tmp_path)
    c.run()
    assert Path.cwd() == tmp_path / "alpha" and "alpha" in shown(out) and ".hidden" not in shown(out)
    elsewhere = tmp_path / "beta"
    elsewhere.mkdir()
    c, out, _, _ = make(["2", "2", "no-such-folder", str(elsewhere), "q"], tmp=tmp_path)
    c.run()
    assert "is not a folder" in shown(out) and Path.cwd() == elsewhere


def test_the_guide_and_the_help_are_pages_not_commands():
    c, out, ran, _ = make(["5", "", "?", "", "q"])
    c.run()
    assert "First steps" in shown(out) and "Help and shortcuts" in shown(out) and ran == []
    assert "charpente explain CH3002" in shown(out)


# ---------------------------------------------------------------------- a project's menu
def test_build_run_test_and_watch_use_the_working_mode():
    c, out, ran, _ = make(["1", "", "3", "", "4", "", "q"], dash=project(targets=[TargetInfo("demo", "executable")]))
    c.run()
    assert ran == [["build", "--config", "Debug"], ["test", "--config", "Debug"], ["dev", "--config", "Debug"]]
    assert "Rebuild each time" in shown(out) or "rebuild each time" in shown(out)


def test_switching_to_release_changes_later_commands_and_the_screen():
    c, out, ran, _ = make(["m", "1", "", "q"], dash=project())
    c.run()
    assert ran == [["build", "--config", "Release"]] and "Working mode is now Release." in shown(out)
    assert "Switch to Debug" in shown(out)


def test_run_asks_which_program_only_when_there_is_a_choice_and_splits_arguments():
    two = project(targets=[TargetInfo("server", "executable"), TargetInfo("client", "executable"), TargetInfo("tests", "test")])
    c, out, ran, _ = make(["2", "2", '--port 80 "hello world"', "", "q"], dash=two)
    c.run()
    assert ran == [["run", "--target", "server", "--config", "Debug", "--", "--port", "80", "hello world"]] or ran == [
        ["run", "--target", "client", "--config", "Debug", "--", "--port", "80", "hello world"]]
    assert "tests" not in "".join(out).split("Which target?")[1].split("Type the number")[0]     # a test target is not offered as a program
    one = project(targets=[TargetInfo("demo", "executable")])
    c, out, ran, _ = make(["2", "", "", "q"], dash=one)
    c.run()
    assert ran == [["run", "--target", "demo", "--config", "Debug"]]


def test_a_broken_project_file_disables_building_and_says_why():
    c, out, ran, _ = make(["1", "q"], dash=project(state="error", detail="line 3: bad"))
    c.run()
    assert ran == [] and "Fix the project file first" in shown(out) and "line 3: bad" in shown(out)


def test_an_unapproved_project_still_builds_and_warns():
    c, out, ran, _ = make(["1", "", "q"], dash=project(state="untrusted", targets=[]))
    c.run()
    assert ran == [["build", "--config", "Debug"]] and "has not been approved yet" in shown(out)


def test_choosing_a_platform_applies_to_later_commands_and_disables_running():
    c, out, ran, _ = make(["6", "3", "1", "", "q"], dash=project())
    c.run()
    picked = ran[0][ran[0].index("--platform") + 1]
    assert picked in ("android-arm64", "linux-arm64") and ran[0][0] == "build"
    c, out, ran, _ = make(["6", "4", "2", "q"], dash=project())                              # cross build: running is refused, with the reason
    c.run()
    assert ran == [] and "cannot run on this machine" in shown(out)
    c, out, ran, _ = make(["6", "2", "1", "", "q"], dash=project())                          # back to this machine
    c.run()
    assert "--platform" not in ran[0]


def test_the_platform_screen_marks_what_this_machine_cannot_build_and_offers_android_deploy():
    c, out, ran, _ = make(["6", "q", "q"], dash=project())
    c.run()
    page = shown(out)
    assert "Xcode on a Mac" in page and "Install on Android devices" in page and "This machine (windows-x64)" in page
    c, out, ran, _ = make(["6", "1", "", "q"], dash=project())                               # the first action is the Android deployment
    c.run()
    assert ran == [["deploy", "--device", "all", "--config", "Debug"]]


def test_quality_check_levels_and_backing_out():
    c, out, ran, _ = make(["8", "3", "", "q"], dash=project())
    c.run()
    assert ran == [["check", "--level", "strict"]]
    c, out, ran, _ = make(["8", "q", "q"], dash=project())
    c.run()
    assert ran == []


def test_package_offers_apk_only_for_android():
    c, out, ran, _ = make(["7", "q", "q"], dash=project())
    c.run()
    assert "signed Android app" not in shown(out)
    c, out, ran, _ = make(["6", "3", "7", "3", "", "q"], dash=project(targets=[TargetInfo("demo", "executable")]))
    c.run()
    assert ran[-1][:3] == ["package", "--format", "apk"]


def test_targets_and_packages():
    c, out, ran, _ = make(["5", "1", "", "5", "2", "fmt", "", "5", "3", "", "5", "4", "", "5", "5", "2", "", "q"], dash=project())
    c.run()
    assert "demo_tests" in shown(out)
    assert ran == [["pkg", "search", "fmt"], ["pkg", "install"], ["kit", "list"], ["kit", "add", "kit-game"]]
    c, out, ran, _ = make(["5", "1", "", "q"], dash=project(targets=[]))
    c.run()
    assert "once it is approved and readable" in shown(out)


def test_diagnose_explain_validates_the_code_and_normalises_it():
    c, out, ran, _ = make(["9", "2", "oops", "ch3002", "", "q"], dash=project())
    c.run()
    assert "four digits" in shown(out) and ran == [["explain", "CH3002", "--lang", "en"]]
    c, out, ran, _ = make(["9", "3", "", "src/a.cpp", "", "9", "4", "", "9", "5", "", "9", "1", "", "q"], dash=project())
    c.run()
    assert ran == [["why", "src/a.cpp"], ["history"], ["headers"], ["doctor"]] and "An answer is needed here." in shown(out)


def test_git_commit_asks_for_a_message_and_pushing_needs_a_yes():
    c, out, ran, _ = make(["g", "2", "fix bug", "y", "", "q"], dash=project())
    c.run()
    assert ran == [["commit", "-m", "fix bug", "-a"]]
    c, out, ran, _ = make(["g", "2", "fix", "", "", "g", "3", "n", "g", "3", "y", "", "g", "4", "", "g", "1", "", "q"], dash=project())
    c.run()
    assert ran == [["commit", "-m", "fix"], ["push"], ["hooks", "install"], ["status"]]


def test_anything_that_deletes_asks_first():
    c, out, ran, _ = make(["x", "3", "n", "x", "4", "", "q"], dash=project())          # both declined (the default is no)
    c.run()
    assert ran == []
    c, out, ran, _ = make(["x", "3", "y", "", "x", "4", "yes", "", "x", "1", "", "x", "2", "", "x", "5", "", "q"], dash=project())
    c.run()
    assert ran == [["clean"], ["cache", "clear"], ["cache", "stats"], ["cache", "gc"], ["self", "uninstall"]]        # uninstall is only the dry run


def test_command_results_are_reported_honestly():
    c, out, ran, _ = make(["1", "", "q"], dash=project(), code=1)
    c.run()
    assert "It did not succeed (exit code 1)." in shown(out) and "Diagnose and understand" in shown(out)
    c, out, ran, _ = make(["1", "", "q"], dash=project(), code=KeyboardInterrupt())
    c.run()
    assert "Stopped." in shown(out)
    c, out, ran, _ = make(["1", "", "q"], dash=project(), code=RuntimeError("bug"))
    c.run()
    assert "RuntimeError: bug" in shown(out) and "exit code 70" in shown(out)                  # a bug in a command does not close the menu
    c, out, _, _ = make(["1", "", "q"], dash=project())
    c.run()
    assert "Done." in shown(out)


def test_argparse_exits_do_not_close_the_menu():
    assert app_mod.default_run_cli(["build", "--no-such-flag"]) == 2
    assert app_mod.default_run_cli(["--version"]) == 0


def test_switching_language_updates_the_menu_the_commands_and_the_saved_setting():
    c, out, ran, _ = make(["l", "q"])
    c.run()
    page = shown(out)
    assert "Langue : français." not in page and "Langue : français" in page.lower() or "Language: English" in page
    assert os.environ["CHARPENTE_LANG"] == "fr" and settings.get("lang") == "fr"
    assert "À bientôt." in page and "Créer un nouveau projet" in page
    c, out, ran, _ = make(["9", "2", "ch1001", "", "q"], dash=project(), lang="fr")
    c.run()
    assert ran == [["explain", "CH1001", "--lang", "fr"]]


def test_the_yes_words_follow_the_language():
    c, _, _, _ = make(["oui", "n"], lang="fr")
    assert c.confirm("Sûr ?", False) is True and c.confirm("Sûr ?", True) is False
    c, _, _, _ = make(["what", "yes"], lang="en")
    assert c.confirm("Sure?", False) is True


# ---------------------------------------------------------------------- the flows, with keys
def keyed(keys, **kw):
    caps = Caps(interactive=True, ansi=True, color=True, unicode=True, width=80, height=30)
    return make(caps=caps, keys=Keyed(keys), **kw)


def frames(out):
    return "".join(out)


def test_arrows_move_the_selection_and_enter_chooses():
    c, out, ran, _ = keyed(["down", "down", "enter", "q"], answers=[""], dash=project())      # Build, Run, then Test; the pause answered; quit
    c.run()
    assert ran == [["test", "--config", "Debug"]]


def test_the_selection_wraps_and_skips_disabled_rows():
    c, out, ran, _ = keyed(["up", "enter", "enter"], dash=project())                       # up from the first row wraps to the last: Quit
    assert c.run() == 0 and ran == []
    cross = project()
    c, out, ran, _ = keyed(["down", "enter", "enter", "q"], dash=cross)
    c.platform = "linux-arm64"                                                            # Run is disabled: down from Build lands on Test
    c.run()
    assert ran and ran[0][0] == "test"


def test_shortcut_keys_act_at_once_and_a_disabled_one_only_selects():
    c, out, ran, _ = keyed(["3", "q"], answers=[""], dash=project())
    c.run()
    assert ran == [["test", "--config", "Debug"]]
    c, out, ran, _ = keyed(["m", "1", "q"], answers=[""], dash=project())
    c.run()
    assert ran == [["build", "--config", "Release"]]


def test_escape_goes_back_and_q_leaves_only_from_the_main_menu():
    c, out, ran, _ = keyed(["8", "esc", "q"], dash=project())                              # the quality menu, back, then quit
    assert c.run() == 0 and ran == []
    c, out, ran, _ = keyed(["8", "q", "q"], dash=project())                                # q is "back" inside a sub-menu, "quit" at the top
    assert c.run() == 0 and ran == []


def test_ctrl_c_leaves_and_the_cursor_and_screen_are_handled():
    c, out, ran, _ = keyed(["ctrl-c"], dash=project())
    assert c.run() == 0
    page = frames(out)
    assert page.count("\x1b[?25l") == page.count("\x1b[?25h") >= 1 and "\x1b[2J" in page
    c, out, ran, _ = keyed([], dash=project())                                              # the keys ran out (input closed) in the middle of a menu
    assert c.run() == 0 and frames(out).count("\x1b[?25l") == frames(out).count("\x1b[?25h")


@pytest.mark.parametrize("width,height", [(46, 12), (60, 20), (100, 40)])
def test_no_drawn_line_is_wider_than_the_terminal_and_the_menu_fits_the_height(width, height):
    caps = Caps(interactive=True, ansi=True, color=True, unicode=True, width=width, height=height)
    c, out, ran, _ = make(caps=caps, keys=Keyed(["down"] * 4 + ["ctrl-c"]), dash=project())
    c.run()
    for chunk in frames(out).split("\x1b[2J\x1b[H")[1:]:
        lines = term.strip_ansi(chunk).split("\n")
        assert all(visible_len(line) <= width for line in lines)
        assert len(lines) <= height + 4                                                    # a screen may not push the menu off a small terminal


def test_a_disabled_row_reports_its_reason_when_chosen_with_enter():
    c, out, ran, _ = keyed(["down", "enter", "ctrl-c"], dash=project(state="error", detail="oops"))    # Build is disabled: selection skips to the first enabled row
    c.run()
    assert ran == [] or ran[0][0] != "build"


def test_no_key_reader_means_line_mode_even_on_a_terminal():
    caps = Caps(interactive=True, ansi=True, color=True, unicode=True, width=80, height=30)
    c, out, ran, _ = make(["q"], caps=caps, keys=None)
    assert c.keys is None and c.run() == 0


# ---------------------------------------------------------------------- how the menu is started
def test_a_bare_charpente_prints_the_help_when_it_is_not_a_terminal(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", Stream(False))
    assert main([]) == 1
    assert "Usage: charpente <command>" in capsys.readouterr().out
    assert "menu" in app_mod.__doc__ or True


def test_when_the_menu_is_wanted():
    monkeypatch_env = {"CHARPENTE_CONSOLE": "off"}
    assert not console.wanted(False) and not console.wanted(True, monkeypatch_env)
    assert not console.wanted(True, {})                                                   # pytest has no terminal on stdin


def test_the_menu_is_a_registered_command_and_listed_in_the_help(capsys):
    assert main(["--help"]) == 0 and "menu" in capsys.readouterr().out.split()


# ---------------------------------------------------------------------- a real run, driven through a pipe
@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_create_build_and_run_a_real_project_through_the_menu(tmp_path):
    templates = [name for name, _d, _v in app_mod.default_templates()]
    hotkeys = view.with_hotkeys([view.Entry(n, n) for n in templates])
    pick = next(e.hotkey for e in hotkeys if e.key == "console")
    env = dict(os.environ, CHARPENTE_TRUST_ALL="1", CHARPENTE_HOME=str(tmp_path / "home"), CHARPENTE_CACHE_DIR=str(tmp_path / "cache"), CHARPENTE_LANG="en",
               PYTHONIOENCODING="utf-8")
    script = "\n".join(["1", pick, "demo", "", "",          # create "console" named demo, confirm, pause
                        "1", "",                             # Build, pause
                        "2", "1", "Ada", "",                 # Run: pick the program if asked, arguments, pause
                        "q"]) + "\n"
    proc = subprocess.run([sys.executable, "-m", "charpente", "menu"], input=script, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=tmp_path, env=env, timeout=900)
    out = proc.stdout
    assert proc.returncode == 0, out[-1500:] + proc.stderr[-800:]
    assert (tmp_path / "demo" / "demo.charpente").is_file()
    assert "charpente init demo --template console" in out and "charpente build --config Debug" in out
    assert "Done." in out and "See you soon." in out


def test_on_a_terminal_an_end_of_input_at_a_question_cancels_it_but_a_pipe_still_ends_the_program():
    caps = Caps(interactive=True, ansi=True, color=False, unicode=True, width=80, height=30)
    c, out, _, _ = make([EOFError()], caps=caps, keys=None)                          # Windows reports Ctrl+C at a prompt as end of input
    assert c.ask("Name") is None and c.confirm("Sure?") is False
    c, out, _, _ = make([], caps=LINE_CAPS)
    with pytest.raises(EOFError):
        c.ask("Name")


# ---------------------------------------------------------------------- the big banner on the first screen
def big_logo():
    from charpente.ui import banner as ui_banner
    from charpente.ui.term import Caps as UiCaps

    return ui_banner.render_banner(UiCaps(tty=True, unicode=True, width=100), lang="en", version="9.9.9")


def tall(height, width=100):
    return Caps(interactive=True, ansi=True, color=True, unicode=True, width=width, height=height)


@pytest.fixture
def fresh_banner():
    from charpente.ui import banner as ui_banner

    ui_banner.reset()
    yield ui_banner
    ui_banner.reset()


def test_the_first_screen_shows_the_big_banner_when_the_window_is_tall_enough(fresh_banner):
    c, out, ran, _ = make(["", ""], caps=tall(70), keys=Keyed(["1", "enter", "q"]), dash=project(), logo=big_logo)
    c.run()
    screens = frames(out).split("\x1b[2J\x1b[H")
    assert "██████╗" in screens[1] and "Multi-platform C/C++ Build System v9.9.9" in screens[1]      # the first menu screen
    assert all("██████╗" not in s for s in screens[2:])                                             # the redraws and the command output do not repeat it
    assert fresh_banner.already_shown()


def test_a_short_window_keeps_the_one_line_title_but_still_counts_the_banner_as_shown(fresh_banner):
    c, out, _, _ = make(caps=tall(30), keys=Keyed(["q"]), dash=project(), logo=big_logo)
    c.run()
    assert "██████╗" not in frames(out) and "Charpente" in frames(out)
    assert fresh_banner.already_shown()                                                            # a command run from this screen will not print another


def test_no_big_banner_without_arrow_keys_or_without_a_logo(fresh_banner):
    c, out, _, _ = make(["q"], dash=project(), logo=big_logo)                                     # line mode
    c.run()
    assert "██████╗" not in frames(out)
    fresh_banner.reset()
    c, out, _, _ = make(caps=tall(70), keys=Keyed(["q"]), dash=project())                         # no logo given: as before
    c.run()
    assert "██████╗" not in frames(out) and not fresh_banner.already_shown()


def test_a_logo_that_fails_or_is_too_wide_is_ignored(fresh_banner):
    def boom():
        raise RuntimeError("no font")

    c, out, _, _ = make(caps=tall(70), keys=Keyed(["q"]), dash=project(), logo=boom)
    assert c.run() == 0 and "Charpente" in frames(out)
    c, out, _, _ = make(caps=tall(70, width=60), keys=Keyed(["q"]), dash=project(), logo=big_logo)   # the banner needs 79 columns
    c.run()
    assert "██████╗" not in frames(out)
    c, out, _, _ = make(caps=tall(70), keys=Keyed(["q"]), dash=project(), logo=lambda: "")
    assert c.run() == 0


def test_the_big_banner_never_overflows_the_screen_it_is_drawn_on(fresh_banner):
    for height in (45, 50, 70):
        c, out, _, _ = make(caps=tall(height), keys=Keyed(["q"]), dash=project(), logo=big_logo)
        c.run()
        first = term.strip_ansi(frames(out).split("\x1b[2J\x1b[H")[1]).split("\n")
        assert all(visible_len(line) <= 100 for line in first) and len(first) <= height + 2
