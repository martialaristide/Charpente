from helpers import GCC, FakeToolchain, collect_events, make_workspace

from charpente import builder
from charpente.cli import main
from charpente.core import analysis
from charpente.core.state import ActionRecord
from charpente.dsl.model import OS
from charpente.events import EventBus


def rec(deps, duration):
    return ActionRecord(key="k", argv=[], cwd="", tool="", env=[], inputs={}, deps={d: "x" for d in deps},
                        outputs={}, duration=duration)


def test_header_costs_rank_by_total_rebuild_time():
    records = [("a", rec(["/p/common.h", "/p/a.h"], 2.0)), ("b", rec(["/p/common.h"], 3.0)),
               ("c", rec(["/p/rare.h"], 10.0))]
    costs = analysis.header_costs(records)
    assert [c.path for c in costs] == ["/p/rare.h", "/p/common.h", "/p/a.h"]
    common = costs[1]
    assert common.includers == 2 and common.rebuild_seconds == 5.0


def test_no_records_no_costs():
    assert analysis.header_costs([]) == []


def test_wide_header_change_produces_a_hint():
    reasons = {f"compile:{i}": ["header changed: include/common.h"] for i in range(25)}
    hints = analysis.hints_from_reasons(reasons)
    assert len(hints) == 1 and hints[0].code == "HINT001"
    assert "25 files" in hints[0].message and "include/common.h" in hints[0].message
    assert hints[0].detail["files"] == 25


def test_narrow_header_change_is_not_worth_a_hint():
    reasons = {f"compile:{i}": ["header changed: include/x.h"] for i in range(5)}
    assert analysis.hints_from_reasons(reasons) == []


def test_command_line_change_hint():
    reasons = {f"compile:{i}": ["command line changed: added -DX"] for i in range(30)}
    hints = analysis.hints_from_reasons(reasons)
    assert [h.code for h in hints] == ["HINT002"]


def test_a_build_emits_the_hint_event(tmp_path):
    sources = {f"f{i}.cpp": f"int f{i}();" for i in range(22)}
    (tmp_path / "common.h").write_text("v1")
    ws = make_workspace(tmp_path, sources)
    fake = FakeToolchain(headers={f"f{i}": [tmp_path / "common.h"] for i in range(22)})
    builder.build_workspace(ws, GCC, OS.LINUX, run=fake)
    (tmp_path / "common.h").write_text("v2 changed")
    bus = EventBus()
    events = collect_events(bus, ["hint.emitted"])
    builder.build_workspace(ws, GCC, OS.LINUX, run=fake, bus=bus)
    assert len(events) == 1 and events[0].payload["code"] == "HINT001"
    assert events[0].payload["detail"]["files"] == 22


def test_headers_command_without_a_build(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "w.charpente").write_text('from charpente import *\nwith Workspace("W") as ws:\n    pass\n')
    assert main(["headers"]) == 0
    assert "No build records" in capsys.readouterr().out
