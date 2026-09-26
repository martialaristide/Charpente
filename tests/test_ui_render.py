"""charpente.ui.render: the styled build display driven by events, the way a real build drives it, and how a Session chooses it."""
import argparse
import io

import pytest
from helpers import GCC, FakeToolchain, make_workspace

from charpente import builder
from charpente.commands import build as build_cmd
from charpente.commands._session import Session
from charpente.dsl.model import OS, Kind, Target, Workspace
from charpente.events import EventBus
from charpente.ui import render
from charpente.ui.term import NONE, TRUE, Caps, strip_ansi, visible_len


class Out(io.StringIO):
    def __init__(self, encoding="utf-8"):
        super().__init__()
        self._encoding = encoding

    encoding = "utf-8"


def caps(color=NONE, width=100, tty=True, unicode=True):
    return Caps(tty=tty, color=color, unicode=unicode, width=width)


def feed(events, *, lang="fr", names=("moteur", "shaders", "app", "tests_moteur"), c=None, out=None, context=None):
    """Send (type, payload) events through a bus to a StyledRenderer and return what it printed."""
    out = out if out is not None else Out()
    bus = EventBus()
    renderer = render.StyledRenderer(bus, out=out, caps=c or caps(), lang=lang, target_names=names, env={}, context=context or {"platform": "linux-x64", "tools": "gcc 13.2.0"})
    for kind, payload in events:
        bus.emit(kind, **payload)
    bus.flush()
    bus.close()
    return out.getvalue(), renderer


def screen(text):
    """What is left on the screen: for every line, only what follows the last carriage return (the transient bar is overwritten)."""
    return [line.split("\r")[-1] for line in text.split("\n")]


def session_events(ok=True, failed=False):
    events = [("session.started", {"command": "build", "argv": [], "cwd": "/w", "version": "0.13.0", "config": "Debug"}),
              ("workspace.loaded", {"name": "CasqueDemo", "path": "/w", "targets": 4}),
              ("graph.analyzed", {"actions": 8, "targets": 4, "critical_path": 1.0, "config": ""}),
              ("action.finished", {"action": "compile:moteur:a.cpp", "target": "moteur", "kind": "compile", "duration": 1.0, "outputs": ["/w/build/a.o"]}),
              ("action.finished", {"action": "archive:moteur", "target": "moteur", "kind": "archive", "duration": 0.5, "outputs": ["/w/build/Debug/moteur/libmoteur.a"]}),
              ("target.finished", {"target": "moteur", "duration": 2.4, "executed": 2, "cached": 0, "up_to_date": 0}),
              ("action.cache_hit", {"action": "compile:shaders:s.cpp", "target": "shaders", "kind": "compile"}),
              ("target.finished", {"target": "shaders", "duration": 0.0, "executed": 0, "cached": 1, "up_to_date": 0}),
              ("action.finished", {"action": "link:app", "target": "app", "kind": "link", "duration": 1.1, "outputs": ["/w/build/Debug/app/app"]}),
              ("diagnostic.emitted", {"file": "/w/app.cpp", "line": 3, "column": 1, "severity": "warning", "message": "unused variable", "action": "link:app"}),
              ("diagnostic.emitted", {"file": "/w/app.cpp", "line": 5, "column": 1, "severity": "warning", "message": "unused", "action": "link:app"}),
              ("target.finished", {"target": "app", "duration": 1.1, "executed": 1, "cached": 0, "up_to_date": 0})]
    if failed:
        events += [("action.failed", {"action": "link:tests_moteur", "target": "tests_moteur", "kind": "link", "returncode": 1, "duration": 0.1, "output": "x"}),
                   ("diagnostic.emitted", {"file": "/w/t.cpp", "line": 9, "column": 1, "severity": "error", "message": "undefined reference to 'f'", "action": "link:tests_moteur"}),
                   ("target.failed", {"target": "tests_moteur", "error": "ld: undefined reference to 'f'\nld: final link failed\ncollect2: error", "code": "CH3003"})]
    events.append(("session.finished", {"ok": ok and not failed, "duration": 4.2, "exit_code": 0 if ok and not failed else 1}))
    return events


# ---------------------------------------------------------------------- a whole session
def test_a_session_prints_the_stages_the_targets_the_warnings_and_the_result_box():
    text, _ = feed(session_events(failed=True))
    lines = screen(text)
    assert "  ▸ Chargement de l'espace de travail" in lines
    assert "  espace CasqueDemo │ config Debug │ plateforme linux-x64 │ outils gcc 13.2.0" in lines
    assert "  ▸ Construction" in lines
    assert any(x.startswith("  ✔ moteur") and "build/Debug/moteur/libmoteur.a" in x and "2,4 s" in x for x in lines)
    assert any(x.startswith("  ◆ shaders") and "servi par le cache" in x for x in lines)
    assert any(x.startswith("  ✔ app") and "build/Debug/app/app" in x for x in lines)
    assert "  ▲ app : 2 avertissements, voir charpente build -v" in lines
    failure = next(x for x in lines if x.startswith("  ✘ tests_moteur"))
    assert "undefined reference to 'f'" in failure and "[CH3003]" in failure
    assert any("ld: final link failed" in x for x in lines)
    assert any("╭─ Résultat" in x for x in lines) and "charpente why tests_moteur" in text
    assert any("3 réussies, 1 échec" in x for x in lines) and any("cache" in x and "sur 8" in x for x in lines) and any("4,2 s" in x for x in lines)
    assert any("cache    1 action sur 8" in x for x in lines)                                # 1 action, not "1 actions"


def test_the_order_is_the_order_of_the_build():
    text, _ = feed(session_events(failed=True))
    positions = [text.index(marker) for marker in ("Chargement", "Construction", "✔ moteur", "◆ shaders", "✔ app", "▲ app", "✘ tests_moteur", "Résultat")]
    assert positions == sorted(positions)


def test_a_successful_session_has_no_next_step_row_and_a_green_box():
    text, _ = feed(session_events(ok=True), c=caps(TRUE))
    plain = "\n".join(strip_ansi(x) for x in screen(text))
    assert "suite" not in plain and "échec" not in plain and "3 réussies" in plain
    top = next(line for line in text.split("\n") if "Résultat" in line)
    assert "38;2;72;200;120" in top                                                  # the box top line is green


def test_a_failed_session_has_a_red_box():
    text, _ = feed(session_events(failed=True), c=caps(TRUE))
    top = next(line for line in text.split("\n") if "Résultat" in line)
    assert "38;2;240;84;84" in top


def test_english():
    text, _ = feed(session_events(failed=True), lang="en")
    assert "Loading the workspace" in text and "workspace CasqueDemo" in text and "Building" in text and "2 warnings" in text
    assert "3 succeeded, 1 failed" in text and "duration" in text and "4.2 s" in text and "next" in text and "served by the cache" in text


def test_the_bar_is_drawn_while_building_and_the_final_bar_is_kept():
    text, _ = feed(session_events(), c=caps(NONE, tty=True))
    assert "\r" in text                                                                  # a transient bar on a terminal
    assert text.count("━") > 0 and "8/8" in text.replace(" ", "") or "/8" in text
    final = [x for x in text.split("\n") if x.strip().endswith("/8") and "━" in x]
    assert final, "the final progress line is kept before the result box"


def test_no_bar_is_drawn_off_a_terminal():
    text, _ = feed(session_events(), c=caps(NONE, tty=False))
    assert "\r" not in text and "/8" in text                                              # only the final line


def test_the_transient_bar_never_leaves_stray_text_before_a_line():
    text, _ = feed(session_events(), c=caps(NONE, tty=True, width=60))
    for chunk in text.split("\n"):
        visible = chunk.split("\r")[-1]                                                    # what is left on the line after the last carriage return
        assert visible_len(visible) <= 60


# ---------------------------------------------------------------------- degradations
def test_without_colour_there_is_no_escape_sequence_at_all():
    text, _ = feed(session_events(failed=True), c=caps(NONE))
    assert "\x1b" not in text


def test_the_ascii_look():
    text, _ = feed(session_events(failed=True), c=caps(NONE, unicode=False))
    assert all(ord(ch) < 128 for ch in text)
    assert "[ok] moteur" in text and "[=]  shaders" in text and "[x]  tests_moteur" in text and "[!]  app" in text and "+- Resultat" in text


@pytest.mark.parametrize("width", [20, 40, 60, 100])
def test_no_line_is_wider_than_the_terminal(width):
    text, _ = feed(session_events(failed=True), c=caps(TRUE, width))
    for line in text.replace("\r", "\n").split("\n"):
        assert visible_len(line) <= width - 1, (width, strip_ansi(line))              # one column less than the terminal: the last column is never written


def test_a_long_error_is_cut_with_a_count_of_what_was_left_out():
    error = "\n".join(f"line {i}" for i in range(40))
    events = [("graph.analyzed", {"actions": 1, "targets": 1, "critical_path": 0.0, "config": ""}), ("target.failed", {"target": "app", "error": error, "code": None}),
              ("session.finished", {"ok": False, "duration": 1.0, "exit_code": 1})]
    text, _ = feed(events)
    assert "line 0" in text and "line 11" in text and "line 12" not in text and "(+28)" in text


def test_compiler_text_that_no_warning_accounts_for_is_still_shown():
    events = [("graph.analyzed", {"actions": 1, "targets": 1, "critical_path": 0.0, "config": ""}),
              ("action.output", {"action": "rule:gen", "target": "app", "stream": "stdout", "text": "generated version.h\n"}),
              ("action.finished", {"action": "rule:gen", "target": "app", "kind": "rule", "duration": 0.1, "outputs": []}),
              ("session.finished", {"ok": True, "duration": 1.0, "exit_code": 0})]
    assert "generated version.h" in feed(events)[0]


def test_warning_text_is_summarised_not_repeated():
    events = [("graph.analyzed", {"actions": 1, "targets": 1, "critical_path": 0.0, "config": ""}),
              ("action.output", {"action": "compile:app:a", "target": "app", "stream": "stderr", "text": "a.cpp:1: warning: unused\n"}),
              ("diagnostic.emitted", {"file": "a.cpp", "line": 1, "column": 1, "severity": "warning", "message": "unused", "action": "compile:app:a"}),
              ("action.finished", {"action": "compile:app:a", "target": "app", "kind": "compile", "duration": 0.1, "outputs": ["a.o"]}),
              ("target.finished", {"target": "app", "duration": 0.1, "executed": 1, "cached": 0, "up_to_date": 0}),
              ("session.finished", {"ok": True, "duration": 1.0, "exit_code": 0})]
    text = feed(events)[0]
    assert "1 avertissement" in text and "a.cpp:1: warning: unused" not in text


def test_an_interrupted_build_says_so():
    events = [("graph.analyzed", {"actions": 10, "targets": 2, "critical_path": 0.0, "config": ""}), ("session.interrupted", {"reason": "keyboard"}),
              ("session.finished", {"ok": False, "duration": 1.0, "exit_code": 130})]
    text = feed(events)[0]
    assert "construction interrompue" in text and "╭─ Résultat" in text


def test_nothing_built_means_no_summary():
    events = [("session.started", {"command": "deploy", "argv": [], "cwd": "/w", "version": "0.13.0", "config": "Debug"}), ("session.finished", {"ok": False, "duration": 0.1, "exit_code": 1})]
    assert "Résultat" not in feed(events)[0]


def test_an_empty_workspace_says_there_was_nothing_to_build():
    events = [("graph.analyzed", {"actions": 0, "targets": 0, "critical_path": 0.0, "config": ""}), ("session.finished", {"ok": True, "duration": 0.1, "exit_code": 0})]
    assert "rien à construire" in feed(events)[0]


def test_a_hint_is_shown_muted():
    events = [("hint.emitted", {"code": "resource", "message": "2000 MB of memory are available"}), ("session.finished", {"ok": True, "duration": 0.1, "exit_code": 0})]
    assert "  hint: 2000 MB of memory are available" in feed(events)[0]


# ---------------------------------------------------------------------- it never fails a build
def test_a_broken_output_stops_the_display_but_not_the_build():
    class Broken(Out):
        def write(self, text):
            raise BrokenPipeError("pipe closed")

    text, renderer = feed(session_events(failed=True), out=Broken())
    assert text == "" and renderer._dead


def test_a_closed_output_is_survived():
    out = Out()
    bus = EventBus()
    renderer = render.StyledRenderer(bus, out=out, caps=caps(), lang="fr", env={})
    out.close()
    for kind, payload in session_events(failed=True):
        bus.emit(kind, **payload)
    bus.flush()
    bus.close()
    assert renderer._dead                                                                  # nothing raised; the display simply stopped


def test_a_character_the_terminal_cannot_write_is_replaced_not_fatal():
    class Cp1252(Out):
        encoding = "cp1252"

        def write(self, text):
            text.encode("cp1252")
            return super().write(text)

    events = [("workspace.loaded", {"name": "日本語", "path": "/w", "targets": 1}), ("session.finished", {"ok": True, "duration": 0.1, "exit_code": 0})]
    assert "espace" in feed(events, out=Cp1252(), c=caps(NONE, unicode=False))[0]


def test_malformed_events_are_ignored_not_fatal():
    class Fake:
        def __init__(self, type, payload):
            self.type, self.payload = type, payload

    renderer = render.StyledRenderer(EventBus(), out=Out(), caps=caps(), lang="fr", env={})
    for kind, payload in (("graph.analyzed", {"actions": "many"}), ("target.finished", {"target": "app", "duration": "slow", "executed": None, "cached": None}),
                          ("session.finished", {"ok": True, "duration": None}), ("diagnostic.emitted", {}), ("action.finished", {}), ("nonsense", {"a": 1}),
                          ("workspace.loaded", {}), ("target.failed", {"error": None})):
        renderer._on_event(Fake(kind, payload))                                            # type: ignore[arg-type]   # must not raise


def test_finish_removes_the_bar_and_is_idempotent():
    out = Out()
    bus = EventBus()
    renderer = render.StyledRenderer(bus, out=out, caps=caps(NONE, tty=True), lang="en", env={})
    bus.emit("graph.analyzed", actions=4, targets=1, critical_path=0.0, config="")
    bus.flush()
    assert "\r" in out.getvalue()
    renderer.finish()
    renderer.finish()
    assert out.getvalue().endswith("\r")
    bus.close()


# ---------------------------------------------------------------------- helpers
def test_display_path_is_relative_when_below_the_folder_and_uses_forward_slashes(tmp_path):
    assert render.display_path(str(tmp_path / "build" / "app.exe"), tmp_path) == "build/app.exe"
    assert "/" in render.display_path("C:\\elsewhere\\x.exe", tmp_path) and "\\" not in render.display_path("C:\\elsewhere\\x.exe", tmp_path)
    assert render.display_path("rel/x", None) == "rel/x"


@pytest.mark.parametrize("line,expected", [("g++.exe (Rev5, Built by MSYS2 project) 16.1.0", "16.1.0"), ("clang version 17.0.6 (x)", "17.0.6"), ("zig 0.16.0", "0.16.0"), ("weird", None)])
def test_tool_labels(line, expected):
    assert render.tool_label("gcc", line) == (f"gcc {expected}" if expected else "gcc")
    assert render.tool_label("gcc") == "gcc"


def test_resolve_tool_label_never_raises():
    class Broken:
        name = "broken"
        cxx_compiler = "/no/such/compiler"

    assert render.resolve_tool_label(Broken()).startswith("broken")
    assert render.resolve_tool_label(object()) == ""


# ---------------------------------------------------------------------- a Session chooses it
def parsed(**kw):
    values = dict(output="auto", verbose=False, platform=None)
    values.update(kw)
    return argparse.Namespace(**values)


def test_auto_uses_the_styled_display_on_a_terminal(monkeypatch):
    monkeypatch.setattr(render, "styled_wanted", lambda *a, **k: True)
    session = Session("build", parsed(), None)
    assert session.fancy and isinstance(session.renderer, render.StyledRenderer)
    session.finish(True)


def test_auto_is_plain_off_a_terminal_and_with_verbose(monkeypatch):
    monkeypatch.setattr(render, "styled_wanted", lambda *a, **k: False)
    session = Session("build", parsed(), None)
    assert not session.fancy and session.renderer is None
    session.finish(True)
    monkeypatch.setattr(render, "styled_wanted", lambda *a, **k: True)
    verbose = Session("build", parsed(verbose=True), None)
    assert not verbose.fancy and verbose.renderer is None
    verbose.finish(True)


def test_plain_and_jsonl_never_use_the_styled_display(monkeypatch):
    monkeypatch.setattr(render, "styled_wanted", lambda *a, **k: True)
    for mode in ("plain", "jsonl"):
        s = Session("build", parsed(output=mode), None)
        assert not s.fancy and s.renderer is None
        s.finish(True)
    assert Session("build", argparse.Namespace(), None).fancy is False                    # commands without --output stay plain


def test_styled_wanted_needs_a_real_terminal_no_ci_and_no_dumb_terminal():
    class Tty(io.StringIO):
        encoding = "utf-8"

        def isatty(self):
            return True

    assert render.styled_wanted(Tty(), {}) and not render.styled_wanted(io.StringIO(), {})
    assert not render.styled_wanted(Tty(), {"CI": "1"}) and not render.styled_wanted(Tty(), {"TERM": "dumb"})


def test_a_real_build_through_a_styled_session(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render, "styled_wanted", lambda *a, **k: True)
    monkeypatch.setenv("NO_COLOR", "1")
    ws = Workspace(name="Demo", location=tmp_path)
    for rel, text in {"core/core.cpp": "int core();", "app/main.cpp": "int main() {}"}.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    ws.add_target(Target(name="core", kind=Kind.STATIC_LIBRARY, source_patterns=["core/*.cpp"], location=tmp_path))
    ws.add_target(Target(name="app", depends_on=["core"], source_patterns=["app/*.cpp"], location=tmp_path))
    with Session("build", parsed(), ws, toolchain="gcc", config="Debug", tools="gcc 13.2.0") as session:
        assert session.fancy
        result = builder.build_workspace(ws, GCC, OS.LINUX, config="Debug", run=FakeToolchain(), jobs=1, bus=session.bus, use_cache=False)
        build_cmd.print_result_lines(session, result, toolchain_name="gcc")
        session.finish(result.ok, 0)
    out = capsys.readouterr().out
    assert "▸ Building" in out and "workspace Demo" in out and "tools gcc 13.2.0" in out and "╭─" in out
    lines = screen(out)
    assert sum(1 for x in lines if x.startswith("  ✔ core")) == 1 and sum(1 for x in lines if x.startswith("  ✔ app")) == 1                       # each target once: the command did not print its own lines as well
    assert "[ok]" not in out and "Done in" not in out and "\x1b" not in out


def test_the_command_still_prints_its_own_lines_when_the_display_is_not_styled(tmp_path, capsys):
    ws = make_workspace(tmp_path, {"main.cpp": "int main() {}"})
    with Session("build", parsed(output="plain"), ws, toolchain="gcc", config="Debug") as session:
        result = builder.build_workspace(ws, GCC, OS.LINUX, config="Debug", run=FakeToolchain(), jobs=1, bus=session.bus, use_cache=False)
        build_cmd.print_result_lines(session, result, toolchain_name="gcc")
        session.finish(result.ok, 0)
    out = capsys.readouterr().out
    assert "[ok]" in out and "Done in" in out and "▸" not in out
