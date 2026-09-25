import os
import time

import pytest
from helpers import GCC, FakeToolchain, make_workspace

from charpente import builder
from charpente.core import fastpath
from charpente.core.statcache import StatCache
from charpente.dsl.model import OS
from charpente.events import EventBus


def _files(tmp_path, names):
    out = []
    for n in names:
        f = tmp_path / n
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(n)
        old = time.time() - 3600
        os.utime(f, (old, old))
        out.append(str(f))
    return out


def _stamp(tmp_path, names, context="ctx"):
    stats = StatCache()
    dirs = fastpath.collect(_files(tmp_path, names), stats)
    return fastpath.Stamp(context=context, targets={"app": {"output": "x", "actions": 3}}, dirs=dirs,
                          created_ns=time.time_ns())


# ============================================================ stamp file
def test_write_load_verify_round_trip(tmp_path):
    stamp = _stamp(tmp_path, ["a.cpp", "sub/b.cpp", "sub/has space.h"])
    path = tmp_path / "state" / "stamp.txt"
    assert fastpath.write(path, stamp)
    loaded = fastpath.load(path)
    assert loaded is not None and loaded.context == "ctx" and loaded.targets["app"]["actions"] == 3
    assert fastpath.verify(loaded, "ctx", StatCache())


def test_a_different_context_never_verifies(tmp_path):
    stamp = _stamp(tmp_path, ["a.cpp"])
    assert not fastpath.verify(stamp, "other", StatCache())
    assert not fastpath.verify(None, "ctx", StatCache())


def test_a_changed_size_or_mtime_or_missing_file_never_verifies(tmp_path):
    stamp = _stamp(tmp_path, ["a.cpp", "b.cpp"])
    target = tmp_path / "a.cpp"
    assert fastpath.verify(stamp, "ctx", StatCache())

    target.write_text("longer content than before")           # size and mtime change
    assert not fastpath.verify(stamp, "ctx", StatCache())

    stamp = _stamp(tmp_path, ["a.cpp", "b.cpp"])
    st = target.stat()
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))   # only mtime
    assert not fastpath.verify(stamp, "ctx", StatCache())

    stamp = _stamp(tmp_path, ["a.cpp", "b.cpp"])
    (tmp_path / "b.cpp").unlink()
    assert not fastpath.verify(stamp, "ctx", StatCache())


def test_a_stamp_is_refused_when_a_watched_file_is_too_recent(tmp_path):
    names = _files(tmp_path, ["a.cpp"])
    fresh = tmp_path / "just_written.o"
    fresh.write_text("x")                                     # mtime = now: racy
    dirs = fastpath.collect(names + [str(fresh)], StatCache())
    stamp = fastpath.Stamp(context="c", dirs=dirs, created_ns=time.time_ns())
    path = tmp_path / "stamp.txt"
    path.write_text("stale older stamp")
    assert fastpath.write(path, stamp) is False
    assert not path.exists()                                  # and the older stamp is dropped


def test_collect_fails_if_a_file_is_missing(tmp_path):
    assert fastpath.collect([str(tmp_path / "nope.cpp")], StatCache()) is None


@pytest.mark.parametrize("content", ["", "not json\n", '{"version": 1}\n', '{"version": 2, "context": "c"}\n1\t2\tx\n'])
def test_corrupt_or_foreign_stamps_read_as_no_stamp(tmp_path, content):
    path = tmp_path / "stamp.txt"
    path.write_text(content)
    assert fastpath.load(path) is None


def test_missing_stamp_file(tmp_path):
    assert fastpath.load(tmp_path / "absent.txt") is None


def test_stamp_path_depends_on_the_key(tmp_path):
    assert fastpath.stamp_path(tmp_path, "Debug|app") != fastpath.stamp_path(tmp_path, "Release|app")
    assert fastpath.stamp_path(tmp_path, "k") == fastpath.stamp_path(tmp_path, "k")


# ============================================================ through the builder
@pytest.fixture
def old_files(monkeypatch):
    """Let stamps be written right away (the racy window is a real-time safeguard)."""
    monkeypatch.setattr(fastpath, "RACY_WINDOW_NS", 0)


def _spy_on_planning(monkeypatch):
    calls = []
    real = builder.plan_workspace

    def spy(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(builder, "plan_workspace", spy)
    return calls


SOURCES = {"a.cpp": "int a();", "b.cpp": "int b();", "main.cpp": "int main(){}"}


def build(ws, fake, **kw):
    return builder.build_workspace(ws, GCC, OS.LINUX, run=fake, **kw)


def test_second_build_is_answered_without_planning(tmp_path, monkeypatch, old_files):
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain()
    first = build(ws, fake)
    assert first.ok and not first.targets[0].skipped
    planned = _spy_on_planning(monkeypatch)
    second = build(ws, fake)
    assert second.ok and second.targets[0].skipped and planned == []
    assert second.targets[0].up_to_date == 4 and second.targets[0].output_path == first.targets[0].output_path


def test_fast_path_emits_target_events(tmp_path, old_files):
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain()
    build(ws, fake)
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e.type), sync=True)
    build(ws, fake, bus=bus)
    assert seen == ["graph.analyzed", "target.up_to_date"]


@pytest.mark.parametrize("change", ["edit_source", "new_source", "delete_source", "flag", "delete_output",
                                    "config", "header"])
def test_any_relevant_change_falls_back_to_the_engine(tmp_path, monkeypatch, old_files, change):
    (tmp_path / "h.h").write_text("v1")
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain(headers={"a": [tmp_path / "h.h"]})
    first = build(ws, fake)
    planned = _spy_on_planning(monkeypatch)
    config = "Debug"
    if change == "edit_source":
        (tmp_path / "a.cpp").write_text("int a(); // changed")
    elif change == "new_source":
        (tmp_path / "c.cpp").write_text("int c();")
    elif change == "delete_source":
        (tmp_path / "b.cpp").unlink()
    elif change == "flag":
        ws.targets["app"].define_macros.append("X=1")
    elif change == "delete_output":
        first.targets[0].output_path.unlink()
    elif change == "config":
        config = "Release"
    elif change == "header":
        (tmp_path / "h.h").write_text("v2 (different size)")
    result = build(ws, fake, config=config)
    assert result.ok and planned, f"{change}: the engine should have been consulted"
    assert not result.targets[0].skipped


def test_touch_without_change_goes_through_the_engine_and_is_then_fast_again(tmp_path, monkeypatch, old_files):
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain()
    build(ws, fake)
    earlier = time.time() - 100                      # a different mtime, in the past (a future one is
    os.utime(tmp_path / "a.cpp", (earlier, earlier))  # always suspect and would never be stamped)
    planned = _spy_on_planning(monkeypatch)
    again = build(ws, fake)
    assert planned and again.targets[0].skipped                 # the engine proved nothing changed...
    planned.clear()
    third = build(ws, fake)
    assert planned == [] and third.targets[0].skipped           # ...and a fresh stamp makes it fast again


def test_a_failed_build_leaves_no_stamp_behind(tmp_path, monkeypatch, old_files):
    ws = make_workspace(tmp_path, SOURCES)
    assert not build(ws, FakeToolchain(fail_on={"b"})).ok
    planned = _spy_on_planning(monkeypatch)
    ok = build(ws, FakeToolchain())
    assert planned and ok.ok


def test_fast_path_can_be_disabled(tmp_path, monkeypatch, old_files):
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain()
    build(ws, fake)
    planned = _spy_on_planning(monkeypatch)
    assert build(ws, fake, fast_path=False).targets[0].skipped and planned


def test_different_target_subsets_have_independent_stamps(tmp_path, monkeypatch, old_files):
    for n in ("a", "b"):
        (tmp_path / f"{n}.cpp").write_text(f"int {n}();")
    from charpente.dsl.model import Target, Workspace

    ws = Workspace(name="D", location=tmp_path)
    ws.add_target(Target(name="a", source_patterns=["a.cpp"], location=tmp_path))
    ws.add_target(Target(name="b", source_patterns=["b.cpp"], location=tmp_path))
    fake = FakeToolchain()
    build(ws, fake)
    build(ws, fake, only=["a"])
    planned = _spy_on_planning(monkeypatch)
    assert build(ws, fake).targets[0].skipped
    assert build(ws, fake, only=["a"]).targets[0].skipped
    assert planned == []


def test_racy_default_never_trusts_a_freshly_written_tree(tmp_path, monkeypatch):
    """With the real 2 s window, a build that just wrote its outputs is not stamped."""
    ws = make_workspace(tmp_path, SOURCES)
    fake = FakeToolchain()
    build(ws, fake)
    planned = _spy_on_planning(monkeypatch)
    assert build(ws, fake).targets[0].skipped
    assert planned                                               # engine was used: no stamp yet
