"""HarmonyOS packaging by delegation to hvigor, hdc deployment and the Node-API skeleton (recording runner, fake projects)."""
import argparse
import subprocess
from pathlib import Path

import pytest

from charpente import harmony
from charpente.dsl.model import Kind, Target, Workspace
from charpente.errors import ChError


class Rec:
    def __init__(self, output="", code=0, on_call=None):
        self.calls, self.output, self.code, self.on_call = [], output, code, on_call

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw.get("cwd")))
        if self.on_call:
            self.on_call(argv, kw)
        return subprocess.CompletedProcess(argv, self.code, stdout=self.output, stderr="")


def make_project(root: Path, name="harmony"):
    project = root / name
    (project / "entry").mkdir(parents=True)
    (project / "build-profile.json5").write_text("{}")
    return project


def test_settings_defaults_and_validation():
    s = harmony.settings_from("entry", {})
    assert (s.project, s.module, s.package_type, s.mode) == ("harmony", "entry", "hap", "debug")
    for raw, fragment in (({"colour": 1}, "unknown"), ({"package_type": "zip"}, "package_type"),
                          ({"bundle_name": "nodots"}, "bundle name"), ({"mode": "fast"}, "mode"),
                          ({"project": "../evil"}, "plain relative"), ({"module": "/abs"}, "plain relative"),
                          ({"product": "a b"}, "plain relative")):
        with pytest.raises(ChError) as exc:
            harmony.settings_from("entry", raw)
        assert exc.value.code == "CH8006" and fragment in str(exc.value)


def test_libraries_are_placed_where_hvigor_looks_for_them(tmp_path):
    project = make_project(tmp_path)
    lib64, lib32 = tmp_path / "arm64" / "libentry.so", tmp_path / "arm" / "libentry.so"
    for lib in (lib64, lib32):
        lib.parent.mkdir()
        lib.write_bytes(lib.parent.name.encode())
    placed = harmony.place_libraries(tmp_path, harmony.settings_from("entry", {}),
                                     {"harmonyos-arm64": lib64, "harmonyos-arm": lib32})
    assert sorted(p.relative_to(project).as_posix() for p in placed) == [
        "entry/libs/arm64-v8a/libentry.so", "entry/libs/armeabi-v7a/libentry.so"]
    assert (project / "entry" / "libs" / "arm64-v8a" / "libentry.so").read_bytes() == b"arm64"


def test_a_folder_that_is_not_a_hvigor_project_is_refused_with_advice(tmp_path):
    (tmp_path / "harmony").mkdir()
    with pytest.raises(ChError) as exc:
        harmony.place_libraries(tmp_path, harmony.settings_from("entry", {}), {})
    assert "not a hvigor project" in str(exc.value) and "DevEco" in str(exc.value)


def test_hvigor_command_line_per_package_type():
    argv = harmony.hvigor_argv(harmony.settings_from("entry", {"mode": "release"}), "hvigorw")
    assert argv[0] == "hvigorw" and argv[-2:] == ["assembleHap", "--no-daemon"] and "buildMode=release" in argv
    assert harmony.hvigor_argv(harmony.settings_from("e", {"package_type": "har"}), "h")[-2] == "assembleHar"
    assert harmony.hvigor_argv(harmony.settings_from("e", {"package_type": "hsp"}), "h")[-2] == "assembleHsp"
    assert all(isinstance(a, str) for a in argv)


def test_hvigorw_is_the_projects_own_wrapper_first(tmp_path):
    project = make_project(tmp_path)
    (project / "hvigorw.bat").write_text("")
    assert harmony.find_hvigorw(project, which=lambda n: "/x/hvigorw").endswith("hvigorw.bat")
    assert harmony.find_hvigorw(tmp_path / "harmony2", which=lambda n: "/x/hvigorw") == "/x/hvigorw"
    with pytest.raises(ChError) as exc:
        harmony.find_hvigorw(tmp_path / "harmony2", which=lambda n: None)
    assert exc.value.code == "CH8007" and "Huawei" in str(exc.value)


def test_build_package_places_libraries_runs_hvigor_and_reports_the_hap(tmp_path):
    project = make_project(tmp_path)
    (project / "hvigorw").write_text("")
    lib = tmp_path / "libentry.so"
    lib.write_bytes(b"elf")

    def hvigor_writes_a_hap(argv, kw):
        out = project / "entry" / "build" / "default" / "outputs" / "default"
        out.mkdir(parents=True, exist_ok=True)
        (out / "entry-default-unsigned.hap").write_bytes(b"hap")

    rec = Rec(on_call=hvigor_writes_a_hap)
    said = []
    outputs = harmony.build_package(tmp_path, harmony.settings_from("entry", {}), {"harmonyos-arm64": lib}, runner=rec,
                                    say=said.append)
    assert [p.name for p in outputs] == ["entry-default-unsigned.hap"]
    assert rec.calls[0][1] == str(project) and said == ["Running hvigor (hap)"]
    assert (project / "entry" / "libs" / "arm64-v8a" / "libentry.so").is_file()


def test_hvigor_failure_and_silent_success_are_both_reported(tmp_path):
    project = make_project(tmp_path)
    (project / "hvigorw").write_text("")
    lib = tmp_path / "libentry.so"
    lib.write_bytes(b"x")
    with pytest.raises(ChError) as exc:
        harmony.build_package(tmp_path, harmony.settings_from("entry", {}), {"harmonyos-arm64": lib},
                              runner=Rec(output="ERROR: signing config missing", code=1))
    assert exc.value.code == "CH8008" and "signing config missing" in str(exc.value)
    with pytest.raises(ChError) as exc:
        harmony.build_package(tmp_path, harmony.settings_from("entry", {}), {"harmonyos-arm64": lib}, runner=Rec())
    assert "left no .hap" in str(exc.value)


def test_hdc_discovery_parsing_and_deployment(tmp_path):
    sdk = tmp_path / "sdk"
    (sdk / "12" / "toolchains").mkdir(parents=True)
    (sdk / "12" / "toolchains" / "hdc.exe").write_text("")
    assert harmony.hdc_path(sdk, which=lambda n: None).endswith("hdc.exe")
    with pytest.raises(ChError) as exc:
        harmony.hdc_path(None, which=lambda n: None)
    assert exc.value.code == "CH8007"
    assert harmony.parse_targets("127.0.0.1:5555\nABCDEF\n") == ["127.0.0.1:5555", "ABCDEF"]
    assert harmony.parse_targets("[Empty]\n") == []
    rec = Rec(output="install bundle successfully")
    harmony.install_and_launch("hdc", tmp_path / "a.hap", "com.example.app", serial="S1", runner=rec)
    assert rec.calls[0][0] == ["hdc", "-t", "S1", "install", "-r", str(tmp_path / "a.hap")]
    assert rec.calls[1][0] == ["hdc", "-t", "S1", "shell", "aa", "start", "-a", "EntryAbility", "-b", "com.example.app"]
    with pytest.raises(ChError):
        harmony.install_and_launch("hdc", tmp_path / "a.hap", "com.example.app", runner=Rec(output="install failed"))
    with pytest.raises(ChError) as exc:
        harmony.install_and_launch("hdc", tmp_path / "a.hap", "", runner=Rec(output="ok"))
    assert "bundle_name" in str(exc.value)
    assert harmony.hilog_argv("hdc", "S1") == ["hdc", "-t", "S1", "shell", "hilog"]


def test_napi_skeleton_files_are_consistent():
    files = harmony.napi_files("entry", ["add", "multiply"])
    assert sorted(files) == ["src/entry_napi.cpp", "types/libentry/Index.d.ts", "types/libentry/oh-package.json5"]
    cpp = files["src/entry_napi.cpp"]
    assert '#include "napi/native_api.h"' in cpp and '.nm_modname = "entry"' in cpp
    assert '{"add", nullptr, add,' in cpp and '{"multiply", nullptr, multiply,' in cpp
    assert files["types/libentry/Index.d.ts"].splitlines() == [
        "export const add: (a: number, b: number) => number;", "export const multiply: (a: number, b: number) => number;"]
    assert '"name": "libentry.so"' in files["types/libentry/oh-package.json5"]
    for bad in ("Entry", "1x", "a b"):
        with pytest.raises(ChError):
            harmony.napi_files(bad)
    with pytest.raises(ChError):
        harmony.napi_files("entry", ["not valid"])


def test_only_a_mobile_app_becomes_a_harmony_package(tmp_path):
    from charpente.commands import _harmony

    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="tool", kind=Kind.EXECUTABLE, location=tmp_path))
    with pytest.raises(ChError) as exc:
        _harmony.build_package(argparse.Namespace(platform=None), ws, ws.targets["tool"])
    assert "MOBILE_APP" in str(exc.value)
    assert _harmony._platforms(argparse.Namespace(platform="harmonyos-arm64,harmonyos-x64")) == [
        "harmonyos-arm64", "harmonyos-x64"]
    with pytest.raises(ChError):
        _harmony._platforms(argparse.Namespace(platform="android-arm64"))
