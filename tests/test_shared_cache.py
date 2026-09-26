"""The shared (LAN/CI) build cache: the server, the client, signing, fail-open behaviour, and real builds hitting entries another checkout uploaded."""
import hashlib
import http.client
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from charpente.cli import main
from charpente.core import hashing
from charpente.core.cache import LocalCache
from charpente.core.cache_server import CacheServer
from charpente.core.remote import RemoteCache, TieredCache, entry_is_valid, from_environment, sign_entry
from charpente.errors import ChError

HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++"))


def digest_of(data: bytes) -> str:
    return hashing.digest_bytes(data)


@pytest.fixture
def server(tmp_path):
    srv = CacheServer(tmp_path / "server")
    srv.start()
    yield srv
    srv.shutdown()


def http_call(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection(server.host, server.port, timeout=20)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, data


# ---------------------------------------------------------------------- the server
def test_blobs_are_checked_against_their_names(server):
    data = b"some object file"
    name = digest_of(data).replace(":", "-")
    assert http_call(server, "PUT", f"/cas/{name}", data)[0] == 201
    assert http_call(server, "GET", f"/cas/{name}") == (200, data)
    assert http_call(server, "HEAD", f"/cas/{name}")[0] == 200
    assert http_call(server, "PUT", f"/cas/{name}", b"something else")[0] == 400                    # the body must hash to its name
    assert http_call(server, "GET", f"/cas/{digest_of(b'absent').replace(':', '-')}")[0] == 404
    assert http_call(server, "PUT", "/cas/xx-1234", b"x")[0] in (400, 415)                          # an unknown digest algorithm


def test_entries_must_be_json_objects_and_names_safe(server):
    assert http_call(server, "PUT", "/ac/b3-abc", b'{"outputs": []}')[0] == 201
    assert http_call(server, "GET", "/ac/b3-abc") == (200, b'{"outputs": []}')
    assert http_call(server, "PUT", "/ac/b3-abd", b"not json")[0] == 400
    assert http_call(server, "PUT", "/ac/b3-abe", b"[1, 2]")[0] == 400
    assert http_call(server, "PUT", "/mf/k1", b'{"header_sets": [["a.h"]]}')[0] == 201
    for path in ["/ac/..%2f..%2fx", "/ac/a%2Fb", "/ac/", "/cas", "/other/x", "/ac/x/y", "/ac/.hidden", "/ac/" + "a" * 300]:
        assert http_call(server, "GET", path)[0] == 404, path
    assert not any(server.cache.root.parent.glob("x"))


def test_size_limits_and_read_only(tmp_path):
    small = CacheServer(tmp_path / "s", max_blob=10)
    small.start()
    try:
        assert http_call(small, "PUT", f"/cas/{digest_of(b'x' * 50).replace(':', '-')}", b"x" * 50)[0] == 413
        assert http_call(small, "PUT", "/ac/k", b'{"a": 1}')[0] == 201
    finally:
        small.shutdown()
    mirror = CacheServer(tmp_path / "m", readonly=True)
    mirror.start()
    try:
        assert http_call(mirror, "PUT", "/ac/k", b"{}")[0] == 403
        assert json.loads(http_call(mirror, "GET", "/health")[1]) == {"charpente-cache": 1, "readonly": True}
    finally:
        mirror.shutdown()


def test_a_token_is_required_when_set_and_a_public_bind_needs_one(tmp_path):
    srv = CacheServer(tmp_path / "s", token="s3cret")
    srv.start()
    try:
        assert http_call(srv, "GET", "/health")[0] == 401
        assert http_call(srv, "GET", "/health", headers={"Authorization": "Bearer wrong"})[0] == 401
        assert http_call(srv, "PUT", "/ac/k", b"{}")[0] == 401
        assert http_call(srv, "GET", "/health", headers={"Authorization": "Bearer s3cret"})[0] == 200
    finally:
        srv.shutdown()
    with pytest.raises(ValueError, match="needs a token"):
        CacheServer(tmp_path / "t", host="0.0.0.0")
    other = CacheServer(tmp_path / "u", host="0.0.0.0", token="x")                                  # allowed once there is a token
    other.shutdown()


# ---------------------------------------------------------------------- the client
def test_the_client_round_trips_and_verifies_downloads(server, tmp_path):
    remote = RemoteCache(server.url)
    data = b"payload"
    digest = digest_of(data)
    source = tmp_path / "src.bin"
    source.write_bytes(data)
    assert remote.put_blob(digest, source) and remote.has_blob(digest)
    assert remote.get_blob(digest, tmp_path / "out" / "copy.bin") and (tmp_path / "out" / "copy.bin").read_bytes() == data
    assert remote.put_entry("k1", {"outputs": [{"digest": digest, "size": 7, "mode": 420}]}) and remote.get_entry("k1")["outputs"][0]["digest"] == digest
    assert remote.get_entry("missing") is None and remote.get_manifest("nope") == []
    assert remote.put_manifest("k1", [["a.h"], ["b.h"]]) and remote.get_manifest("k1") == [["a.h"], ["b.h"]]
    assert remote.health() == {"charpente-cache": 1, "readonly": False}
    assert RemoteCache(server.url, readonly=True).put_blob(digest, source) is False                   # a read-only client never uploads


def test_a_substituted_blob_is_refused(server, tmp_path):
    good = digest_of(b"the real object")
    path = server.cache._blob(good)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"a malicious replacement")                                                       # what a compromised server could serve
    remote = RemoteCache(server.url)
    assert remote.get_blob(good, tmp_path / "x.bin") is False and not (tmp_path / "x.bin").exists()
    assert any("wrong file" in w for w in remote.warnings)


def test_entries_are_signed_and_unsigned_or_forged_ones_rejected(server):
    signed = RemoteCache(server.url, signing_key="team-key")
    assert signed.put_entry("k", {"outputs": [], "duration": 1.0})
    assert signed.get_entry("k") is not None
    assert RemoteCache(server.url, signing_key="another-key").get_entry("k") is None                   # wrong key
    assert RemoteCache(server.url).get_entry("k") is not None                                          # no key: signatures are not checked
    RemoteCache(server.url).put_entry("plain", {"outputs": []})
    strict = RemoteCache(server.url, signing_key="team-key")
    assert strict.get_entry("plain") is None and strict.rejected == 1 and any("no valid signature" in w for w in strict.warnings)
    tampered = json.loads(http_call(server, "GET", "/ac/k")[1])
    tampered["duration"] = 99.0
    http_call(server, "PUT", "/ac/forged", json.dumps(tampered).encode())
    assert RemoteCache(server.url, signing_key="team-key").get_entry("forged") is None                 # altered after signing


def test_signatures_cover_every_field_and_ignore_key_order():
    a = {"outputs": [{"digest": "b3:1"}], "duration": 1.0}
    b = {"duration": 1.0, "outputs": [{"digest": "b3:1"}]}
    assert sign_entry(a, "k") == sign_entry(b, "k") != sign_entry({**a, "duration": 2.0}, "k")
    assert entry_is_valid({**a, "sig": sign_entry(a, "k")}, "k") and not entry_is_valid(a, "k") and entry_is_valid(a, None)


def test_a_remote_that_is_down_is_skipped_with_one_warning_and_never_raises(tmp_path):
    down = CacheServer(tmp_path / "gone")
    url = down.url
    down.shutdown()
    remote = RemoteCache(url, timeout=1)
    for _ in range(3):
        assert remote.get_entry("k") is None and remote.get_manifest("k") == [] and remote.has_blob("b3:x") is False
    assert len(remote.warnings) == 1 and "unreachable" in remote.warnings[0]
    assert remote.health() is None


def test_a_wrong_token_is_reported_as_the_cache_refusing_not_as_a_crash(tmp_path):
    srv = CacheServer(tmp_path / "s", token="right")
    srv.start()
    try:
        remote = RemoteCache(srv.url, token="wrong")
        assert remote.get_entry("k") is None and "401" in remote.warnings[0]
    finally:
        srv.shutdown()


def test_the_environment_decides_and_insecure_setups_are_refused(tmp_path):
    local = LocalCache(tmp_path / "l")
    assert from_environment(local, {}) is local
    assert isinstance(from_environment(local, {"CHARPENTE_REMOTE_CACHE": "http://127.0.0.1:1"}), TieredCache)
    assert isinstance(from_environment(local, {"CHARPENTE_REMOTE_CACHE": "http://localhost:1"}), TieredCache)
    assert isinstance(from_environment(local, {"CHARPENTE_REMOTE_CACHE": "https://cache.example.com"}), TieredCache)
    lan = {"CHARPENTE_REMOTE_CACHE": "http://192.168.1.5:8080"}
    with pytest.raises(ChError) as info:
        from_environment(local, lan)
    assert info.value.code == "CH8028" and "signed" in info.value.message
    assert isinstance(from_environment(local, {**lan, "CHARPENTE_CACHE_SIGNING_KEY": "k"}), TieredCache)
    assert isinstance(from_environment(local, {**lan, "CHARPENTE_REMOTE_CACHE_INSECURE": "1"}), TieredCache)
    for bad in ("ftp://x", "not a url", "http://"):
        with pytest.raises(ChError):
            from_environment(local, {"CHARPENTE_REMOTE_CACHE": bad})
    assert from_environment(local, {"CHARPENTE_REMOTE_CACHE": "http://127.0.0.1:1", "CHARPENTE_REMOTE_CACHE_MODE": "readonly"}).remote.readonly is True


# ---------------------------------------------------------------------- the tiered cache alone
def test_a_hit_in_the_shared_cache_is_copied_to_the_local_one(server, tmp_path):
    uploader = TieredCache(LocalCache(tmp_path / "uploader"), RemoteCache(server.url))
    product = tmp_path / "product.o"
    product.write_bytes(b"compiled")
    assert uploader.store("key-1", [product], stdout="warning: x", duration=0.5)
    uploader.flush()
    fresh = TieredCache(LocalCache(tmp_path / "fresh"), RemoteCache(server.url))
    entry = fresh.lookup("key-1")
    assert entry is not None and entry.stdout == "warning: x" and fresh.origin("key-1") == "remote" and fresh.remote_hits == 1
    destination = tmp_path / "restored.o"
    assert fresh.restore(entry, [destination]) and destination.read_bytes() == b"compiled"
    server.shutdown()                                                                                   # now it is local: the server is not needed again
    again = fresh.lookup("key-1")
    assert again is not None and fresh.local.hits >= 1
    assert TieredCache(LocalCache(tmp_path / "third"), RemoteCache(server.url, timeout=1)).lookup("key-1") is None


def test_manifests_travel_too(server, tmp_path):
    first = TieredCache(LocalCache(tmp_path / "one"), RemoteCache(server.url))
    first.add_to_manifest("k", ["@ROOT@/inc/a.h", "/usr/include/x.h"])
    first.flush()
    second = TieredCache(LocalCache(tmp_path / "two"), RemoteCache(server.url))
    assert second.manifest("k") == [["@ROOT@/inc/a.h", "/usr/include/x.h"]]
    assert LocalCache(tmp_path / "two").manifest("k") == [["@ROOT@/inc/a.h", "/usr/include/x.h"]]      # remembered locally


def test_an_entry_whose_blob_cannot_be_fetched_is_a_miss(server, tmp_path):
    remote = RemoteCache(server.url)
    remote.put_entry("dangling", {"outputs": [{"digest": digest_of(b"never uploaded"), "size": 1, "mode": 420}]})
    assert TieredCache(LocalCache(tmp_path / "l"), RemoteCache(server.url)).lookup("dangling") is None


# ---------------------------------------------------------------------- real builds
def make_project(base: Path, name: str = "proj") -> Path:
    root = base / name
    (root / "src" / "core").mkdir(parents=True)
    (root / "sc.charpente").write_bytes(b'''from charpente import *

with Workspace("sc") as ws:
    with Target("core") as core:
        core.kind(Kind.STATIC_LIBRARY)
        core.standard("c++17")
        core.sources(["src/core/*.cpp"])
        core.public_include_dirs(["src/core"])
    with Target("app") as app:
        app.kind(Kind.EXECUTABLE)
        app.standard("c++17")
        app.sources(["src/main.cpp"])
        app.uses("core")
''')
    (root / "src" / "core" / "answer.hpp").write_bytes(b"#pragma once\nint answer();\n")
    (root / "src" / "core" / "answer.cpp").write_bytes(b'#include "answer.hpp"\nint answer() { return 42; }\n')
    (root / "src" / "main.cpp").write_bytes(b'#include <cstdio>\n#include "answer.hpp"\nint main() { std::printf("%d\\n", answer()); return 0; }\n')
    return root


def sources_of_hits(capsys):
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    hits = [e["payload"].get("source") for e in events if e["type"] == "action.cache_hit"]
    executed = [e for e in events if e["type"] == "action.finished"]
    hints = [e["payload"]["message"] for e in events if e["type"] == "hint.emitted" and e["payload"].get("code") == "cache.remote"]
    return hits, len(executed), hints


def build_in(monkeypatch, capsys, folder: Path, cache_dir: Path, *flags: str):
    monkeypatch.chdir(folder)
    monkeypatch.setenv("CHARPENTE_CACHE_DIR", str(cache_dir))
    code = main(["build", "--output", "jsonl", *flags])
    return (code, *sources_of_hits(capsys))


def output_of(folder: Path, config="Release", flavour="-repro"):
    return next((folder / "build" / f"{config}{flavour}" / "app").glob("app*"))


@pytest.fixture
def shared(monkeypatch, server):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.setenv("CHARPENTE_REMOTE_CACHE", server.url)
    monkeypatch.delenv("CHARPENTE_CACHE_SIGNING_KEY", raising=False)
    return server


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_a_second_checkout_in_another_folder_gets_everything_from_the_shared_cache(shared, tmp_path, monkeypatch, capsys):
    first = make_project(tmp_path / "alice" / "work")
    second = make_project(tmp_path / "bob" / "somewhere" / "else")
    code, hits, executed, _ = build_in(monkeypatch, capsys, first, tmp_path / "cache-a", "--reproducible", "--config", "Release")
    assert code == 0 and hits == [] and executed == 4                                                    # everything was built (2 compiles, an archive, a link) and uploaded
    assert shared.cache.stats().entries >= 3
    code, hits, executed, _ = build_in(monkeypatch, capsys, second, tmp_path / "cache-b", "--reproducible", "--config", "Release")
    assert code == 0 and executed == 0 and hits and set(hits) == {"remote"}                            # nothing compiled: all from the shared cache
    assert output_of(first).read_bytes() == output_of(second).read_bytes()                              # and the result is byte-identical
    assert subprocess.run([str(output_of(second))], capture_output=True, text=True).stdout.strip() == "42"
    code, hits, executed, _ = build_in(monkeypatch, capsys, second, tmp_path / "cache-b", "--reproducible", "--config", "Release")
    assert code == 0 and executed == 0                                                                  # up to date now (nothing to fetch either)


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_without_the_reproducible_flavour_another_folder_cannot_share_but_the_same_folder_can(shared, tmp_path, monkeypatch, capsys):
    first = make_project(tmp_path / "one")
    other = make_project(tmp_path / "two" / "deeper")
    assert build_in(monkeypatch, capsys, first, tmp_path / "ca")[0] == 0
    _, hits, executed, _ = build_in(monkeypatch, capsys, other, tmp_path / "cb")
    assert hits == [] and executed > 0                                                                  # keys include the folder: sound, just no sharing
    shutil.rmtree(first / "build")
    _, hits, executed, _ = build_in(monkeypatch, capsys, first, tmp_path / "cc")                        # same folder, a fresh local cache (a CI runner)
    assert executed == 0 and set(hits) == {"remote"}


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_a_changed_header_rebuilds_its_dependents_and_stops_where_the_objects_do_not_change(shared, tmp_path, monkeypatch, capsys):
    first = make_project(tmp_path / "a")
    second = make_project(tmp_path / "b" / "b")
    build_in(monkeypatch, capsys, first, tmp_path / "ca", "--reproducible", "--config", "Release")
    (second / "src" / "core" / "answer.hpp").write_bytes(b"#pragma once\nint answer();\n// edited\n")
    code, hits, executed, _ = build_in(monkeypatch, capsys, second, tmp_path / "cb", "--reproducible", "--config", "Release")
    # Both compiles include the header, so both are rebuilt; but a comment does not change the objects, so the archive and the link
    # (keyed by the objects' contents) are found in the shared cache: content addressing cuts the rebuild off.
    assert code == 0 and executed == 2 and hits == ["remote", "remote"]


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_signed_entries_are_shared_within_a_team_and_ignored_across_teams(shared, tmp_path, monkeypatch, capsys):
    first = make_project(tmp_path / "a")
    second = make_project(tmp_path / "b" / "b")
    third = make_project(tmp_path / "c" / "c")
    monkeypatch.setenv("CHARPENTE_CACHE_SIGNING_KEY", "team-secret")
    build_in(monkeypatch, capsys, first, tmp_path / "ca", "--reproducible", "--config", "Release")
    _, hits, executed, _ = build_in(monkeypatch, capsys, second, tmp_path / "cb", "--reproducible", "--config", "Release")
    assert executed == 0 and set(hits) == {"remote"}
    monkeypatch.setenv("CHARPENTE_CACHE_SIGNING_KEY", "someone-elses-key")
    code, hits, executed, hints = build_in(monkeypatch, capsys, third, tmp_path / "cc", "--reproducible", "--config", "Release")
    assert code == 0 and executed > 0 and hits == [] and any("no valid signature" in h for h in hints)   # the build still works; nothing untrusted was used


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_a_read_only_client_uses_the_cache_but_never_writes_to_it(shared, tmp_path, monkeypatch, capsys):
    first = make_project(tmp_path / "a")
    second = make_project(tmp_path / "b" / "b")
    build_in(monkeypatch, capsys, first, tmp_path / "ca", "--reproducible", "--config", "Release")
    before = shared.cache.stats()
    monkeypatch.setenv("CHARPENTE_REMOTE_CACHE_MODE", "readonly")
    (second / "src" / "main.cpp").write_bytes(b'#include <cstdio>\n#include "answer.hpp"\nint main() { std::printf("new %d\\n", answer()); return 0; }\n')
    code, hits, executed, _ = build_in(monkeypatch, capsys, second, tmp_path / "cb", "--reproducible", "--config", "Release")
    assert code == 0 and hits.count("remote") >= 1 and executed >= 1
    assert shared.cache.stats() == before                                                               # what it built stayed local


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_a_shared_cache_that_is_down_never_fails_the_build(tmp_path, monkeypatch, capsys):
    gone = CacheServer(tmp_path / "gone")
    url = gone.url
    gone.shutdown()
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.setenv("CHARPENTE_REMOTE_CACHE", url)
    project = make_project(tmp_path / "p")
    code, hits, executed, hints = build_in(monkeypatch, capsys, project, tmp_path / "c")
    assert code == 0 and hits == [] and executed > 0
    assert len(hints) == 1 and "unreachable" in hints[0]                                                # said once, not per action


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_an_unsafe_configuration_stops_the_build_with_a_coded_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.setenv("CHARPENTE_REMOTE_CACHE", "http://192.168.1.5:8080")
    monkeypatch.delenv("CHARPENTE_CACHE_SIGNING_KEY", raising=False)
    monkeypatch.chdir(make_project(tmp_path / "p"))
    assert main(["build"]) != 0
    assert "CH8028" in capsys.readouterr().err
    assert main(["build", "--no-cache"]) == 0                                                           # opting out of caching needs no cache configuration


# ---------------------------------------------------------------------- commands
def test_cache_remote_reports_the_state(server, monkeypatch, capsys):
    monkeypatch.delenv("CHARPENTE_REMOTE_CACHE", raising=False)
    assert main(["cache", "remote"]) == 0 and "No shared cache" in capsys.readouterr().out
    monkeypatch.setenv("CHARPENTE_REMOTE_CACHE", server.url)
    monkeypatch.setenv("CHARPENTE_CACHE_SIGNING_KEY", "k")
    assert main(["cache", "remote"]) == 0
    out = capsys.readouterr().out
    assert "answers:  yes" in out and "read-write" in out and "signed and verified" in out
    monkeypatch.setenv("CHARPENTE_REMOTE_CACHE", "http://127.0.0.1:9")
    assert main(["cache", "remote"]) == 1 and "NO" in capsys.readouterr().out


def test_the_serve_command_needs_a_token_beyond_this_machine(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CHARPENTE_CACHE_SERVER_TOKEN", raising=False)
    assert main(["cache", "serve", "--dir", str(tmp_path / "s"), "--host", "0.0.0.0", "--port", "0"]) != 0
    err = capsys.readouterr().err
    assert "CH8028" in err and "CHARPENTE_CACHE_SERVER_TOKEN" in err


def test_the_serve_command_serves_and_can_be_stopped(tmp_path):
    proc = subprocess.Popen([sys.executable, "-m", "charpente", "cache", "serve", "--dir", str(tmp_path / "s"), "--port", "0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=dict(os.environ))
    try:
        line = proc.stdout.readline().decode()
        url = line.split(": ")[1].split()[0]
        host, port = url.replace("http://", "").split(":")
        connection = http.client.HTTPConnection(host, int(port), timeout=20)
        connection.request("GET", "/health")
        assert connection.getresponse().status == 200
    finally:
        proc.terminate()
        proc.wait(timeout=30)
    assert hashlib.sha256(b"x").hexdigest()
