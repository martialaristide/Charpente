"""Deploying to several devices at once and merging their logs. A small real `adb` stand-in (a compiled program) plays the devices; the APK is a real one."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from charpente import android, multideploy
from charpente.cli import main
from charpente.core.process import ProcessResult
from charpente.errors import ChError
from charpente.multideploy import Device, LogMerger, Outcome

HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++"))
HAVE_NDK = android.find_sdk() is not None and android.find_sdk().ndk is not None if hasattr(android.find_sdk() or object(), "ndk") else android.find_sdk() is not None


# ---------------------------------------------------------------------- pure
def test_abi_lists_and_platforms():
    assert multideploy.parse_abilist("arm64-v8a,armeabi-v7a\n") == ["arm64-v8a", "armeabi-v7a"] and multideploy.parse_abilist("") == []
    assert multideploy.platform_for(["arm64-v8a", "armeabi-v7a"]) == "android-arm64"
    assert multideploy.platform_for(["x86_64", "x86"]) == "android-x64"
    assert multideploy.platform_for(["x86"]) is None and multideploy.platform_for([]) is None
    assert multideploy.platform_for(["mips", "armeabi-v7a"]) == "android-arm"                          # the first one we can build, not merely the first


def test_platforms_needed_are_deduplicated_in_a_stable_order():
    devices = [Device("a", platform="android-x64"), Device("b", platform="android-arm64"), Device("c", platform="android-x64"), Device("d")]
    assert multideploy.platforms_needed(devices) == ["android-arm64", "android-x64"]
    supported, skipped = multideploy.split_supported(devices)
    assert [d.serial for d in supported] == ["a", "b", "c"] and [d.serial for d in skipped] == ["d"]


def test_discovery_reads_ready_devices_only():
    def run(argv, **kw):
        if argv[1:] == ["devices"]:
            return ProcessResult(tuple(argv), 0, "List of devices attached\nA\tdevice\nB\toffline\nC\tunauthorized\nD\tdevice\n")
        serial = argv[2]
        return ProcessResult(tuple(argv), 0 if serial == "A" else 1, "arm64-v8a,armeabi-v7a\n" if serial == "A" else "")

    devices = multideploy.discover("adb", run)
    assert [(d.serial, d.abis, d.platform) for d in devices] == [("A", ["arm64-v8a", "armeabi-v7a"], "android-arm64"), ("D", [], None)]


def test_one_failing_device_never_stops_the_others():
    done = []

    def install(device):
        if device.serial == "bad":
            raise ChError("CH8008", step="adb install", detail="INSTALL_FAILED")
        if device.serial == "buggy":
            raise RuntimeError("boom")
        done.append(device.serial)

    outcomes = multideploy.deploy_all([Device("a"), Device("bad"), Device("b"), Device("buggy")], install)
    assert [(o.serial, o.ok) for o in outcomes] == [("a", True), ("bad", False), ("b", True), ("buggy", False)]      # results keep the order given
    assert sorted(done) == ["a", "b"] and "CH8008" in outcomes[1].detail and "RuntimeError: boom" in outcomes[3].detail
    assert multideploy.deploy_all([], install) == []


def test_installs_really_run_in_parallel():
    barrier = threading.Barrier(3, timeout=20)
    multideploy.deploy_all([Device("a"), Device("b"), Device("c")], lambda d: barrier.wait())           # would time out (BrokenBarrierError) if run one after another
    assert barrier.n_waiting == 0


def test_summary():
    summary = multideploy.summarize([Outcome("a", True), Outcome("b", False, "no space")], [Device("c", ["mips"])])
    assert summary["ok"] == ["a"] and summary["failed"] == ["b: no space"] and "runs mips" in summary["skipped"][0]


class FakeStream:
    """Stands in for `process.LineStream`: emits given lines from its own thread, then exits."""

    def __init__(self, argv, on_line, on_exit, lines=()):
        self.argv = argv
        self.stopped = False
        self.thread = threading.Thread(target=self.run, args=(on_line, on_exit, list(lines)), daemon=True)
        self.thread.start()

    def run(self, on_line, on_exit, lines):
        for line in lines:
            if self.stopped:
                break
            on_line(line)
            time.sleep(0.005)
        on_exit(0)

    def stop(self):
        self.stopped = True


def test_merged_logs_are_tagged_kept_in_order_per_device_and_never_torn():
    seen = []
    streams = {}

    def start(argv, on_line, on_exit):
        serial = argv[2]
        streams[serial] = FakeStream(argv, on_line, on_exit, [f"{serial} line {i}" for i in range(50)])
        return streams[serial]

    merger = LogMerger("adb", [Device("A"), Device("B")], lambda serial, line: seen.append((serial, line)), start=start)
    assert merger.wait(20) is True                                                                     # both ended by themselves
    for serial in ("A", "B"):
        assert [line for s, line in seen if s == serial] == [f"{serial} line {i}" for i in range(50)]
    assert {s for s, _ in seen} == {"A", "B"} and len(seen) == 100
    assert streams["A"].argv == ["adb", "-s", "A", "logcat", "-v", "time"]


def test_the_log_filter_and_stopping():
    seen = []
    merger = LogMerger("adb", [Device("A")], lambda s, line: seen.append(line), flt="ERR",
                       start=lambda argv, on_line, on_exit: FakeStream(argv, on_line, on_exit, ["fine", "an ERROR here", "fine again", "err lower"]))
    merger.wait(20)
    assert seen == ["an ERROR here", "err lower"]                                                        # the filter ignores case
    slow = LogMerger("adb", [Device("A")], lambda s, line: None, start=lambda argv, on_line, on_exit: FakeStream(argv, on_line, on_exit, ["x"] * 100000))
    assert slow.wait(0.05) is False
    slow.stop()
    assert slow.wait(1) is True
    assert LogMerger("adb", [], lambda s, line: None).wait(1) is True


def test_tags_align():
    assert multideploy.tag("A", 6) == "[A]   " and multideploy.tag("emulator-5554") == "[emulator-5554]"


# ---------------------------------------------------------------------- with a real adb stand-in and a real APK
FAKE_ADB = r'''
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <random>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

static std::string env(const char* name) { const char* v = std::getenv(name); return v ? v : ""; }
static void note(const std::string& text) {
    std::string path = env("FAKE_ADB_LOG");
    if (path.empty()) return;
    // One small file per event (several fake devices run at once, and concurrent appends to one file are not safe on every OS).
    std::random_device entropy;
    std::string unique = std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) + "-" + std::to_string(entropy());
    std::ofstream(path + "." + unique + ".note") << text << std::endl;
}
static std::vector<std::string> split(const std::string& s, char sep) {
    std::vector<std::string> out; std::stringstream in(s); std::string part;
    while (std::getline(in, part, sep)) out.push_back(part);
    return out;
}
// FAKE_ADB_DEVICES = "serial=abi1,abi2;serial2=abi"
static std::string abis_of(const std::string& serial) {
    for (const auto& entry : split(env("FAKE_ADB_DEVICES"), ';')) {
        auto kv = split(entry, '=');
        if (kv.size() == 2 && kv[0] == serial) return kv[1];
    }
    return "";
}
int main(int argc, char** argv) {
    std::vector<std::string> a(argv + 1, argv + argc);
    std::string serial;
    size_t i = 0;
    if (a.size() > 1 && a[0] == "-s") { serial = a[1]; i = 2; }
    if (i >= a.size()) return 1;
    const std::string& cmd = a[i];
    if (cmd == "devices") {
        std::printf("List of devices attached\n");
        for (const auto& entry : split(env("FAKE_ADB_DEVICES"), ';')) std::printf("%s\tdevice\n", split(entry, '=')[0].c_str());
        return 0;
    }
    if (cmd == "shell" && a.size() > i + 2 && a[i + 1] == "getprop") { std::printf("%s\n", abis_of(serial).c_str()); return 0; }
    if (cmd == "install") {
        note("install " + serial + " " + a.back());
        for (const auto& bad : split(env("FAKE_ADB_FAIL"), ',')) if (bad == serial) { std::printf("Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]\n"); return 1; }
        std::printf("Success\n");
        return 0;
    }
    if (cmd == "shell" && a.size() > i + 1 && a[i + 1] == "monkey") { note("launch " + serial); std::printf("Events injected: 1\n"); return 0; }
    if (cmd == "logcat") {
        int lines = std::atoi(env("FAKE_ADB_LOG_LINES").c_str());
        for (int n = 1; n <= (lines ? lines : 5); ++n) {
            std::printf("01-01 00:00:%02d.000 I/App( 1): message %d from %s\n", n, n, serial.c_str());
            std::fflush(stdout);
            std::this_thread::sleep_for(std::chrono::milliseconds(30));
        }
        return 0;
    }
    return 1;
}
'''


@pytest.fixture(scope="module")
def fake_adb(tmp_path_factory):
    if not HAVE_COMPILER:
        pytest.skip("needs a C++ compiler")
    folder = tmp_path_factory.mktemp("fakeadb")
    (folder / "adb.cpp").write_text(FAKE_ADB, encoding="utf-8")
    exe = folder / ("adb.exe" if sys.platform == "win32" else "adb")
    compiler = shutil.which("g++") or shutil.which("clang++")
    built = subprocess.run([compiler, "-std=c++17", str(folder / "adb.cpp"), "-o", str(exe), "-static"] if sys.platform == "win32" else [compiler, "-std=c++17", str(folder / "adb.cpp"), "-o", str(exe)],
                           capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    return folder


@pytest.fixture
def android_project(tmp_path, monkeypatch):
    if not HAVE_NDK:
        pytest.skip("needs the Android SDK and NDK")
    env = dict(os.environ, CHARPENTE_TRUST_ALL="1")
    subprocess.run([sys.executable, "-m", "charpente", "init", "phone", "--template", "app-android", "--install", "--dir", str(tmp_path / "phone")], check=True, capture_output=True, env=env, cwd=tmp_path)
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(tmp_path / "phone")
    return tmp_path / "phone"


def use_fake(monkeypatch, fake_adb, log, devices, **extra):
    monkeypatch.setenv("PATH", str(fake_adb) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_ADB_DEVICES", devices)
    monkeypatch.setenv("FAKE_ADB_LOG", str(log))
    for key, value in extra.items():
        monkeypatch.setenv(key, value)


def read_log(path):
    """Every event the fake adb noted (one file each), oldest first."""
    files = sorted(path.parent.glob(path.name + ".*.note"), key=lambda p: (p.stat().st_mtime_ns, p.name))
    return [line for f in files for line in f.read_text(encoding="utf-8").splitlines()]


def test_deploy_all_builds_one_apk_for_every_device_abi_and_installs_everywhere(android_project, fake_adb, monkeypatch, tmp_path, capsys):
    log = tmp_path / "adb.log"
    use_fake(monkeypatch, fake_adb, log, "phone-1=arm64-v8a,armeabi-v7a;emulator-5554=x86_64,x86;old-tablet=mips")
    code = main(["deploy", "--device", "all", "--config", "Debug"])
    captured = capsys.readouterr()
    out = captured.out
    assert code == 0, out + captured.err
    assert "found phone-1: arm64-v8a, armeabi-v7a" in out and "found old-tablet: mips  (not supported: skipped)" in out
    assert "Deployed" in out and "Skipped old-tablet: runs mips" in out
    installs = [line.split() for line in read_log(log) if line.startswith("install")]
    assert sorted(i[1] for i in installs) == ["emulator-5554", "phone-1"] and len({i[2] for i in installs}) == 1        # the same APK everywhere
    apk = Path(installs[0][2])
    with zipfile.ZipFile(apk) as archive:
        libs = sorted(n.split("/")[1] for n in archive.namelist() if n.startswith("lib/") and n.endswith(".so"))
    assert libs == ["arm64-v8a", "x86_64"]                                                                             # exactly the ABIs the devices need
    assert sorted(line.split()[1] for line in read_log(log) if line.startswith("launch")) == ["emulator-5554", "phone-1"]


def test_a_failing_device_is_reported_and_the_others_still_get_the_app(android_project, fake_adb, monkeypatch, tmp_path, capsys):
    log = tmp_path / "adb.log"
    use_fake(monkeypatch, fake_adb, log, "good=arm64-v8a;full=arm64-v8a", FAKE_ADB_FAIL="full")
    assert main(["deploy", "--device", "all", "--no-launch"]) == 1
    out = capsys.readouterr().out
    assert "FAILED full:" in out and "INSTALL_FAILED_INSUFFICIENT_STORAGE" in out and "Deployed" in out and "to good." in out
    assert {line.split()[1] for line in read_log(log) if line.startswith("install")} == {"good", "full"}
    assert not [line for line in read_log(log) if line.startswith("launch")]                                            # --no-launch


def test_logs_from_all_devices_come_back_merged_and_tagged(android_project, fake_adb, monkeypatch, tmp_path, capsys):
    use_fake(monkeypatch, fake_adb, tmp_path / "adb.log", "alpha=arm64-v8a;beta=arm64-v8a", FAKE_ADB_LOG_LINES="6")
    assert main(["deploy", "--device", "all", "--no-launch", "--logs", "--log-seconds", "30"]) == 0
    out = capsys.readouterr().out
    assert "Following the logs of 2 device(s)" in out
    lines = [line for line in out.splitlines() if "message" in line]
    assert len(lines) == 12
    for serial in ("alpha", "beta"):
        own = [line for line in lines if line.startswith(f"[{serial}]")]
        assert [line.split("message ")[1].split()[0] for line in own] == ["1", "2", "3", "4", "5", "6"]                     # in order, per device
        assert all(line.rstrip().endswith(f"from {serial}") for line in own)


def test_deploy_events_are_machine_readable(android_project, fake_adb, monkeypatch, tmp_path, capsys):
    use_fake(monkeypatch, fake_adb, tmp_path / "adb.log", "one=arm64-v8a", FAKE_ADB_LOG_LINES="2")
    assert main(["deploy", "--device", "all", "--logs", "--log-seconds", "30", "--output", "jsonl"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    kinds = [e["type"] for e in events if e["type"].startswith("deploy.")]
    assert kinds.count("deploy.device_found") == 1 and "deploy.installing" in kinds and "deploy.launched" in kinds and kinds.count("deploy.log") == 2
    logged = [e["payload"] for e in events if e["type"] == "deploy.log"]
    assert all(p["device"] == "one" and "message" in p["line"] for p in logged)


def test_no_supported_device_is_a_coded_error(android_project, fake_adb, monkeypatch, tmp_path, capsys):
    use_fake(monkeypatch, fake_adb, tmp_path / "adb.log", "only-x86=x86")
    assert main(["deploy", "--device", "all"]) != 0
    assert "CH8009" in capsys.readouterr().err
