import os
import shutil
import time

from helpers import GCC, FakeToolchain, collect_events, make_workspace

from charpente import builder
from charpente.core import engine as eng
from charpente.core.cache import LocalCache
from charpente.core.planner import plan_workspace
from charpente.core.state import StateDB
from charpente.dsl.model import OS, Kind, Target, Workspace
from charpente.events import EventBus

SOURCES = {"a.cpp": "int a(){return 1;}", "b.cpp": "int b(){return 2;}", "main.cpp": "int main(){return 0;}"}


def build(ws, fake, bus=None, **kw):
    return builder.build_workspace(ws, GCC, OS.LINUX, run=fake, bus=bus, **kw)


def statuses(result):
    return {i: r.status for i, r in result.engine.results.items()}


# ============================================================ incremental basics
def test_clean_build_runs_everything_then_a_second_build_runs_nothing(tmp_path):
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain()
    first = build(ws, fake)
    assert first.ok and sorted(fake.compiles) == ["a", "b", "main"]
    n = len(fake.calls)
    second = build(ws, fake)
    assert second.ok and second.targets[0].skipped and len(fake.calls) == n
    assert set(statuses(second).values()) == {"up_to_date"}


def test_editing_a_source_recompiles_only_that_source_and_relinks(tmp_path):
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain()
    build(ws, fake)
    fake.compiles.clear()
    (tmp_path / "b.cpp").write_text("int b(){return 22;}")
    r = build(ws, fake)
    assert r.ok and fake.compiles == ["b"]
    assert statuses(r)["link:app"] == "executed"


def test_touching_a_file_without_changing_it_rebuilds_nothing(tmp_path):
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain()
    build(ws, fake)
    time.sleep(0.05)
    future = time.time() + 5
    for name in SOURCES:
        os.utime(tmp_path / name, (future, future))
    fake.calls.clear()
    assert build(ws, fake).targets[0].skipped and fake.calls == []


# ============================================================ header tracking
def test_header_change_recompiles_exactly_the_dependents(tmp_path):
    inc = tmp_path / "inc"
    inc.mkdir()
    (inc / "common.h").write_text("// v1")
    (inc / "only_a.h").write_text("// v1")
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain(headers={"a": [inc / "common.h", inc / "only_a.h"], "b": [inc / "common.h"]})
    build(ws, fake)

    fake.compiles.clear()
    (inc / "only_a.h").write_text("// v2")
    r = build(ws, fake)
    assert fake.compiles == ["a"] and r.ok

    fake.compiles.clear()
    (inc / "common.h").write_text("// v2")
    build(ws, fake)
    assert sorted(fake.compiles) == ["a", "b"]           # main.cpp does not include it

    fake.compiles.clear()
    build(ws, fake)
    assert fake.compiles == []


def test_a_deleted_header_makes_its_dependents_stale(tmp_path):
    (tmp_path / "gone.h").write_text("//")
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain(headers={"a": [tmp_path / "gone.h"]})
    build(ws, fake)
    fake.compiles.clear()
    (tmp_path / "gone.h").unlink()
    build(ws, fake)
    assert fake.compiles == ["a"]


def test_headers_with_spaces_in_their_names_are_tracked(tmp_path):
    (tmp_path / "my header.h").write_text("//1")
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain(headers={"main": [tmp_path / "my header.h"]})
    build(ws, fake)
    fake.compiles.clear()
    (tmp_path / "my header.h").write_text("//2")
    build(ws, fake)
    assert fake.compiles == ["main"]


def test_a_compiler_that_writes_no_depfile_still_builds_correctly(tmp_path):
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain()

    def strip(argv):
        pass

    real = fake._run

    def no_dep(argv):
        argv = [a for a in argv]
        if "-MF" in argv:
            i = argv.index("-MF")
            del argv[i:i + 2]
        return real(argv)

    fake._run = no_dep
    assert build(ws, fake).ok
    fake.compiles.clear()
    assert build(ws, fake).targets[0].skipped


# ============================================================ command / environment / outputs
def test_changing_a_flag_rebuilds_everything_and_says_why(tmp_path):
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain()
    build(ws, fake)
    ws.targets["app"].define_macros.append("NEW=1")
    fake.compiles.clear()
    bus = EventBus()
    events = collect_events(bus, ["action.started"])
    build(ws, fake, bus=bus)
    assert sorted(fake.compiles) == ["a", "b", "main"]
    reasons = [r for e in events if e.payload.get("reasons") for r in e.payload["reasons"]]
    assert any("command line changed" in r and "-DNEW=1" in r for r in reasons)


def test_a_deleted_output_is_rebuilt(tmp_path):
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain()
    r1 = build(ws, fake)
    r1.targets[0].output_path.unlink()
    fake.calls.clear()
    r2 = build(ws, fake)
    assert r2.ok and not r2.targets[0].skipped and [c for c in fake.calls if "-c" in c] == []


def test_an_output_modified_outside_the_build_is_rebuilt(tmp_path):
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain()
    r1 = build(ws, fake)
    r1.targets[0].output_path.write_text("someone edited the binary by hand")
    r2 = build(ws, fake)
    assert not r2.targets[0].skipped
    assert r2.targets[0].output_path.read_text() == "binary"


def test_environment_that_affects_compilation_is_part_of_the_key(tmp_path, monkeypatch):
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain()
    monkeypatch.delenv("CPATH", raising=False)
    build(ws, fake)
    monkeypatch.setenv("CPATH", str(tmp_path))
    fake.compiles.clear()
    build(ws, fake)
    assert sorted(fake.compiles) == ["a", "b", "main"]


def test_static_library_drops_members_of_removed_sources(tmp_path):
    ws = make_workspace(tmp_path, SOURCES, kind=Kind.STATIC_LIBRARY)
    fake = FakeToolchain()
    seen = []

    def on_call(argv):
        if "rcs" in argv:
            out = argv[argv.index("rcs") + 1]
            seen.append(os.path.exists(out))     # the archiver must start from nothing

    fake.on_call = on_call
    build(ws, fake)
    (tmp_path / "b.cpp").unlink()
    build(ws, fake)
    assert seen == [False, False]


def test_missing_declared_output_is_reported(tmp_path):
    ws = make_workspace(tmp_path, {"a.cpp": "int a();"})
    fake = FakeToolchain()
    real = fake._run

    def lying(argv):
        r = real(argv)
        if "-c" in argv:
            os.remove(argv[argv.index("-o") + 1])
        return r

    fake._run = lying
    result = build(ws, fake)
    assert not result.ok and "did not create" in result.targets[0].error


def test_missing_tool_is_a_clean_failure_not_a_traceback(tmp_path):
    ws = make_workspace(tmp_path, SOURCES)
    from charpente.core import process
    result = builder.build_workspace(ws, GCC, OS.LINUX, run=process.raw_run) if shutil.which("g++") is None else None
    if result is not None:
        assert not result.ok and "not found" in result.targets[0].error.lower()
    from charpente.errors import ChError

    def gone(argv, **kw):
        raise ChError("CH2002", tool=argv[0])

    r = builder.build_workspace(ws, GCC, OS.LINUX, run=gone)
    assert not r.ok and "Program not found" in r.targets[0].error


# ============================================================ failures
def test_fail_fast_stops_scheduling_new_work(tmp_path):
    ws = make_workspace(tmp_path, {f"f{i}.cpp": "x" for i in range(6)})
    fake = FakeToolchain(fail_on={"f0"})
    r = build(ws, fake, jobs=1)
    assert not r.ok
    assert len(fake.compiles) < 6                       # the rest was not started
    assert "f0.cpp" in r.targets[0].error
    assert not [c for c in fake.calls if "-o" in c and "-c" not in c]   # never linked


def test_keep_going_builds_unrelated_targets_and_blocks_dependents(tmp_path):
    for n in ("core", "app", "tool"):
        (tmp_path / f"{n}.cpp").write_text("x")
    ws = Workspace(name="D", location=tmp_path)
    ws.add_target(Target(name="core", kind=Kind.STATIC_LIBRARY, source_patterns=["core.cpp"], location=tmp_path))
    ws.add_target(Target(name="app", depends_on=["core"], source_patterns=["app.cpp"], location=tmp_path))
    ws.add_target(Target(name="tool", source_patterns=["tool.cpp"], location=tmp_path))
    fake = FakeToolchain(fail_on={"core"})
    r = build(ws, fake, keep_going=True)
    assert not r.ok
    assert r.target("core").ok is False and r.target("tool").ok is True
    app = r.target("app")
    assert app.ok is False and "depends on failed" in app.error and app.error_code == "CH3006"
    assert "app" in fake.compiles                       # app's *compile* is independent of core


def test_all_compile_errors_are_reported_not_just_the_first(tmp_path):
    ws = make_workspace(tmp_path, {"a.cpp": "x", "b.cpp": "y"})
    fake = FakeToolchain(fail_on={"a", "b"})
    r = build(ws, fake, keep_going=True, jobs=1)
    assert "a.cpp" in r.targets[0].error and "b.cpp" in r.targets[0].error
    assert r.targets[0].error_code == "CH3002"


def test_link_failure_has_its_own_code(tmp_path):
    ws = make_workspace(tmp_path, {"a.cpp": "x"})
    r = build(ws, FakeToolchain(fail_on={"app"}))
    assert not r.ok and r.targets[0].error_code == "CH3003"


def test_a_failed_action_is_retried_next_time(tmp_path):
    ws = make_workspace(tmp_path, SOURCES)
    build(ws, FakeToolchain(fail_on={"b"}))
    fake = FakeToolchain()
    r = build(ws, fake)
    assert r.ok and "b" in fake.compiles


# ============================================================ cache
def test_cache_restores_everything_after_a_clean_without_running_the_compiler(tmp_path):
    ws = make_workspace(tmp_path, SOURCES)
    cache = LocalCache(tmp_path / "cache")
    fake = FakeToolchain()
    build(ws, fake, cache=cache)
    shutil.rmtree(tmp_path / "build")
    fake2 = FakeToolchain()
    bus = EventBus()
    events = collect_events(bus, ["action.cache_hit", "target.finished"])
    r = build(ws, fake2, bus=bus, cache=cache)
    assert r.ok and [c for c in fake2.calls if "-c" in c or "-o" in c] == []
    assert sum(e.type == "action.cache_hit" for e in events) == 4
    assert r.targets[0].cached == 4 and not r.targets[0].skipped
    assert r.targets[0].output_path.read_text() == "binary"


def test_cache_key_includes_header_contents(tmp_path):
    (tmp_path / "h.h").write_text("v1")
    ws = make_workspace(tmp_path, {"a.cpp": "int a();"})
    cache = LocalCache(tmp_path / "cache")
    fake = FakeToolchain(headers={"a": [tmp_path / "h.h"]})
    build(ws, fake, cache=cache)
    (tmp_path / "h.h").write_text("v2")
    build(ws, fake, cache=cache)                         # compiled with v2, cached
    shutil.rmtree(tmp_path / "build")
    fake.compiles.clear()
    (tmp_path / "h.h").write_text("v1")
    build(ws, fake, cache=cache)                         # v1 again: served from the cache
    assert fake.compiles == []
    (tmp_path / "h.h").write_text("v3")
    shutil.rmtree(tmp_path / "build")
    build(ws, fake, cache=cache)                         # never seen: must compile
    assert fake.compiles == ["a"]


def test_cache_can_be_disabled(tmp_path):
    ws = make_workspace(tmp_path, {"a.cpp": "int a();"})
    fake = FakeToolchain()
    build(ws, fake, use_cache=False)
    shutil.rmtree(tmp_path / "build")
    fake.compiles.clear()
    build(ws, fake, use_cache=False)
    assert fake.compiles == ["a"]


def test_cached_warnings_are_replayed_as_diagnostics(tmp_path):
    ws = make_workspace(tmp_path, {"a.cpp": "int a();"})
    cache = LocalCache(tmp_path / "cache")
    fake = FakeToolchain()
    real = fake._run

    def warns(argv):
        r = real(argv)
        if "-c" in argv:
            r.stderr = "a.cpp:1:1: warning: unused [-Wunused]"
        return r

    fake._run = warns
    build(ws, fake, cache=cache)
    shutil.rmtree(tmp_path / "build")
    bus = EventBus()
    events = collect_events(bus, ["diagnostic.emitted"])
    build(ws, fake, bus=bus, cache=cache)
    assert any(e.payload["severity"] == "warning" for e in events)


# ============================================================ parallelism and scheduling
def test_independent_compiles_run_in_parallel(tmp_path):
    ws = make_workspace(tmp_path, {f"f{i}.cpp": "x" for i in range(8)})
    fake = FakeToolchain(delay=0.05)
    r = build(ws, fake, jobs=4)
    assert r.ok and 2 <= fake.max_concurrent <= 4


def test_jobs_one_is_strictly_sequential(tmp_path):
    ws = make_workspace(tmp_path, {f"f{i}.cpp": "x" for i in range(5)})
    fake = FakeToolchain(delay=0.01)
    build(ws, fake, jobs=1)
    assert fake.max_concurrent == 1


def test_the_critical_path_is_scheduled_first(tmp_path):
    """With one job, the source whose chain is longest (the slow one recorded
    from an earlier build) must be compiled before the quick ones."""
    ws = make_workspace(tmp_path, {"slow.cpp": "x", "q1.cpp": "x", "q2.cpp": "x"})
    fake = FakeToolchain()
    build(ws, fake, jobs=1)
    plan = plan_workspace(ws, GCC, OS.LINUX)
    state = StateDB(builder.state_dir(ws) / "state.db")
    rec = state.get_action("compile:app:slow.cpp")
    rec.duration = 50.0
    state.put_action("compile:app:slow.cpp", rec)
    state.close()
    for name in ("slow", "q1", "q2"):
        (tmp_path / f"{name}.cpp").write_text("changed")
    fake.compiles.clear()
    build(ws, fake, jobs=1)
    assert fake.compiles[0] == "slow" and plan


# ============================================================ events and dry runs
def test_event_stream_for_a_successful_build(tmp_path):
    ws = make_workspace(tmp_path, SOURCES)
    bus = EventBus()
    events = collect_events(bus)
    build(ws, FakeToolchain(), bus=bus)
    types = [e.type for e in events]
    assert types[0] == "graph.analyzed"
    assert types.count("target.started") == 1 and types.count("target.finished") == 1
    assert types.count("action.finished") == 4
    finished = next(e for e in events if e.type == "target.finished")
    assert finished.payload["executed"] == 4


def test_up_to_date_targets_are_announced_as_such(tmp_path):
    ws = make_workspace(tmp_path, SOURCES)
    build(ws, FakeToolchain())
    bus = EventBus()
    events = collect_events(bus, ["target.*"])
    build(ws, FakeToolchain(), bus=bus)
    assert [e.type for e in events] == ["target.up_to_date"]


def test_failures_emit_action_failed_and_diagnostics(tmp_path):
    ws = make_workspace(tmp_path, {"a.cpp": "x"})
    bus = EventBus()
    events = collect_events(bus)
    build(ws, FakeToolchain(fail_on={"a"}), bus=bus)
    kinds = {e.type for e in events}
    assert {"action.failed", "target.failed", "diagnostic.emitted"} <= kinds
    diag = next(e for e in events if e.type == "diagnostic.emitted")
    assert diag.payload["severity"] == "error" and diag.payload["line"] == 1


def test_plan_explains_why_things_are_stale_without_running_anything(tmp_path):
    (tmp_path / "h.h").write_text("1")
    ws = make_workspace(tmp_path, {"a.cpp": "int a();", "b.cpp": "int b();"})
    fake = FakeToolchain(headers={"a": [tmp_path / "h.h"]})
    build(ws, fake)
    (tmp_path / "h.h").write_text("2")
    (tmp_path / "b.cpp").write_text("int b(); // edited")

    plan = plan_workspace(ws, GCC, OS.LINUX)
    state = StateDB(builder.state_dir(ws) / "state.db")
    engine = eng.Engine(state, EventBus(), root=tmp_path)
    calls = len(fake.calls)
    decisions = engine.plan(plan.graph)
    assert len(fake.calls) == calls                                   # nothing was run
    a, b = decisions["compile:app:a.cpp"], decisions["compile:app:b.cpp"]
    assert not a.fresh and any("header changed: h.h" in r for r in a.reasons)
    assert not b.fresh and any("input changed: b.cpp" in r for r in b.reasons)
    link = decisions["link:app"]
    assert not link.fresh and any("will be rebuilt" in r for r in link.reasons)
    state.close()


def test_plan_of_a_fresh_workspace_is_all_fresh_and_new_workspace_has_no_record(tmp_path):
    ws = make_workspace(tmp_path, SOURCES)
    plan = plan_workspace(ws, GCC, OS.LINUX)
    state = StateDB(tmp_path / "s.db")
    engine = eng.Engine(state, EventBus(), root=tmp_path)
    first = engine.plan(plan.graph)
    assert all("no previous build record" in d.reasons[0] for d in first.values())
    state.close()
    build(ws, FakeToolchain())
    state = StateDB(builder.state_dir(ws) / "state.db")
    engine = eng.Engine(state, EventBus(), root=tmp_path)
    assert all(d.fresh for d in engine.plan(plan.graph).values())
    state.close()


def test_interrupted_build_is_reported_and_the_next_build_is_correct(tmp_path):
    ws = make_workspace(tmp_path, {f"f{i}.cpp": "x" for i in range(4)})
    fake = FakeToolchain(delay=0.02)
    bus = EventBus()
    fired = []

    def ctrl_c(event):
        # A KeyboardInterrupt is delivered to the main thread only, which is
        # where the scheduler emits `target.started` from.
        if not fired:
            fired.append(1)
            raise KeyboardInterrupt

    bus.subscribe(ctrl_c, sync=True, types=["target.started"])
    interrupted = build(ws, fake, bus=bus, jobs=2)
    assert interrupted.interrupted and not interrupted.ok

    rebuilt = build(ws, FakeToolchain())
    assert rebuilt.ok and rebuilt.targets[0].output_path.exists()
    assert build(ws, FakeToolchain()).targets[0].skipped
