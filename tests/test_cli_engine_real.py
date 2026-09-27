"""End-to-end tests of the engine through the CLI, with a real host compiler
(skipped when none is installed): exact header tracking, cache, `why`,
history, events, compile_commands.json."""
import json
import os
import shutil
import time
from pathlib import Path

import pytest

from charpente.cli import main
from charpente.platform import host_os
from charpente.toolchains import NoToolchainFoundError, pick_default


def _has_compiler() -> bool:
    try:
        pick_default(host_os())
        return True
    except NoToolchainFoundError:
        return False


requires_compiler = pytest.mark.skipif(not _has_compiler(), reason="no C/C++ compiler on PATH")

WORKSPACE = """
from charpente import *
with Workspace("W") as ws:
    with Target("app") as t:
        t.sources(["src/**/*.cpp"])
        t.include_dirs(["include"])
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "include").mkdir()
    (tmp_path / "w.charpente").write_text(WORKSPACE)
    (tmp_path / "include" / "a.h").write_text("#pragma once\ninline int va() { return 1; }\n")
    (tmp_path / "include" / "b.h").write_text("#pragma once\ninline int vb() { return 2; }\n")
    (tmp_path / "src" / "one.cpp").write_text('#include "a.h"\nint one() { return va(); }\n')
    (tmp_path / "src" / "two.cpp").write_text('#include "b.h"\nint two() { return vb(); }\n')
    (tmp_path / "src" / "main.cpp").write_text(
        '#include <cstdio>\nint one();\nint two();\nint main() { std::printf("total=%d\\n", one() + two()); }\n')
    return tmp_path


def run_program(capfd):
    assert main(["run", "--no-build"]) == 0
    return capfd.readouterr().out


@requires_compiler
def test_editing_a_header_rebuilds_exactly_its_dependents_and_the_binary_changes(project, capfd):
    assert main(["run"]) == 0
    assert "total=3" in capfd.readouterr().out

    # a header only one.cpp includes
    (project / "include" / "a.h").write_text("#pragma once\ninline int va() { return 10; }\n")
    assert main(["build", "-v"]) == 0
    out = capfd.readouterr().out
    assert "Compiling one.cpp" in out
    assert "Compiling two.cpp" not in out and "Compiling main.cpp" not in out
    assert "header changed: include/a.h" in out
    assert "total=12" in run_program(capfd)

    # touching without changing: nothing runs
    time.sleep(0.05)
    os.utime(project / "include" / "b.h", (time.time() + 3, time.time() + 3))
    assert main(["build"]) == 0
    assert "[up to date]" in capfd.readouterr().out


@requires_compiler
def test_second_build_is_a_noop_and_reports_it(project, capsys):
    assert main(["build"]) == 0
    capsys.readouterr()
    assert main(["build"]) == 0
    out = capsys.readouterr().out
    assert "[up to date]" in out and "0 run, 0 from cache, 4 up to date" in out


@requires_compiler
def test_cache_serves_a_rebuild_after_clean_without_compiling(project, capsys):
    assert main(["build"]) == 0
    capsys.readouterr()
    assert main(["clean"]) == 0
    capsys.readouterr()
    assert main(["build"]) == 0
    out = capsys.readouterr().out
    assert "4 from cache" in out and "0 run" in out


@requires_compiler
def test_no_cache_flag_forces_real_compilation(project, capsys):
    main(["build"])
    main(["clean"])
    capsys.readouterr()
    assert main(["build", "--no-cache"]) == 0
    assert "4 run, 0 from cache" in capsys.readouterr().out


@requires_compiler
def test_why_predicts_and_explains(project, capsys):
    main(["build"])
    capsys.readouterr()
    assert main(["why", "app"]) == 0
    assert "up to date" in capsys.readouterr().out

    (project / "include" / "b.h").write_text("#pragma once\ninline int vb() { return 20; }\n")
    assert main(["why", "include/b.h"]) == 0
    out = capsys.readouterr().out
    assert "two.cpp" in out and "header changed: include/b.h" in out
    assert "one.cpp" not in out

    assert main(["why", "app"]) == 0
    assert "will be rebuilt" in capsys.readouterr().out       # the link, downstream of two.cpp


@requires_compiler
def test_why_last_reads_the_history(project, capsys):
    main(["build"])
    (project / "include" / "a.h").write_text("#pragma once\ninline int va() { return 5; }\n")
    main(["build"])
    capsys.readouterr()
    assert main(["why", "--last", "include/a.h"]) == 0
    out = capsys.readouterr().out
    assert "one.cpp" in out and "executed" in out and "header changed" in out


def test_why_unknown_subject(project, capsys):
    assert main(["why", "no-such-thing"]) == 1
    assert "Nothing known" in capsys.readouterr().out


@requires_compiler
def test_history_and_diff_build(project, capsys):
    main(["build"])
    (project / "src" / "one.cpp").write_text('#include "a.h"\nint one() { return va() + 1; }\n')
    main(["build"])
    capsys.readouterr()
    assert main(["history"]) == 0
    out = capsys.readouterr().out
    assert out.count("build") >= 2 and "ok" in out

    assert main(["diff-build"]) == 0
    out = capsys.readouterr().out
    assert "Time:" in out and "Actions run: 4 -> 2" in out


@requires_compiler
def test_history_with_no_builds(project, capsys):
    assert main(["history"]) == 0
    assert "No build history" in capsys.readouterr().out


@requires_compiler
def test_diff_build_needs_two_sessions(project, capsys):
    main(["build"])
    capsys.readouterr()
    assert main(["diff-build"]) == 1
    assert "CH4005" in capsys.readouterr().err


@requires_compiler
def test_jsonl_output_is_valid_events(project, capsys):
    jsonschema = pytest.importorskip("jsonschema")
    from charpente.events.schema import any_event_schema

    assert main(["build", "--output", "jsonl"]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines]                 # every line is JSON: nothing else was printed
    validator = jsonschema.Draft202012Validator(any_event_schema())
    for ev in events:
        validator.validate(ev)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "session.started" and kinds[-1] == "session.finished"
    assert "graph.analyzed" in kinds and kinds.count("action.finished") == 4
    ids = [e["id"] for e in events]
    assert ids == sorted(ids)


@requires_compiler
def test_session_log_is_recorded_and_replayable(project, capsys):
    main(["build"])
    logs = list((project / "build" / ".charpente" / "events").glob("*.jsonl"))
    assert len(logs) == 1
    capsys.readouterr()
    assert main(["replay"]) == 0
    out = capsys.readouterr().out
    assert "session.started" in out and "action.finished" in out
    assert main(["replay", "--output", "jsonl"]) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[0])["type"] == "session.started"


@requires_compiler
def test_compile_commands_json_is_written_for_language_servers(project):
    main(["build"])
    db = json.loads((project / "build" / "compile_commands.json").read_text())
    assert len(db) == 3
    entry = next(e for e in db if e["file"].endswith("one.cpp"))
    assert Path(entry["directory"]).resolve() == project.resolve() and ("-Iinclude" in entry["arguments"] or "/Iinclude" in entry["arguments"])   # short or long form of the same folder
    assert entry["output"].endswith("one.cpp.o") or entry["output"].endswith("one.cpp.obj")


@requires_compiler
def test_compile_commands_is_not_rewritten_when_unchanged(project):
    main(["build"])
    path = project / "build" / "compile_commands.json"
    before = path.stat().st_mtime_ns
    time.sleep(0.05)
    main(["build"])
    assert path.stat().st_mtime_ns == before


@requires_compiler
def test_a_compile_error_is_reported_with_its_code_and_exit_code(project, capsys):
    (project / "src" / "two.cpp").write_text("int two() { return }\n")
    assert main(["build"]) == 1
    out = capsys.readouterr().out
    assert "[FAILED]" in out and "two.cpp" in out


@requires_compiler
def test_warnings_of_a_successful_build_are_shown(project, capsys):
    (project / "src" / "two.cpp").write_text(
        '#include "b.h"\nint two() { int unused; return vb(); }\n')
    (project / "w.charpente").write_text(WORKSPACE.replace('t.include_dirs(["include"])',
                                                             't.include_dirs(["include"])\n        t.compile_flags(["-Wall"])'))
    if shutil.which("g++") is None and shutil.which("clang++") is None:
        pytest.skip("GNU-style warnings only")
    assert main(["build"]) == 0
    captured = capsys.readouterr()
    assert "unused" in captured.err + captured.out


@requires_compiler
def test_same_named_sources_in_different_folders_both_link(project, capfd):
    (project / "src" / "x").mkdir()
    (project / "src" / "y").mkdir()
    (project / "src" / "x" / "util.cpp").write_text("int ux() { return 100; }\n")
    (project / "src" / "y" / "util.cpp").write_text("int uy() { return 200; }\n")
    (project / "src" / "main.cpp").write_text(
        '#include <cstdio>\nint ux();\nint uy();\nint main() { std::printf("sum=%d\\n", ux() + uy()); }\n')
    (project / "src" / "one.cpp").unlink()
    (project / "src" / "two.cpp").unlink()
    assert main(["run"]) == 0
    assert "sum=300" in capfd.readouterr().out


@requires_compiler
def test_library_change_relinks_the_dependent_executable(tmp_path, monkeypatch, capfd):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "core.cpp").write_text("int value() { return 1; }\n")
    (tmp_path / "app.cpp").write_text('#include <cstdio>\nint value();\nint main() { std::printf("v=%d\\n", value()); }\n')
    (tmp_path / "w.charpente").write_text("""
from charpente import *
with Workspace("W") as ws:
    with Target("core") as t:
        t.kind(Kind.STATIC_LIBRARY)
        t.sources(["core.cpp"])
    with Target("app") as t:
        t.depends_on(["core"])
        t.links(["core"])
        t.sources(["app.cpp"])
""")
    assert main(["run", "--target", "app"]) == 0
    assert "v=1" in capfd.readouterr().out
    (tmp_path / "core.cpp").write_text("int value() { return 7; }\n")
    assert main(["run", "--target", "app"]) == 0
    assert "v=7" in capfd.readouterr().out                 # the library changed -> the app was relinked


@requires_compiler
def test_parallel_and_serial_builds_produce_the_same_result(project, capfd):
    assert main(["build", "-j", "1"]) == 0
    assert "total=3" in run_program(capfd)
    main(["clean"])
    assert main(["build", "-j", "4", "--no-cache"]) == 0
    assert "total=3" in run_program(capfd)


def test_cache_command(project, capsys):
    assert main(["cache", "dir"]) == 0
    assert capsys.readouterr().out.strip()
    assert main(["cache", "stats"]) == 0
    assert "entries" in capsys.readouterr().out
    assert main(["cache", "gc", "--max-size", "1MB"]) == 0
    assert main(["cache", "gc", "--max-size", "banana"]) == 1
    assert main(["cache", "clear"]) == 0


@requires_compiler
def test_test_command_reports_flaky_tests(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(tmp_path)
    marker = tmp_path / "ran-once"
    (tmp_path / "t.cpp").write_text(f"""
#include <cstdio>
int main() {{
    std::FILE* f = std::fopen("{marker.as_posix()}", "r");
    if (f) {{ std::fclose(f); return 0; }}
    f = std::fopen("{marker.as_posix()}", "w");
    if (f) std::fclose(f);
    return 1;        // fails the first time only
}}
""")
    (tmp_path / "w.charpente").write_text("""
from charpente import *
with Workspace("W") as ws:
    with Target("flaky") as t:
        t.kind(Kind.TEST)
        t.sources(["t.cpp"])
""")
    assert main(["test", "--retries", "2"]) == 0
    out = capsys.readouterr().out
    assert "[FLAKY] flaky" in out and "1/1 test target(s) passed" in out


@requires_compiler
def test_a_failing_test_without_retries_still_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.cpp").write_text("int main() { return 3; }\n")
    (tmp_path / "w.charpente").write_text("""
from charpente import *
with Workspace("W") as ws:
    with Target("bad") as t:
        t.kind(Kind.TEST)
        t.sources(["t.cpp"])
""")
    assert main(["test", "--retries", "1"]) == 1
    assert "[FAIL] bad (exit code 3)" in capsys.readouterr().out


@requires_compiler
def test_headers_command_ranks_project_headers(project, capsys):
    main(["build"])
    capsys.readouterr()
    assert main(["headers"]) == 0
    out = capsys.readouterr().out
    assert "a.h" in out and "b.h" in out and "included by" in out
