import os
import sqlite3
import time

from charpente.core import hashing
from charpente.core.cache import CacheEntry, LocalCache
from charpente.core.state import MISSING, RACY_WINDOW_NS, ActionRecord, FileHasher, StateDB
from charpente.core.toolid import UNRESOLVED, ToolIdentities


def _record(**kw):
    base = dict(key="k", argv=["cc", "-c", "a.c"], cwd="/w", tool="/usr/bin/cc|1|d", env=[("A", "1")],
                inputs={"/w/a.c": "b3:x"}, deps={"/w/a.h": "b3:y"}, outputs={"/w/a.o": [1, 2]}, duration=0.5)
    base.update(kw)
    return ActionRecord(**base)


# ============================================================ StateDB
def test_action_records_round_trip_and_persist(tmp_path):
    db = StateDB(tmp_path / "s" / "state.db")
    db.put_action("compile:a", _record())
    db.close()
    again = StateDB(tmp_path / "s" / "state.db")
    rec = again.get_action("compile:a")
    assert rec is not None and rec.argv == ["cc", "-c", "a.c"] and rec.env == [("A", "1")]
    assert rec.deps == {"/w/a.h": "b3:y"} and rec.duration == 0.5
    assert again.action_ids() == ["compile:a"]
    again.delete_action("compile:a")
    assert again.get_action("compile:a") is None
    again.close()


def test_file_digests_persist(tmp_path):
    db = StateDB(tmp_path / "state.db")
    db.put_file("k", 5, 6, "b3:d", False)
    db.flush()
    db.close()
    assert StateDB(tmp_path / "state.db").get_file("k") == (5, 6, "b3:d", 0)


def test_a_corrupt_database_is_discarded_not_trusted(tmp_path):
    path = tmp_path / "state.db"
    path.write_bytes(b"this is not a sqlite database at all" * 100)
    db = StateDB(path)          # must not raise
    assert db.action_ids() == []
    db.put_action("a", _record())
    assert db.get_action("a") is not None
    db.close()


def test_an_old_schema_version_is_discarded(tmp_path):
    path = tmp_path / "state.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE actions(id TEXT PRIMARY KEY, data TEXT)")
    conn.execute("INSERT INTO actions VALUES('a', '{}')")
    conn.execute("PRAGMA user_version=1")
    conn.commit()
    conn.close()
    db = StateDB(path)
    assert db.action_ids() == []
    db.close()


def test_a_garbled_record_reads_as_missing(tmp_path):
    db = StateDB(tmp_path / "state.db")
    db._actions["bad"] = "{not json"
    assert db.get_action("bad") is None
    db._actions["odd"] = '{"unexpected": 1}'
    assert db.get_action("odd") is None
    db.close()


# ============================================================ FileHasher
def test_file_hasher_reads_once_then_trusts_stat(tmp_path):
    f = tmp_path / "a.h"
    f.write_text("content")
    old = time.time() - 3600
    os.utime(f, (old, old))                       # old enough to be beyond the racy window
    db = StateDB(tmp_path / "state.db")
    h1 = FileHasher(db)
    d = h1.digest(f)
    assert d == hashing.digest_bytes(b"content") and h1.reads == 1
    assert h1.digest(f) == d and h1.reads == 1    # session memo

    h2 = FileHasher(db)                           # a new session: persisted stat memo
    assert h2.digest(f) == d and h2.reads == 0
    db.close()


def test_content_change_is_detected_even_if_mtime_and_size_are_equal_when_racy(tmp_path):
    """The racy-timestamp case: a same-size edit within the timestamp tick."""
    f = tmp_path / "a.h"
    f.write_text("aaaa")
    st = f.stat()
    db = StateDB(tmp_path / "state.db")
    h1 = FileHasher(db)
    first = h1.digest(f)                          # just written: recorded as racy
    f.write_text("bbbb")                          # same size ...
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))   # ... and the very same mtime
    h2 = FileHasher(db)
    assert h2.digest(f) != first and h2.reads == 1
    db.close()


def test_old_files_are_not_racy(tmp_path):
    f = tmp_path / "a.h"
    f.write_text("x")
    old = time.time() - 10
    os.utime(f, (old, old))
    db = StateDB(tmp_path / "state.db")
    FileHasher(db).digest(f)
    assert db.get_file(os.path.normcase(os.path.abspath(f)))[3] == 0
    assert RACY_WINDOW_NS == 2_000_000_000
    db.close()


def test_missing_and_directories_have_the_missing_digest(tmp_path):
    h = FileHasher(None)
    assert h.digest(tmp_path / "nope") == MISSING
    assert h.digest(tmp_path) == MISSING


def test_invalidate_forces_a_reread(tmp_path):
    f = tmp_path / "x"
    f.write_text("1")
    h = FileHasher(None)
    a = h.digest(f)
    f.write_text("2")
    assert h.digest(f) == a          # memoised for the session
    h.invalidate(f)
    assert h.digest(f) != a
    h.forget_all()


# ============================================================ cache
def _out(tmp_path, name, data=b"obj"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_store_lookup_restore(tmp_path):
    cache = LocalCache(tmp_path / "cache")
    out = _out(tmp_path, "a.o", b"object bytes")
    assert cache.store("b3:key", [out], stdout="warn", stderr="", duration=1.5)
    entry = cache.lookup("b3:key")
    assert isinstance(entry, CacheEntry) and entry.stdout == "warn" and entry.duration == 1.5
    dest = tmp_path / "restored" / "a.o"
    assert cache.restore(entry, [dest]) and dest.read_bytes() == b"object bytes"
    assert cache.hits == 1


def test_miss_is_counted_and_returns_none(tmp_path):
    cache = LocalCache(tmp_path / "cache")
    assert cache.lookup("b3:nothing") is None and cache.misses == 1


def test_identical_content_is_stored_once(tmp_path):
    cache = LocalCache(tmp_path / "cache")
    a, b = _out(tmp_path, "a.o", b"same"), _out(tmp_path, "b.o", b"same")
    cache.store("k1", [a])
    cache.store("k2", [b])
    assert cache.stats().blobs == 1 and cache.stats().entries == 2


def test_an_entry_whose_blob_vanished_is_dropped(tmp_path):
    cache = LocalCache(tmp_path / "cache")
    cache.store("k", [_out(tmp_path, "a.o", b"zzz")])
    for blob in (tmp_path / "cache" / "cas").rglob("*"):
        if blob.is_file():
            blob.unlink()
    assert cache.lookup("k") is None
    assert cache.stats().entries == 0


def test_restore_refuses_a_wrong_number_of_destinations(tmp_path):
    cache = LocalCache(tmp_path / "cache")
    cache.store("k", [_out(tmp_path, "a.o")])
    entry = cache.lookup("k")
    assert cache.restore(entry, [tmp_path / "x", tmp_path / "y"]) is False


def test_store_fails_cleanly_for_a_missing_output(tmp_path):
    cache = LocalCache(tmp_path / "cache")
    assert cache.store("k", [tmp_path / "does-not-exist"]) is False
    assert cache.lookup("k") is None


def test_manifest_keeps_most_recent_first_and_is_bounded(tmp_path):
    cache = LocalCache(tmp_path / "cache")
    assert cache.manifest("k") == []
    cache.add_to_manifest("k", ["a.h"])
    cache.add_to_manifest("k", ["a.h", "b.h"])
    cache.add_to_manifest("k", ["a.h"])           # moves to the front, no duplicate
    assert cache.manifest("k") == [["a.h"], ["a.h", "b.h"]]
    for i in range(40):
        cache.add_to_manifest("k", [f"h{i}.h"])
    assert len(cache.manifest("k")) == 16


def test_gc_evicts_least_recently_used_first(tmp_path):
    cache = LocalCache(tmp_path / "cache")
    for i in range(4):
        cache.store(f"k{i}", [_out(tmp_path, f"o{i}", bytes([i]) * 1000)])
    blobs = sorted(p for p in (tmp_path / "cache" / "cas").rglob("*") if p.is_file())
    now = time.time()
    for age, blob in enumerate(blobs):                      # blob 0 oldest
        os.utime(blob, (now - 1000 + age, now - 1000 + age))
    freed = cache.gc(2500)
    assert freed >= 2000
    assert cache.stats().bytes <= 2500


def test_clear_removes_everything(tmp_path):
    cache = LocalCache(tmp_path / "cache")
    cache.store("k", [_out(tmp_path, "a.o")])
    cache.clear()
    assert cache.stats().entries == 0 and not (tmp_path / "cache").exists()


def test_default_cache_dir_honours_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARPENTE_CACHE_DIR", str(tmp_path / "c"))
    assert LocalCache().root == (tmp_path / "c").resolve()


# ============================================================ tool identity
def test_unresolvable_tool_has_an_unresolved_identity(tmp_path):
    ids = ToolIdentities(which=lambda name: None, persist=False)
    ident = ids.identify("no-such-compiler")
    assert ident.digest == UNRESOLVED and not ident.resolved


def test_identity_of_a_real_file_includes_version_and_digest(tmp_path):
    import sys
    ids = ToolIdentities(persist=False)
    ident = ids.identify(sys.executable)
    assert ident.resolved and ident.path and ident.digest.startswith(("b3:", "b2:"))
    assert "Python" in ident.version
    assert ids.identify(sys.executable) is ident            # memoised


def test_identity_is_remembered_on_disk_and_not_recomputed(tmp_path, monkeypatch):
    import sys

    from charpente.core import process

    calls = []
    real_run = process.run

    def counting(argv, **kw):
        calls.append(argv)
        return real_run(argv, **kw)

    monkeypatch.setattr(process, "run", counting)
    ToolIdentities().identify(sys.executable)
    assert len(calls) == 1
    ToolIdentities().identify(sys.executable)              # a fresh session: served from disk
    assert len(calls) == 1
