"""Budgets (binary size, build time), and the size/duration parsing they use."""
import json
import shutil
from pathlib import Path

import pytest

from charpente import budgets
from charpente.cli import main
from charpente.dsl.loader import load_workspace
from charpente.errors import ChError
from charpente.units import human_duration, human_size, parse_duration, parse_size

HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++"))


# ---------------------------------------------------------------------- units
@pytest.mark.parametrize("text, expected", [("1024", 1024), ("2KB", 2048), ("2 kb", 2048), ("1.5MB", 1572864), ("1MiB", 1048576), ("3G", 3 * 1024 ** 3), ("0", 0)])
def test_sizes(text, expected):
    assert parse_size(text) == expected


@pytest.mark.parametrize("bad", ["", "MB", "-5MB", "12 parsecs", "1..5MB"])
def test_bad_sizes_are_coded_errors(bad):
    with pytest.raises(ChError) as info:
        parse_size(bad)
    assert info.value.code == "CH4005"


@pytest.mark.parametrize("text, expected", [("90s", 90), ("2m", 120), ("1h30m", 5400), ("500ms", 0.5), ("45", 45), (12, 12.0), ("1m30s", 90), ("0.5s", 0.5)])
def test_durations(text, expected):
    assert parse_duration(text) == pytest.approx(expected)


@pytest.mark.parametrize("bad", ["", "soon", "5x", "1h 30", "-3", -1, "s"])
def test_bad_durations(bad):
    with pytest.raises(ChError):
        parse_duration(bad)


def test_human_formats():
    assert human_size(512) == "512 B" and human_size(1536) == "1.5 KB" and human_size(5 * 1024 ** 2) == "5.0 MB"
    assert human_duration(0.25) == "250 ms" and human_duration(12.34) == "12.3 s" and human_duration(125) == "2 min 5 s"


# ---------------------------------------------------------------------- declaring budgets
def test_the_dsl_records_budgets(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    (tmp_path / "w.charpente").write_text('from charpente import *\nwith Workspace("w") as ws:\n    ws.budget(build_time="90s", total_size="40MB")\n'
                                          '    with Target("a") as t:\n        t.sources(["*.cpp"])\n        t.budget(size="2MB")\n', encoding="utf-8")
    workspace = load_workspace(str(tmp_path / "w.charpente"))
    assert workspace.budgets == {"build_time": 90.0, "total_size": 40 * 1024 ** 2}
    assert workspace.targets["a"].budgets == {"size": 2 * 1024 ** 2}


@pytest.mark.parametrize("call", ['ws.budget(build_time="soon")', 'ws.budget(total_size="12 parsecs")', "ws.budget(build_time=0)", 'ws.budget(speed="1s")'])
def test_a_bad_budget_is_a_coded_error_not_a_silent_no_op(tmp_path, monkeypatch, call):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    (tmp_path / "w.charpente").write_text(f'from charpente import *\nwith Workspace("w") as ws:\n    {call}\n', encoding="utf-8")
    with pytest.raises(ChError) as info:
        load_workspace(str(tmp_path / "w.charpente"))
    assert info.value.code == "CH1004"                                                             # errors in the file are reported with their own code inside
    assert "[CH1026]" in info.value.message or "speed" in info.value.message


def test_target_budget_names_are_checked():
    with pytest.raises(ChError, match="unknown target budget"):
        budgets.parse_target_budget({"speed": 1})
    assert budgets.parse_target_budget({"size": None}) == {}
    assert budgets.parse_target_budget({"size": 4096}) == {"size": 4096}


# ---------------------------------------------------------------------- evaluating (pure)
class T:
    def __init__(self, **b):
        self.budgets = b


class W:
    def __init__(self, targets, **b):
        self.targets = targets
        self.budgets = b


def test_evaluate_reports_only_what_can_be_measured():
    workspace = W({"a": T(size=1000), "b": T(), "c": T(size=10)}, build_time=5.0, total_size=2000.0)
    sizes = {Path("a.exe"): 1500, Path("b.exe"): 400}
    findings = budgets.evaluate(workspace, {"a": Path("a.exe"), "b": Path("b.exe")}, 3.0, lambda p: sizes.get(p))
    by = {(f.scope, f.kind): f for f in findings}
    assert set(by) == {("a", "size"), ("workspace", "build_time"), ("workspace", "total_size")}       # c was not built: not measured
    assert not by[("a", "size")].ok and by[("workspace", "build_time")].ok and by[("workspace", "total_size")].ok      # 1900 <= 2000
    assert "OVER the budget" in by[("a", "size")].describe() and "within" in by[("workspace", "build_time")].describe()


def test_no_measurable_outputs_means_no_size_findings():
    assert budgets.evaluate(W({"a": T(size=1)}, total_size=10.0), {}, 1.0) == []


# ---------------------------------------------------------------------- the build command
def project(tmp_path, budget_lines):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.cpp").write_text("#include <cstdio>\nint main() { std::puts(\"hi\"); return 0; }\n", encoding="utf-8")
    (tmp_path / "b.charpente").write_text('from charpente import *\n\nwith Workspace("b") as ws:\n' + budget_lines[0] + '    with Target("app") as app:\n        app.kind(Kind.EXECUTABLE)\n'
                                          '        app.standard("c++17")\n        app.sources(["src/main.cpp"])\n' + budget_lines[1], encoding="utf-8")
    return tmp_path


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_a_build_within_its_budgets_passes_and_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(project(tmp_path, ('    ws.budget(build_time="10m", total_size="500MB")\n', '        app.budget(size="50MB")\n')))
    assert main(["build"]) == 0
    out = capsys.readouterr().out
    assert out.count("[budget ok]") == 3 and "OVER" not in out


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_an_exceeded_budget_fails_the_build(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(project(tmp_path, ("", '        app.budget(size="1KB")\n')))
    assert main(["build"]) == 1
    out = capsys.readouterr().out
    assert "[OVER BUDGET] app: size" in out and "the budget of 1.0 KB" in out
    assert main(["build", "--no-budget"]) == 0                                                    # explicitly skipped
    assert "budget" not in capsys.readouterr().out.lower()


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_a_build_time_budget_can_fail_a_slow_build(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(project(tmp_path, ('    ws.budget(build_time="1ms")\n', "")))
    assert main(["build", "--no-cache"]) == 1
    assert "workspace: build time" in capsys.readouterr().out


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_budget_events_are_in_the_machine_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(project(tmp_path, ("", '        app.budget(size="1KB")\n')))
    main(["build", "--output", "jsonl"])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    exceeded = [e for e in events if e["type"] == "budget.exceeded"]
    assert len(exceeded) == 1 and exceeded[0]["payload"]["scope"] == "app" and exceeded[0]["payload"]["actual"] > exceeded[0]["payload"]["limit"]


def test_the_budget_events_have_published_schemas():
    schema = json.loads((Path(__file__).resolve().parents[1] / "docs" / "events" / "budget.exceeded.schema.json").read_text(encoding="utf-8"))
    assert set(schema["properties"]["payload"]["required"]) == {"scope", "kind", "limit", "actual"}


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_a_size_budget_that_cannot_be_measured_is_said_not_silently_skipped(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    extra = '        app.budget(size="50MB")\n    with Target("headers") as h:\n        h.kind(Kind.HEADER_ONLY)\n        h.budget(size="1KB")\n'
    monkeypatch.chdir(project(tmp_path, ("", extra)))
    assert main(["build"]) == 0
    captured = capsys.readouterr()
    assert "[budget ok] app: size" in captured.out
    assert "[budget skipped] headers" in captured.err and "no output file to measure" in captured.err
