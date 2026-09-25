import io
import json
import sys
import time

import pytest

from charpente import hooks
from charpente.cli import main
from charpente.dsl.api import Workspace as DslWorkspace
from charpente.dsl.trust import ensure_trusted_digest
from charpente.errors import ChError
from charpente.events import EventBus
from charpente.output import github as gh
from charpente.output import rich_renderer
from charpente.platform import host_os
from charpente.toolchains import NoToolchainFoundError, pick_default


def _has_compiler() -> bool:
    try:
        pick_default(host_os())
        return True
    except NoToolchainFoundError:
        return False


requires_compiler = pytest.mark.skipif(not _has_compiler(), reason="no C/C++ compiler on PATH")


def wait_for(predicate, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


# =================================================================== DSL hooks
def test_on_registers_hooks_and_rejects_non_events():
    ws = DslWorkspace("W")
    calls = []

    @ws.on(hooks.Event.BUILD_FINISHED)
    def summary(ev):
        calls.append(ev)

    assert ws.model.hooks == [(hooks.Event.BUILD_FINISHED, summary)]
    with pytest.raises(TypeError, match="Event"):
        ws.on("session.finished")


def emit_build(bus, ok=True, failed=0):
    bus.emit("session.started", command="build", argv=[], cwd="", version="x")
    bus.emit("target.started", target="t", actions=2)
    bus.emit("action.finished", action="a", target="t", kind="compile", duration=0.1)
    bus.emit("action.cache_hit", action="b", target="t", kind="compile")
    bus.emit("diagnostic.emitted", severity="warning", message="w")
    bus.emit("diagnostic.emitted", severity="error", message="e")
    bus.emit("diagnostic.emitted", severity="note", message="n")
    for _ in range(failed):
        bus.emit("target.failed", target="x", error="e")
    bus.emit("target.finished", target="t", duration=0.2, executed=1, cached=1, up_to_date=0)
    bus.emit("session.finished", ok=ok, duration=1.5)


def test_hook_runner_provides_session_totals_on_build_finished():
    bus = EventBus(strict=True)
    got = []
    hooks.HookRunner(bus, [(hooks.Event.BUILD_FINISHED, got.append)])
    emit_build(bus)
    bus.close()
    ev = got[0]
    assert ev.type == "session.finished" and ev.ok is True and ev.duration == 1.5
    assert (ev.targets_built, ev.actions_run, ev.cache_hits, ev.warnings, ev.errors) == (1, 1, 1, 1, 1)
    assert ev.targets_failed == 0


def test_hooks_see_only_the_events_they_asked_for_and_any_sees_all():
    bus = EventBus(strict=True)
    finished, everything = [], []
    hooks.HookRunner(bus, [(hooks.Event.TARGET_FINISHED, finished.append), (hooks.Event.ANY, everything.append)])
    emit_build(bus)
    bus.close()
    assert [e.target for e in finished] == ["t"] and finished[0].executed == 1
    assert len(everything) == 9


def test_a_failing_hook_is_reported_and_does_not_break_the_others():
    bus = EventBus(strict=True)
    errors, seen = [], []

    def boom(ev):
        raise RuntimeError("hook bug")

    hooks.HookRunner(bus, [(hooks.Event.BUILD_FINISHED, boom), (hooks.Event.BUILD_FINISHED, seen.append)],
                     on_error=errors.append)
    emit_build(bus)
    bus.close()
    assert len(seen) == 1 and len(errors) == 1 and "hook bug" in errors[0] and "boom" in errors[0]


def test_unknown_field_error_lists_the_available_fields():
    bus = EventBus(strict=True)
    got = []
    hooks.HookRunner(bus, [(hooks.Event.TARGET_STARTED, got.append)])
    bus.emit("target.started", target="t", actions=3)
    bus.close()
    with pytest.raises(AttributeError, match="targets_built|actions"):
        _ = got[0].targets_built
    assert got[0].actions == 3


def test_notify_prints_and_never_raises(capsys):
    hooks.notify("3 targets built")
    assert "[notify] 3 targets built" in capsys.readouterr().err


# ==================================================================== script hooks
def test_discover_scripts_by_event_name(tmp_path):
    d = tmp_path / ".charpente" / "hooks"
    d.mkdir(parents=True)
    (d / "session.finished.py").write_text("print(1)")
    (d / "session.finished.sh").write_text("echo 1")
    (d / "action.failed.py").write_text("print(2)")
    found = hooks.discover_scripts(tmp_path)
    assert sorted(found) == ["action.failed", "session.finished"] and len(found["session.finished"]) == 2
    assert hooks.discover_scripts(tmp_path / "nowhere") == {}


def test_scripts_digest_changes_with_content_and_names(tmp_path):
    d = tmp_path / ".charpente" / "hooks"
    d.mkdir(parents=True)
    (d / "a.py").write_text("1")
    before = hooks.scripts_digest(hooks.discover_scripts(tmp_path))
    (d / "a.py").write_text("2")
    assert hooks.scripts_digest(hooks.discover_scripts(tmp_path)) != before


def test_command_for_uses_explicit_interpreters_never_a_shell_string(tmp_path):
    py = tmp_path / "h.py"
    py.write_text("")
    assert hooks.command_for(py) == [sys.executable, str(py)]
    weird = tmp_path / "h.xyz"
    weird.write_text("")
    assert hooks.command_for(weird) is None


def test_script_hook_runs_with_the_event_on_stdin(tmp_path):
    d = tmp_path / ".charpente" / "hooks"
    d.mkdir(parents=True)
    out = tmp_path / "seen.json"
    (d / "session.finished.py").write_text(
        "import sys, os, json\n"
        f"data = json.load(sys.stdin)\n"
        f"open({str(out)!r}, 'w').write(json.dumps({{'type': data['type'], 'env': os.environ['CHARPENTE_EVENT'], "
        f"'ok': data['payload']['ok']}}))\n")
    bus = EventBus(strict=True)
    hooks.ScriptHooks(bus, hooks.discover_scripts(tmp_path), tmp_path)
    bus.emit("session.finished", ok=True, duration=0.1)
    bus.close()
    assert json.loads(out.read_text()) == {"type": "session.finished", "env": "session.finished", "ok": True}


def test_failing_and_unknown_scripts_are_reported_not_fatal(tmp_path):
    d = tmp_path / ".charpente" / "hooks"
    d.mkdir(parents=True)
    (d / "session.finished.py").write_text("import sys; sys.exit(3)")
    (d / "session.finished.xyz").write_text("")
    errors = []
    bus = EventBus(strict=True)
    hooks.ScriptHooks(bus, hooks.discover_scripts(tmp_path), tmp_path, on_error=errors.append)
    bus.emit("session.finished", ok=True, duration=0.1)
    bus.close()
    assert any("exited with 3" in e for e in errors) and any("unknown script type" in e for e in errors)


def test_hook_scripts_need_approval(tmp_path, monkeypatch):
    monkeypatch.delenv("CHARPENTE_TRUST_ALL", raising=False)
    assert ensure_trusted_digest("k", "d1", label="hook scripts") is False           # non-interactive: skipped
    assert ensure_trusted_digest("k", "d1", label="hook scripts", prompt=lambda q: "n") is False
    assert ensure_trusted_digest("k", "d1", label="hook scripts", prompt=lambda q: "y") is True
    assert ensure_trusted_digest("k", "d1", label="hook scripts") is True             # remembered
    assert ensure_trusted_digest("k", "d2", label="hook scripts") is False           # changed content: asks again
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    assert ensure_trusted_digest("k", "d3", label="hook scripts") is True


WORKSPACE_WITH_HOOK = """
from charpente import *
with Workspace("W") as ws:
    with Target("app") as t:
        t.sources(["a.cpp"])

    @ws.on(Event.BUILD_FINISHED)
    def done(ev):
        open("hook-ran.txt", "w").write(f"{ev.ok}:{ev.targets_built}")
"""


@requires_compiler
def test_dsl_hook_runs_during_a_real_build(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.cpp").write_text("int main(){return 0;}")
    (tmp_path / "w.charpente").write_text(WORKSPACE_WITH_HOOK)
    assert main(["build"]) == 0
    assert wait_for(lambda: (tmp_path / "hook-ran.txt").exists())
    assert (tmp_path / "hook-ran.txt").read_text() == "True:1"


@requires_compiler
def test_script_hooks_are_skipped_when_not_approved_and_run_when_trusted(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.cpp").write_text("int main(){return 0;}")
    (tmp_path / "w.charpente").write_text('from charpente import *\nwith Workspace("W") as ws:\n'
                                          '    with Target("app") as t:\n        t.sources(["a.cpp"])\n')
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")            # trust the workspace file itself ...
    d = tmp_path / ".charpente" / "hooks"
    d.mkdir(parents=True)
    (d / "session.finished.py").write_text("open('script-ran.txt', 'w').write('yes')")
    assert main(["build"]) == 0                                # ... which also covers the hook scripts
    assert wait_for(lambda: (tmp_path / "script-ran.txt").exists())

    (tmp_path / "script-ran.txt").unlink()
    monkeypatch.delenv("CHARPENTE_TRUST_ALL")
    from charpente.dsl import trust
    trust.trust(tmp_path / "w.charpente")                       # only the workspace file is trusted now
    capsys.readouterr()
    assert main(["clean"]) == 0
    assert main(["build"]) == 0
    assert "not approved" in capsys.readouterr().err
    time.sleep(0.3)
    assert not (tmp_path / "script-ran.txt").exists()


# ================================================================ GitHub annotations
def test_escaping_rules():
    assert gh.escape_data("a%b\r\nc") == "a%25b%0D%0Ac"
    assert gh.escape_property("a:b,c") == "a%3Ab%2Cc"


def test_annotation_format():
    assert gh.annotation("error", "boom", file="src/a.cpp", line=3, column=7, title="C2065") == \
        "::error file=src/a.cpp,line=3,col=7,title=C2065::boom"
    assert gh.annotation("warning", "no location") == "::warning::no location"


def test_annotations_are_relative_to_the_repository_and_map_severities(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    out = io.StringIO()
    bus = EventBus(strict=True)
    gh.GitHubAnnotations(bus, tmp_path, out=out)
    bus.emit("diagnostic.emitted", file=str(tmp_path / "src" / "a.cpp"), line=4, column=2, severity="error",
             code="-Wfoo", message="bad\nthing")
    bus.emit("diagnostic.emitted", file="C:\\elsewhere\\x.cpp", line=1, severity="warning", message="w")
    bus.emit("diagnostic.emitted", severity="note", message="n")
    bus.close()
    lines = out.getvalue().splitlines()
    assert lines[0] == "::error file=src/a.cpp,line=4,col=2,title=-Wfoo::bad%0Athing"
    assert lines[1].startswith("::warning file=C%3A/elsewhere/x.cpp,line=1::")
    assert lines[2] == "::notice::n"


@requires_compiler
def test_annotations_appear_automatically_inside_github_actions(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.cpp").write_text("int main() { return }\n")
    (tmp_path / "w.charpente").write_text('from charpente import *\nwith Workspace("W") as ws:\n'
                                          '    with Target("app") as t:\n        t.sources(["a.cpp"])\n')
    assert main(["build"]) == 1
    out = capsys.readouterr().out
    assert "::error file=a.cpp,line=1" in out


# ==================================================================== rich output
def test_rich_is_not_chosen_off_a_terminal():
    assert rich_renderer.wanted_by_default(io.StringIO()) is False


def test_rich_renderer_shows_progress_and_stops_cleanly():
    pytest.importorskip("rich")
    from rich.console import Console

    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=True, width=100, color_system=None)
    bus = EventBus(strict=True)
    renderer = rich_renderer.RichRenderer(bus, console=console)
    bus.emit("graph.analyzed", actions=2, targets=1, critical_path=1.0, config="")
    bus.emit("action.started", action="compile:a", target="t", kind="compile", description="Compiling a.cpp")
    bus.emit("action.output", action="compile:a", target="t", stream="combined", text="warning: careful")
    bus.emit("action.finished", action="compile:a", target="t", kind="compile", duration=0.1)
    bus.emit("hint.emitted", code="H", message="try a PCH")
    bus.emit("action.up_to_date", action="link:t", target="t", kind="link")
    bus.flush()
    renderer.finish()
    renderer.finish()                                             # idempotent
    bus.close()
    text = buffer.getvalue()
    assert "warning: careful" in text and "try a PCH" in text


def test_rich_renderer_explains_how_to_install_it_when_missing(monkeypatch):
    real_import = __import__

    def fake_import(name, *a, **k):
        if name.startswith("rich"):
            raise ImportError("no rich")
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", fake_import)
    with pytest.raises(ChError) as exc:
        rich_renderer.RichRenderer(EventBus())
    assert exc.value.code == "CH4006" and "charpente[rich]" in exc.value.format()
