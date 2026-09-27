"""Resource-aware builds (memory, disk, battery, heat) and resuming an interrupted build."""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from charpente import resources
from charpente.cli import main
from charpente.resources import LOW_DISK_BYTES, MEMORY_PER_JOB, Sample, plan_jobs

HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++"))
GB = 1024 ** 3


# ---------------------------------------------------------------------- the policy (pure)
def test_a_healthy_machine_runs_everything_it_was_asked_to():
    plan = plan_jobs(0, 8, Sample(on_battery=False, free_memory=32 * GB, free_disk=100 * GB, temperature=55.0))
    assert plan.jobs == 8 and plan.events == () and plan.notes == ()
    assert plan_jobs(3, 8, Sample()).jobs == 3                                                       # an explicit -j is respected; unknown readings change nothing


def test_low_memory_lowers_the_jobs_and_says_so():
    plan = plan_jobs(8, 8, Sample(free_memory=int(2.2 * MEMORY_PER_JOB)))
    assert plan.jobs == 2 and plan.events == (("resource.low_memory", {"free_bytes": int(2.2 * MEMORY_PER_JOB)}),)
    assert "running 2 job(s) instead of 8" in plan.notes[0]
    assert plan_jobs(8, 8, Sample(free_memory=10)).jobs == 1                                        # never below one
    assert plan_jobs(2, 8, Sample(free_memory=2 * MEMORY_PER_JOB)).events == ()                     # enough for what was asked


def test_low_disk_is_reported_and_changes_nothing_else():
    plan = plan_jobs(4, 8, Sample(free_disk=LOW_DISK_BYTES - 1), build_dir="/proj/build")
    assert plan.jobs == 4 and plan.events == (("resource.low_disk", {"path": "/proj/build", "free_bytes": LOW_DISK_BYTES - 1}),)
    assert plan_jobs(4, 8, Sample(free_disk=LOW_DISK_BYTES)).events == ()


def test_eco_mode_on_battery_or_heat():
    battery = Sample(on_battery=True, free_memory=32 * GB)
    assert plan_jobs(0, 8, battery).jobs == 8                                                       # off by default: nothing changes silently
    on = plan_jobs(0, 8, battery, eco="auto")
    assert on.jobs == 4 and on.events == (("resource.on_battery", {"jobs": 4}),) and "on battery power" in on.notes[0]
    assert plan_jobs(0, 8, Sample(on_battery=False), eco="auto").jobs == 8                         # auto: only when needed
    hot = plan_jobs(0, 8, Sample(temperature=91.0), eco="auto")
    assert hot.jobs == 2 and "91 C" in hot.notes[0]
    assert plan_jobs(0, 8, Sample(temperature=60.0), eco="auto").jobs == 8
    forced = plan_jobs(0, 8, Sample(on_battery=False), eco="on")
    assert forced.jobs == 4 and "eco mode" in forced.notes[0]
    assert plan_jobs(0, 1, Sample(on_battery=True), eco="on").jobs == 1                             # one CPU stays one


def test_the_rules_combine_from_the_most_restrictive():
    plan = plan_jobs(0, 16, Sample(on_battery=True, free_memory=3 * MEMORY_PER_JOB, temperature=90.0), eco="auto")
    assert plan.jobs == 3                                                                           # memory allows 3; the heat rule (16 // 4 = 4) is looser
    assert any(kind == "resource.low_memory" for kind, _ in plan.events)


def test_eco_mode_from_flag_and_environment():
    assert resources.eco_mode(False, {}) == "off" and resources.eco_mode(True, {}) == "on"
    assert resources.eco_mode(False, {"CHARPENTE_ECO": "auto"}) == "auto"
    assert resources.eco_mode(False, {"CHARPENTE_ECO": "ON"}) == "on" and resources.eco_mode(False, {"CHARPENTE_ECO": "1"}) == "on"
    assert resources.eco_mode(False, {"CHARPENTE_ECO": "whatever"}) == "off"


def test_sampling_this_machine_never_raises_and_finds_the_disk(tmp_path):
    reading = resources.sample(tmp_path / "does" / "not" / "exist" / "yet")                        # the folder does not exist: its drive is measured
    assert reading.free_disk is not None and reading.free_disk > 0
    if sys.platform in ("win32",) or sys.platform.startswith("linux"):
        assert reading.free_memory is None or reading.free_memory > 0
    assert reading.on_battery in (None, True, False)


# ---------------------------------------------------------------------- in a real build
def make(base: Path, count: int = 3) -> Path:
    (base / "src").mkdir(parents=True)
    lines = ['from charpente import *', '', 'with Workspace("res") as ws:', '    with Target("app") as app:', '        app.kind(Kind.EXECUTABLE)', '        app.standard("c++17")',
             '        app.sources(["src/*.cpp"])']
    (base / "res.charpente").write_bytes("\n".join(lines).encode() + b"\n")
    for i in range(count):
        body = f"int value{i}() {{ return {i}; }}\n"
        if i == 0:
            body += '#include <cstdio>\nint main() { std::printf("ok\\n"); return 0; }\n'
        (base / "src" / f"f{i}.cpp").write_bytes(body.encode())
    return base


def events_of(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_a_low_memory_machine_gets_fewer_jobs_and_an_event(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(make(tmp_path / "p"))
    monkeypatch.setattr(resources, "sample", lambda build_dir: Sample(free_memory=MEMORY_PER_JOB + 1, free_disk=50 * GB))
    assert main(["build", "-j", "8", "--output", "jsonl"]) == 0
    events = events_of(capsys)
    assert any(e["type"] == "resource.low_memory" for e in events)
    assert any(e["type"] == "hint.emitted" and e["payload"]["code"] == "resource" and "instead of 8" in e["payload"]["message"] for e in events)


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_eco_and_low_disk_reach_the_user(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(make(tmp_path / "p"))
    monkeypatch.setattr(resources, "sample", lambda build_dir: Sample(on_battery=True, free_memory=64 * GB, free_disk=LOW_DISK_BYTES // 2))
    monkeypatch.setenv("CHARPENTE_ECO", "auto")
    assert main(["build", "-j", "8"]) == 0
    captured = capsys.readouterr()
    assert "low disk space" in captured.err and "on battery power" in captured.out


def kill_tree(process: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=30)


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_an_interrupted_build_resumes_without_redoing_finished_work(tmp_path, capsys):
    """A power cut, simulated: kill the whole build mid-way, run it again, and check the finished actions were not compiled twice."""
    project = make(tmp_path / "p", count=14)
    for i in range(14):                                                                              # make each compile take long enough to interrupt reliably
        with open(project / "src" / f"f{i}.cpp", "ab") as handle:
            handle.write(("#include <map>\n#include <string>\n#include <vector>\n#include <algorithm>\n#include <iostream>\n#include <sstream>\n"
                          f"static std::map<std::string, std::vector<int>> table{i}() {{ std::map<std::string, std::vector<int>> m; for (int k = 0; k < {i + 3}; ++k) "
                          "m[std::to_string(k)].push_back(k); return m; }\n").encode())
    env = dict(os.environ, CHARPENTE_TRUST_ALL="1", CHARPENTE_CACHE_DIR=str(tmp_path / "cache"))
    first = subprocess.Popen([sys.executable, "-m", "charpente", "build", "-j", "1", "--output", "jsonl"], cwd=project, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             **({"start_new_session": True} if sys.platform != "win32" else {}))
    objects = project / "build" / "Debug" / "app" / "obj" / "src"
    end = time.time() + 120
    while time.time() < end and (not objects.exists() or (len(list(objects.glob("*.o"))) + len(list(objects.glob("*.obj")))) < 4):
        time.sleep(0.02)
    finished_before_kill = (len(list(objects.glob("*.o"))) + len(list(objects.glob("*.obj")))) if objects.exists() else 0
    kill_tree(first)
    assert 4 <= finished_before_kill < 14 and first.returncode != 0                                      # it really was cut short
    again = subprocess.run([sys.executable, "-m", "charpente", "build", "-j", "1", "--output", "jsonl"], cwd=project, env=env, capture_output=True, text=True, timeout=600)
    assert again.returncode == 0, again.stdout[-800:] + again.stderr[-800:]
    events = [json.loads(line) for line in again.stdout.splitlines() if line.startswith("{")]
    executed = [e for e in events if e["type"] == "action.finished" and e["payload"]["kind"] == "compile"]
    saved = [e for e in events if e["type"] in ("action.cache_hit", "action.up_to_date") and e["payload"]["kind"] == "compile"]
    assert len(saved) >= 3 and len(executed) <= 14 - 3                                                    # what finished before the cut was not compiled again
    assert len(executed) + len(saved) == 14
    exe = next((project / "build" / "Debug" / "app").glob("app*"))
    assert subprocess.run([str(exe)], capture_output=True, text=True).stdout.strip() == "ok"
