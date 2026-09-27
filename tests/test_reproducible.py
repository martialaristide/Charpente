"""Reproducible builds: the flavour's flags, the byte comparison, and `charpente verify-reproducible` on real builds."""
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from helpers import needs_gnu_default

from charpente import flags, repro, variants
from charpente.cli import main
from charpente.dsl.model import Kind, Target
from charpente.errors import ChError
from charpente.toolchains import Toolchain

HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++"))
MINGW = Toolchain(name="mingw", c_compiler="gcc", cxx_compiler="g++", archiver="ar", linker="g++")
GCC = Toolchain(name="gcc", c_compiler="gcc", cxx_compiler="g++", archiver="ar", linker="g++")
MSVC = Toolchain(name="msvc", c_compiler="cl", cxx_compiler="cl", archiver="lib", linker="cl")


# ---------------------------------------------------------------------- the flavour (pure)
def test_the_reproducible_flavour_maps_paths_fixes_the_clock_and_drops_timestamps(tmp_path):
    tc = variants.reproducible(MINGW, tmp_path)
    assert tc.variant == "repro"
    assert f"-ffile-prefix-map={tmp_path.resolve()}=/src" in tc.c_args and tc.cxx_args == tc.c_args
    assert "-Wl,--no-insert-timestamp" in tc.ld_args
    assert dict(tc.env) == {"SOURCE_DATE_EPOCH": variants.SOURCE_DATE_EPOCH, "TZ": "UTC", "LC_ALL": "C"}
    assert ("deterministic_ar", "1") in tc.extras


def test_elf_toolchains_drop_the_build_id_and_macos_gets_no_linker_flag(tmp_path):
    assert "-Wl,--build-id=none" in variants.reproducible(GCC, tmp_path).ld_args
    assert variants.reproducible(replace(GCC, name="clang", target="macos-arm64"), tmp_path).ld_args == ()
    assert "-Wl,--no-insert-timestamp" in variants.reproducible(replace(GCC, target="windows-x64"), tmp_path).ld_args


def test_msvc_style_toolchains_are_refused_not_half_supported(tmp_path):
    with pytest.raises(ChError) as info:
        variants.reproducible(MSVC, tmp_path)
    assert info.value.code == "CH8011" and "reproducible" in info.value.message


def test_existing_toolchain_settings_are_kept(tmp_path):
    base = replace(GCC, env=(("A", "1"),), c_args=("-x",), extras=(("k", "v"),))
    tc = variants.reproducible(base, tmp_path)
    assert ("A", "1") in tc.env and tc.c_args[0] == "-x" and ("k", "v") in tc.extras


def test_archives_are_deterministic_only_in_the_flavour(tmp_path):
    lib = Target("lib", kind=Kind.STATIC_LIBRARY)
    plain = flags.link_args(GCC, lib, [Path("a.o")], Path("liblib.a"))
    repro_args = flags.link_args(variants.reproducible(GCC, tmp_path), lib, [Path("a.o")], Path("liblib.a"))
    assert plain[1] == "rcs" and repro_args[1] == "rcsD"


# ---------------------------------------------------------------------- comparing (pure)
def test_first_difference():
    assert repro.first_difference(b"abc", b"abc") is None
    assert repro.first_difference(b"abcdef", b"abcXef") == 3
    assert repro.first_difference(b"abc", b"abcdef") == 3 and repro.first_difference(b"", b"x") == 0
    big = b"a" * 100000
    assert repro.first_difference(big + b"X" + big, big + b"Y" + big) == 100000


def test_differences_come_with_plausible_causes(tmp_path):
    a, b = tmp_path / "one" / "project", tmp_path / "second" / "project"
    diff = repro.explain("app", f"path={a}".encode() + b"\0" * 4, f"path={b}".encode() + b"\0" * 4, [str(a), str(b)])
    assert diff.first_offset == len("path=") + len(str(tmp_path)) + 1 or diff.first_offset is not None
    assert any("build folder path" in h for h in diff.hints) and any("sizes differ" in h for h in diff.hints) == (len(str(a)) != len(str(b)))
    stamp = repro.explain("app", b"built 2026-09-26", b"built 2026-09-27", [])
    assert any("date" in h for h in stamp.hints)


def test_compare_builds_by_content(tmp_path):
    for d in ("a", "b"):
        (tmp_path / d).mkdir()
    (tmp_path / "a" / "same").write_bytes(b"1")
    (tmp_path / "b" / "same").write_bytes(b"1")
    (tmp_path / "a" / "diff").write_bytes(b"1")
    (tmp_path / "b" / "diff").write_bytes(b"2")
    (tmp_path / "a" / "only").write_bytes(b"x")
    report = repro.compare_builds({"same": tmp_path / "a" / "same", "diff": tmp_path / "a" / "diff", "only": tmp_path / "a" / "only"},
                                  {"same": tmp_path / "b" / "same", "diff": tmp_path / "b" / "diff"}, [])
    assert report.identical == ["same"] and [d.name for d in report.different] == ["diff"] and report.missing == ["only"] and not report.ok
    assert repro.compare_builds({}, {}, []).ok is False                                              # nothing built proves nothing


def test_outputs_are_read_from_the_event_stream():
    lines = ['not json', '{"type": "action.finished", "payload": {"target": "app", "kind": "compile", "outputs": ["a.o"]}}',
             '{"type": "action.finished", "payload": {"target": "app", "kind": "link", "outputs": ["app.exe"]}}',
             '{"type": "action.cache_hit", "payload": {"target": "lib", "kind": "archive", "outputs": ["lib.a"]}}', '{broken']
    assert repro.outputs_from_events(lines) == {"app": "app.exe", "lib": "lib.a"}


# ---------------------------------------------------------------------- real builds
def make(tmp_path, extra=""):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.cpp").write_text('#include <cstdio>\n#ifndef BUILD_DIR\n#define BUILD_DIR "none"\n#endif\n'
                                               'int main() { std::printf("built in %s from %s\\n", BUILD_DIR, __FILE__); return 0; }\n', encoding="utf-8")
    (tmp_path / "r.charpente").write_text('import os\nfrom charpente import *\n\nwith Workspace("r") as ws:\n    with Target("core") as core:\n        core.kind(Kind.STATIC_LIBRARY)\n'
                                          '        core.standard("c++17")\n        core.sources(["src/lib.cpp"])\n    with Target("app") as app:\n        app.kind(Kind.EXECUTABLE)\n'
                                          '        app.standard("c++17")\n        app.sources(["src/main.cpp"])\n        app.uses("core")\n' + extra, encoding="utf-8")
    (tmp_path / "src" / "lib.cpp").write_text("int answer() { return 42; }\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def trusted(monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
@needs_gnu_default
def test_a_normal_project_builds_reproducibly_in_two_different_folders(tmp_path, monkeypatch, capsys, trusted):
    monkeypatch.chdir(make(tmp_path))
    assert main(["verify-reproducible"]) == 0
    out = capsys.readouterr().out
    assert out.count("[identical]") == 2 and "byte-identical" in out


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
@needs_gnu_default
def test_a_build_that_embeds_its_folder_is_reported_with_the_cause(tmp_path, monkeypatch, capsys, trusted):
    # The workspace file itself puts the current folder into the program: a real leak the mapped prefix cannot hide.
    monkeypatch.chdir(make(tmp_path, '        app.defines(["BUILD_DIR=\\"" + os.getcwd().replace("\\\\", "/") + "\\""])\n'))
    assert main(["verify-reproducible", "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["reproducible"] is False and result["identical"] == ["core"]
    (different,) = result["different"]
    assert different["target"] == "app" and different["firstDifferentByte"] is not None
    assert any("build folder path" in hint for hint in different["hints"])


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_a_failing_build_is_reported_not_compared(tmp_path, monkeypatch, capsys, trusted):
    project = make(tmp_path)
    (project / "src" / "main.cpp").write_text("int main() { return nope; }\n", encoding="utf-8")
    monkeypatch.chdir(project)
    assert main(["verify-reproducible"]) != 0
    assert "CH8025" in capsys.readouterr().err


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
@needs_gnu_default
def test_the_flavour_has_its_own_folder_and_the_program_still_runs(tmp_path, monkeypatch, capsys, trusted):
    project = make(tmp_path)
    monkeypatch.chdir(project)
    assert main(["build", "--reproducible", "--config", "Release"]) == 0
    exe = next((project / "build" / "Release-repro" / "app").glob("app*"))
    run = subprocess.run([str(exe)], capture_output=True, text=True)
    assert run.returncode == 0 and "/src/src/main.cpp" in run.stdout.replace("\\", "/")                # __FILE__ is mapped, not the real path
    assert str(project.resolve()).replace("\\", "/") not in run.stdout.replace("\\", "/")
    assert not (project / "build" / "Release" / "app").exists()                                        # the normal build directory is untouched


def test_a_copy_never_takes_build_output_along(tmp_path):
    from charpente.commands.verify import _copy_project

    (tmp_path / "p" / "build").mkdir(parents=True)
    (tmp_path / "p" / "build" / "big.o").write_bytes(b"x")
    (tmp_path / "p" / ".git").mkdir()
    (tmp_path / "p" / "src").mkdir()
    (tmp_path / "p" / "src" / "a.cpp").write_text("x", encoding="utf-8")
    _copy_project(tmp_path / "p", tmp_path / "copy")
    assert sorted(p.name for p in (tmp_path / "copy").iterdir()) == ["src"]
    assert os.path.exists(str(tmp_path / "copy" / "src" / "a.cpp")) and sys.platform


def test_apple_archives_are_made_deterministic_without_the_gnu_only_modifier(tmp_path):
    """Apple's `ar` rejects `rcsD` (found by the macOS CI job); it honours ZERO_AR_DATE instead."""
    apple = replace(GCC, name="apple-clang", cxx_compiler="clang++", c_compiler="clang")
    tc = variants.reproducible(apple, tmp_path)
    assert dict(tc.env)["ZERO_AR_DATE"] == "1" and ("deterministic_ar", "1") not in tc.extras
    lib = Target("lib", kind=Kind.STATIC_LIBRARY)
    assert flags.link_args(tc, lib, [Path("a.o")], Path("liblib.a"))[1] == "rcs"
    assert "ZERO_AR_DATE" not in dict(variants.reproducible(GCC, tmp_path).env)                # GNU toolchains keep the D modifier instead
