"""`charpente dev` and hot reload: change detection, generations, and a real running host that swaps a plugin without restarting."""
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from charpente import dev
from charpente.cli import main
from charpente.dsl.loader import load_workspace

HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++"))


# ---------------------------------------------------------------------- change detection
def test_snapshots_and_changes(tmp_path):
    a, b = tmp_path / "a.cpp", tmp_path / "b.cpp"
    a.write_text("1", encoding="utf-8")
    first = dev.snapshot([a, b])                                                    # b does not exist: absent, not an error
    assert list(first) == [str(a)]
    assert dev.changes(first, dev.snapshot([a, b])) == []
    b.write_text("2", encoding="utf-8")
    a.write_text("changed!", encoding="utf-8")
    second = dev.snapshot([a, b])
    assert dev.changes(first, second) == sorted([str(a), str(b)])                    # a modified (size), b added
    b.unlink()
    assert dev.changes(second, dev.snapshot([a, b])) == [str(b)]                    # removed


def test_the_watcher_reports_once_and_notices_new_files(tmp_path):
    (tmp_path / "x.cpp").write_text("1", encoding="utf-8")
    found = lambda: sorted(tmp_path.glob("*.cpp"))  # noqa: E731
    watcher = dev.Watcher(found)
    assert watcher.poll() == []
    (tmp_path / "y.cpp").write_text("2", encoding="utf-8")
    assert watcher.poll() == [str(tmp_path / "y.cpp")]
    assert watcher.poll() == []                                                      # reported once


WORKSPACE = '''import sys
from charpente import *

with Workspace("hot") as ws:
    ws.requires("charpente-hot")
    with Target("plug") as plug:
        plug.kind(Kind.PLUGIN)
        plug.standard("c++17")
        plug.sources(["src/plug.cpp"])
    with Target("host") as host:
        host.kind(Kind.EXECUTABLE)
        host.standard("c++17")
        host.sources(["src/host.cpp"])
        host.uses("charpente-hot")
        if sys.platform != "win32":
            host.links(["dl"])
'''
PLUGIN = '''#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif
extern "C" EXPORT int plugin_value(void) { return %d; }
'''
HOST = '''#include <stdio.h>
#include "charpente_hot.h"
#ifdef _WIN32
#include <windows.h>
static void nap() { Sleep(100); }
#else
#include <unistd.h>
static void nap() { usleep(100000); }
#endif
int main(int argc, char** argv) {
    ch_hot hot;
    typedef int (*value_fn)(void);
    value_fn value = NULL;
    if (argc < 2 || ch_hot_open(&hot, argv[1]) != 0) return 2;
    for (int i = 0; i < 900; i++) {
        int reloaded = ch_hot_poll(&hot);
        if (reloaded == 1) value = (value_fn)ch_hot_symbol(&hot, "plugin_value");
        if (value) printf("gen=%ld value=%d\\n", ch_hot_generation(&hot), value()); else printf("waiting\\n");
        fflush(stdout);
        nap();
    }
    ch_hot_close(&hot);
    return 0;
}
'''


@pytest.fixture
def hot_project(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    (tmp_path / "src").mkdir()
    (tmp_path / "hot.charpente").write_bytes(WORKSPACE.encode())
    (tmp_path / "src" / "plug.cpp").write_bytes((PLUGIN % 1).encode())
    (tmp_path / "src" / "host.cpp").write_bytes(HOST.encode())
    return tmp_path


# ---------------------------------------------------------------------- generations (pure)
def test_publishing_numbers_generations_and_keeps_the_last_ones(tmp_path):
    hot = tmp_path / "hot"
    library = tmp_path / "plug.dll"
    published = []
    for n in range(1, 6):
        library.write_bytes(f"version {n}".encode())
        published.append(dev.publish(hot, "plug", library, keep=3))
    assert [p.generation for p in published] == [1, 2, 3, 4, 5]
    manifest = json.loads((hot / "plug.json").read_text(encoding="utf-8"))
    assert manifest["generation"] == 5 and Path(manifest["path"]).read_bytes() == b"version 5" and manifest["source"] == str(library)
    assert sorted(p.name for p in hot.glob("plug.*.dll")) == ["plug.3.dll", "plug.4.dll", "plug.5.dll"]       # the newest three stay
    assert dev.current_generation(hot, "plug") == 5 and dev.current_generation(hot, "other") == 0
    assert dev.publish(hot, "plug", library).generation == 6                                            # numbering survives a restart (it is in the manifest)


def test_the_manifest_is_valid_json_even_with_windows_paths(tmp_path):
    library = tmp_path / "dir with space" / "plug.dll"
    library.parent.mkdir()
    library.write_bytes(b"x")
    dev.publish(tmp_path / "hot", "plug", library)
    data = json.loads((tmp_path / "hot" / "plug.json").read_text(encoding="utf-8"))
    assert Path(data["path"]).is_file()


def test_watched_files_cover_sources_headers_and_the_workspace_file(hot_project):
    (hot_project / "src" / "extra.hpp").write_bytes(b"// header next to the sources")
    workspace = load_workspace(str(hot_project / "hot.charpente"))
    names = {p.name for p in dev.watched_files(workspace, hot_project / "hot.charpente")}
    assert {"plug.cpp", "host.cpp", "extra.hpp", "hot.charpente"} <= names
    assert dev.plugin_targets(workspace) == ["plug"] and dev.plugin_targets(workspace, ["host"]) == []


# ---------------------------------------------------------------------- a real host that swaps its plugin while running
class Follow:
    """A process whose output lines are collected on a thread."""

    def __init__(self, argv, cwd=None):
        self.proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd, env=dict(os.environ, CHARPENTE_TRUST_ALL="1"))
        self.lines = queue.Queue()
        self.log = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for raw in iter(self.proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            self.log.append(line)
            self.lines.put(line)

    def wait_for(self, predicate, timeout=90, what="a line"):
        end = time.time() + timeout
        while time.time() < end:
            try:
                line = self.lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if predicate(line):
                return line
        raise TimeoutError(f"timed out waiting for {what}; last lines: {self.log[-8:]}")

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_a_running_host_picks_up_each_rebuild_of_its_plugin_without_restarting(hot_project, monkeypatch):
    monkeypatch.chdir(hot_project)
    assert main(["pkg", "install"]) == 0                                                    # the local charpente-hot kit: no network
    assert main(["build"]) == 0
    host_exe = next((hot_project / "build" / "Debug" / "host").glob("host*"))
    hot_dir = hot_project / "build" / "hot"
    dev_proc = Follow([sys.executable, "-m", "charpente", "dev", "--target", "plug", "--poll", "0.2", "--hot-dir", str(hot_dir)], cwd=hot_project)
    host = None
    try:
        dev_proc.wait_for(lambda line: "generation 1 published" in line, 180, "the first generation")
        host = Follow([str(host_exe), str(hot_dir / "plug.json")], cwd=hot_project)
        host.wait_for(lambda line: line == "gen=1 value=1", 60, "the host to load generation 1")
        pid = host.proc.pid

        (hot_project / "src" / "plug.cpp").write_bytes((PLUGIN % 2).encode())                # a change: the running host must see it
        dev_proc.wait_for(lambda line: "generation 2 published" in line, 180, "generation 2")
        host.wait_for(lambda line: line == "gen=2 value=2", 60, "the running host to swap to generation 2")

        (hot_project / "src" / "plug.cpp").write_bytes(b"this is not C++ at all\n")          # a broken edit: nothing is published, the host is undisturbed
        dev_proc.wait_for(lambda line: "[FAILED]" in line or "error" in line.lower(), 180, "the failed rebuild")
        time.sleep(1.0)
        host.wait_for(lambda line: line == "gen=2 value=2", 30, "the host to keep running the last good generation")
        assert not any("generation 3 published" in line for line in dev_proc.log)

        (hot_project / "src" / "plug.cpp").write_bytes((PLUGIN % 3).encode())                # fixed: it recovers
        dev_proc.wait_for(lambda line: "generation 3 published" in line, 180, "generation 3")
        host.wait_for(lambda line: line == "gen=3 value=3", 60, "the running host to swap to generation 3")
        assert host.proc.pid == pid and host.proc.poll() is None                                # the same process the whole time
    finally:
        if host:
            host.stop()
        dev_proc.stop()


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_cycles_limits_the_loop_and_events_are_emitted(hot_project, monkeypatch):
    monkeypatch.chdir(hot_project)
    assert main(["pkg", "install"]) == 0
    follower = Follow([sys.executable, "-m", "charpente", "dev", "--target", "plug", "--poll", "0.2", "--cycles", "1", "--output", "jsonl"], cwd=hot_project)
    try:
        follower.wait_for(lambda line: '"dev.plugin_published"' in line, 180, "the initial publication")
        (hot_project / "src" / "plug.cpp").write_bytes((PLUGIN % 7).encode())
        follower.wait_for(lambda line: '"dev.rebuilt"' in line and '"changed":["plug.cpp"]' in line.replace(" ", ""), 180, "the rebuild event")
        assert follower.proc.wait(timeout=120) == 0                                          # one cycle, then it stops by itself
    finally:
        follower.stop()
    events = [json.loads(line) for line in follower.log if line.startswith("{")]
    published = [e["payload"]["generation"] for e in events if e["type"] == "dev.plugin_published"]
    assert published == [1, 2]


def test_the_hot_header_is_shipped_and_self_consistent():
    header = (Path(__file__).resolve().parents[1] / "charpente" / "kit_sources" / "hot" / "include" / "charpente_hot.h").read_text(encoding="utf-8")
    for name in ("ch_hot_open", "ch_hot_poll", "ch_hot_symbol", "ch_hot_generation", "ch_hot_close"):
        assert name in header
    assert "#ifndef CHARPENTE_HOT_H" in header and "extern \"C\"" in header
