"""Cross-compilation plumbing: the platform table, toolchain selection and specialisation,
command lines, output names, running foreign programs and installing zig.

No compiler is needed here: everything is pure or uses a fake archive served from disk.
The real end-to-end verification (zig building ELF/PE/Mach-O/wasm binaries) is documented
in docs/plans/phase-4a.md and re-runnable with `charpente build --platform ...`.
"""
import hashlib
import io
import json
import os
import tarfile
import zipfile
from pathlib import Path

import pytest
from helpers import GCC

from charpente import cross, flags, platforms, runners, toolchain_install, toolchains
from charpente.core.planner import plan_workspace
from charpente.dsl.model import OS, Kind, Language, Target, Workspace
from charpente.errors import ChError
from charpente.toolchains import Toolchain

ZIG = Toolchain(name="zig", c_compiler="/z/zig", cxx_compiler="/z/zig", archiver="/z/zig", linker="/z/zig",
                c_args=("cc",), cxx_args=("c++",), ar_args=("ar",), ld_args=("c++",),
                targets=toolchains._ZIG_PLATFORMS)
LINUX_X64 = platforms.get("linux-x64")
WINDOWS_X64 = platforms.get("windows-x64")


# ------------------------------------------------------------------ platform table
def test_every_platform_has_a_tier_and_a_triple():
    for p in platforms.all_platforms():
        assert p.tier in (1, 2, 3), p.name
        assert p.triples, p.name
        assert p.name == p.name.lower()
        OS(p.os) if p.os != "visionos" else None      # every platform maps to a known OS


def test_platform_lookup_by_name_and_by_triple():
    assert platforms.get("linux-arm64").arch == "arm64"
    assert platforms.get("aarch64-linux-gnu").name == "linux-arm64"
    assert platforms.get("  Linux-ARM64 ").name == "linux-arm64"


def test_unknown_platform_lists_the_known_ones():
    with pytest.raises(ChError) as exc:
        platforms.get("plan9-mips")
    assert exc.value.code == "CH8001"
    assert "linux-x64" in str(exc.value)


def test_tier_three_warns_and_tier_one_does_not():
    assert platforms.warning_for(platforms.get("openbsd-x64"))
    assert platforms.warning_for(platforms.get("linux-x64")) is None


def test_triple_prefers_the_asked_abi():
    assert platforms.get("linux-x64").triple("musl") == "x86_64-linux-musl"
    assert platforms.get("linux-x64").triple() == "x86_64-linux-gnu"


# ------------------------------------------------------------------ specialise / select
def test_zig_specialisation_puts_the_target_after_the_driver():
    tc = cross.specialise(ZIG, platforms.get("linux-arm64"))
    assert tc.cxx_args == ("c++", "-target", "aarch64-linux-gnu")
    assert tc.c_args == ("cc", "-target", "aarch64-linux-gnu")
    assert tc.ar_args == ("ar",)
    assert tc.target == "linux-arm64"


def test_zig_windows_target_uses_the_gnu_abi():
    assert cross.specialise(ZIG, WINDOWS_X64).c_args[-1] == "x86_64-windows-gnu"


def test_a_toolchain_that_cannot_target_a_platform_refuses_with_a_hint():
    with pytest.raises(ChError) as exc:
        cross.specialise(GCC, LINUX_X64)
    assert exc.value.code == "CH8002"
    with pytest.raises(ChError) as exc:
        cross.specialise(ZIG, platforms.get("android-arm64"))
    assert "Android NDK" in str(exc.value)


def _select(platform, name=None, found=(GCC,), monkeypatch=None):
    return cross.select(platform, name, detect=lambda _os: list(found))


def test_no_platform_means_the_first_detected_toolchain_unchanged(monkeypatch):
    monkeypatch.setattr(cross, "host_os", lambda: OS.LINUX)
    target_os, tc = _select(None, found=(GCC, ZIG))
    assert (target_os, tc) == (OS.LINUX, GCC)
    assert tc.target == ""


def test_no_toolchain_at_all_is_ch2001(monkeypatch):
    monkeypatch.setattr(cross, "host_os", lambda: OS.LINUX)
    with pytest.raises(ChError) as exc:
        _select(None, found=())
    assert exc.value.code == "CH2001"


def test_asking_for_the_host_platform_stays_native(monkeypatch):
    monkeypatch.setattr(cross, "host_os", lambda: OS.LINUX)
    monkeypatch.setattr(platforms, "host", lambda: LINUX_X64)
    target_os, tc = _select("linux-x64", found=(GCC, ZIG))
    assert tc is GCC and tc.target == ""


def test_another_platform_picks_the_first_toolchain_that_can_target_it(monkeypatch):
    monkeypatch.setattr(cross, "host_os", lambda: OS.LINUX)
    monkeypatch.setattr(platforms, "host", lambda: LINUX_X64)
    target_os, tc = _select("windows-arm64", found=(GCC, ZIG))
    assert target_os == OS.WINDOWS
    assert tc.name == "zig" and tc.target == "windows-arm64"


def test_no_capable_toolchain_is_ch8002(monkeypatch):
    monkeypatch.setattr(cross, "host_os", lambda: OS.LINUX)
    monkeypatch.setattr(platforms, "host", lambda: LINUX_X64)
    with pytest.raises(ChError) as exc:
        _select("macos-arm64", found=(GCC,))
    assert exc.value.code == "CH8002"
    assert "toolchain install zig" in str(exc.value)


def test_named_toolchain_must_exist(monkeypatch):
    monkeypatch.setattr(cross, "host_os", lambda: OS.LINUX)
    with pytest.raises(ChError) as exc:
        _select(None, name="clang", found=(GCC,))
    assert exc.value.code == "CH8003"
    assert "gcc" in str(exc.value)
    assert _select(None, name="gcc", found=(GCC, ZIG))[1] is GCC


def test_variant_name_separates_platforms():
    assert cross.variant_name("Debug", GCC) == "Debug"
    assert cross.variant_name("Debug", cross.specialise(ZIG, LINUX_X64)) == "Debug-linux-x64"


# ------------------------------------------------------------------ command lines
def test_zig_compile_and_link_command_lines():
    tc = cross.specialise(ZIG, platforms.get("linux-arm64"))
    cpp = Target(name="app", language=Language.CPP)
    c = Target(name="lib", language=Language.C, standard="c11")
    args = flags.compile_args(tc, cpp, Path("a.cpp"), Path("a.o"), debug=True)
    assert args[:4] == ["/z/zig", "c++", "-target", "aarch64-linux-gnu"]
    assert flags.compile_args(tc, c, Path("a.c"), Path("a.o"), debug=True)[:2] == ["/z/zig", "cc"]
    assert flags.link_args(tc, cpp, [Path("a.o")], Path("app"))[:4] == ["/z/zig", "c++", "-target", "aarch64-linux-gnu"]
    lib = Target(name="lib", kind=Kind.STATIC_LIBRARY)
    assert flags.link_args(tc, lib, [Path("a.o")], Path("liblib.a"))[:3] == ["/z/zig", "ar", "rcs"]


def test_plain_toolchains_get_no_extra_arguments():
    args = flags.compile_args(GCC, Target(name="a", language=Language.CPP), Path("a.cpp"), Path("a.o"), debug=False)
    assert args[0] == "g++" and args[1] == "-c"


@pytest.mark.parametrize("target_os, kind, expected", [
    (OS.WINDOWS, Kind.EXECUTABLE, "app.exe"),
    (OS.LINUX, Kind.EXECUTABLE, "app"),
    (OS.WASI, Kind.EXECUTABLE, "app.wasm"),
    (OS.WASM, Kind.EXECUTABLE, "app.js"),
    (OS.BAREMETAL, Kind.EXECUTABLE, "app.elf"),
    (OS.ANDROID, Kind.SHARED_LIBRARY, "libapp.so"),
    (OS.IOS, Kind.SHARED_LIBRARY, "libapp.dylib"),
    (OS.WINDOWS, Kind.SHARED_LIBRARY, "app.dll"),
    (OS.FREEBSD, Kind.STATIC_LIBRARY, "libapp.a"),
])
def test_output_names_per_target_os(target_os, kind, expected):
    assert flags.output_filename(Target(name="app", kind=kind), target_os, GCC) == expected


def test_a_gnu_toolchain_on_windows_makes_dlls_not_shared_objects():
    assert flags.output_filename(Target(name="p", kind=Kind.SHARED_LIBRARY), OS.WINDOWS, GCC) == "p.dll"


def test_webassembly_has_no_shared_libraries():
    with pytest.raises(ChError) as exc:
        flags.output_filename(Target(name="p", kind=Kind.SHARED_LIBRARY), OS.WASI, GCC)
    assert exc.value.code == "CH3007"


# ------------------------------------------------------------------ planning
def _workspace(tmp_path):
    (tmp_path / "a.cpp").write_text("x")
    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="app", source_patterns=["*.cpp"], location=tmp_path))
    return ws


def test_a_cross_plan_has_its_own_directory_ids_and_arguments(tmp_path):
    ws = _workspace(tmp_path)
    tc = cross.specialise(ZIG, platforms.get("linux-arm64"))
    plan = plan_workspace(ws, tc, OS.LINUX)
    ids = list(plan.graph.actions)
    assert all(i.startswith("linux-arm64/") for i in ids)
    link = plan.graph.actions["linux-arm64/link:app"]
    assert "Debug-linux-arm64" in str(link.outputs[0])
    assert link.argv[:4] == ("/z/zig", "c++", "-target", "aarch64-linux-gnu")


def test_a_native_plan_is_unchanged(tmp_path):
    plan = plan_workspace(_workspace(tmp_path), GCC, OS.LINUX)
    assert "link:app" in plan.graph.actions
    assert str(plan.graph.actions["link:app"].outputs[0]).endswith(os.path.join("build", "Debug", "app", "app"))


def test_platform_overlays_follow_the_cross_target(tmp_path):
    ws = _workspace(tmp_path)
    with_overlay = ws.targets["app"]
    from charpente.dsl.model import Overlay

    with_overlay.overlays.append(Overlay(when={"platform": "linux-arm64"}, define_macros=["ARM=1"]))
    tc = cross.specialise(ZIG, platforms.get("linux-arm64"))
    plan = plan_workspace(ws, tc, OS.LINUX)
    compile_action = next(a for a in plan.graph.actions.values() if a.kind == "compile")
    assert "-DARM=1" in compile_action.argv
    assert "-DARM=1" not in next(a for a in plan_workspace(ws, GCC, OS.LINUX).graph.actions.values()
                                 if a.kind == "compile").argv        # a native build is not the arm64 platform


# ------------------------------------------------------------------ running foreign programs
def test_native_and_emulated_programs_run_directly():
    x64 = platforms.get("windows-x64")
    arm = platforms.get("windows-arm64")
    assert runners.command("p.exe", "windows-x64", x64) == ["p.exe"]
    assert runners.command("p.exe", "windows-x64", arm, program_args=["-v"]) == ["p.exe", "-v"]   # emulation
    with pytest.raises(ChError):
        runners.command("p", "windows-arm64", x64)                                                # not the other way


def test_wasi_prefers_wasmtime_then_node():
    host = platforms.get("linux-x64")
    both = lambda n: f"/bin/{n}"                                          # noqa: E731
    assert runners.command("p.wasm", "wasm32-wasi", host, which=both)[:2] == ["/bin/wasmtime", "run"]
    only_node = lambda n: "/bin/node" if n == "node" else None            # noqa: E731
    argv = runners.command("p.wasm", "wasm32-wasi", host, which=only_node, program_args=["x"])
    assert argv[0] == "/bin/node" and "node:wasi" in argv[3] and argv[-2:] == ["p.wasm", "x"]


def test_emscripten_output_runs_under_node():
    host = platforms.get("linux-x64")
    assert runners.command("p.js", "wasm32-emscripten", host, which=lambda n: "/bin/node") == ["/bin/node", "p.js"]


def test_a_program_for_another_os_is_refused_clearly():
    host = platforms.get("windows-x64")
    with pytest.raises(ChError) as exc:
        runners.command("p", "linux-arm64", host, which=lambda n: None)
    assert exc.value.code == "CH8004"
    with pytest.raises(ChError):
        runners.command("p.wasm", "wasm32-wasi", host, which=lambda n: None)     # no runtime at all


# ------------------------------------------------------------------ installing zig
INDEX = {
    "master": {"x86_64-linux": {"tarball": "http://x/master", "shasum": "00"}},
    "0.9.1": {"x86_64-linux": {"tarball": "http://x/old", "shasum": "11", "size": "5"}},
    "0.10.0": {"x86_64-linux": {"tarball": "http://x/new", "shasum": "AB" * 32, "size": "123"}},
}


def test_the_newest_release_is_chosen_never_master():
    release = toolchain_install.choose_zig(INDEX, None, "x86_64-linux")
    assert release.version == "0.10.0"
    assert release.sha256 == "ab" * 32 and release.size == 123
    assert release.folder == "zig-0.10.0"


def test_a_pinned_version_and_its_errors():
    assert toolchain_install.choose_zig(INDEX, "0.9.1", "x86_64-linux").url == "http://x/old"
    with pytest.raises(ChError) as exc:
        toolchain_install.choose_zig(INDEX, "0.1.0", "x86_64-linux")
    assert exc.value.code == "CH8005" and "0.10.0" in str(exc.value)
    with pytest.raises(ChError) as exc:
        toolchain_install.choose_zig(INDEX, None, "riscv64-freebsd")
    assert "no download" in str(exc.value)


def _fake_zig_archive(tmp_path, version, host_key, as_zip):
    exe = "zig.exe" if os.name == "nt" else "zig"
    top = f"zig-{host_key}-{version}"
    name = top + (".zip" if as_zip else ".tar.gz")
    path = tmp_path / name
    if as_zip:
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(f"{top}/{exe}", "#!fake\n")
            zf.writestr(f"{top}/lib/std.txt", "std")
    else:
        with tarfile.open(path, "w:gz") as tf:
            data = b"#!fake\n"
            info = tarfile.TarInfo(f"{top}/{exe}")
            info.size, info.mode = len(data), 0o755
            tf.addfile(info, io.BytesIO(data))
    return path


@pytest.mark.parametrize("as_zip", [True, False])
def test_install_verifies_extracts_and_is_detected(tmp_path, as_zip):
    archive = _fake_zig_archive(tmp_path, "9.9.9", "x86_64-linux", as_zip)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    index = {"9.9.9": {"x86_64-linux": {"tarball": archive.as_uri(), "shasum": digest}}}
    target = toolchain_install.install_zig("9.9.9", index_fetcher=lambda url: index, host_key="x86_64-linux")
    assert (target / "charpente-install.json").is_file()
    assert json.loads((target / "charpente-install.json").read_text())["sha256"] == digest
    assert toolchain_install.installed()[0][:2] == ("zig", "9.9.9")
    found = toolchains.detect_zig()                    # the real `which`: finds the installed copy
    if shutil_which_zig() is None:
        assert [t.name for t in found] == ["zig"] and "zig-9.9.9" in found[0].c_compiler
    assert toolchain_install.install_zig("9.9.9", index_fetcher=lambda url: index, host_key="x86_64-linux") == target
    assert not (toolchains.toolchains_dir() / "downloads" / archive.name).exists()


def shutil_which_zig():
    import shutil
    return shutil.which("zig")


def test_a_tampered_download_is_refused_and_nothing_is_installed(tmp_path):
    archive = _fake_zig_archive(tmp_path, "9.9.9", "x86_64-linux", True)
    index = {"9.9.9": {"x86_64-linux": {"tarball": archive.as_uri(), "shasum": "0" * 64}}}
    with pytest.raises(ChError) as exc:
        toolchain_install.install_zig("9.9.9", index_fetcher=lambda url: index, host_key="x86_64-linux")
    assert exc.value.code == "CH6002"
    assert toolchain_install.installed() == []


def test_remove_deletes_only_what_was_installed(tmp_path):
    archive = _fake_zig_archive(tmp_path, "9.9.9", "x86_64-linux", True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    index = {"9.9.9": {"x86_64-linux": {"tarball": archive.as_uri(), "shasum": digest}}}
    target = toolchain_install.install_zig("9.9.9", index_fetcher=lambda url: index, host_key="x86_64-linux")
    with pytest.raises(ChError):
        toolchain_install.remove("zig@1.0.0")
    assert toolchain_install.remove("zig@9.9.9") == target.resolve()
    assert not target.exists()
    with pytest.raises(ChError):
        toolchain_install.remove("zig")


def test_detection_with_an_injected_which_ignores_installed_copies(tmp_path):
    assert toolchains.detect_zig(lambda n: None) == []
    assert toolchains.detect_zig(lambda n: "/opt/zig" if n == "zig" else None)[0].c_compiler == "/opt/zig"


def test_zig_is_the_last_native_choice_and_lists_its_targets():
    found = toolchains.detect(OS.LINUX, lambda n: f"/bin/{n}")
    assert [t.name for t in found][-2:] == ["zig", "emscripten"]
    assert "wasm32-wasi" in found[-2].targets


# ------------------------------------------------------------------ the commands
def test_platforms_command_json(capsys, monkeypatch):
    from charpente.commands import platforms as command

    monkeypatch.setattr(toolchains, "detect", lambda _os, which=None: [ZIG])
    assert command.execute(["--json", "--family", "web"]) == 0
    data = json.loads(capsys.readouterr().out)
    names = [p["name"] for p in data["platforms"]]
    assert names == ["wasm32-emscripten"]
    assert data["platforms"][0]["needs"]


def test_platforms_command_table_mentions_tiers(capsys):
    from charpente.commands import platforms as command

    assert command.execute([]) == 0
    out = capsys.readouterr().out
    assert "Tier 1" in out and "linux-arm64" in out


# ------------------------------------------------------------------ assembly and Objective-C
def test_assembly_goes_through_the_c_driver_without_a_language_standard():
    tc = cross.specialise(ZIG, platforms.get("linux-arm64"))
    args = flags.compile_args(tc, Target(name="a", language=Language.CPP), Path("x.S"), Path("x.o"), debug=True,
                              depfile=Path("x.d"))
    assert args[:4] == ["/z/zig", "cc", "-target", "aarch64-linux-gnu"]
    assert not any(a.startswith("-std=") for a in args)
    assert "-MMD" in args


def test_objective_cpp_uses_the_cxx_driver_and_the_targets_standard():
    args = flags.compile_args(GCC, Target(name="a", language=Language.CPP, standard="c++20"), Path("v.mm"),
                              Path("v.o"), debug=False)
    assert args[0] == "g++" and "-std=c++20" in args
    plain = flags.compile_args(GCC, Target(name="a", language=Language.C, standard="c11"), Path("v.m"),
                               Path("v.o"), debug=False)
    assert plain[0] == "gcc" and not any(a.startswith("-std=") for a in plain)


def test_msvc_style_toolchains_refuse_assembly_instead_of_guessing():
    msvc = Toolchain(name="msvc", c_compiler="cl", cxx_compiler="cl", archiver="lib", linker="cl")
    with pytest.raises(ChError) as exc:
        flags.compile_args(msvc, Target(name="a"), Path("x.s"), Path("x.obj"), debug=True)
    assert exc.value.code == "CH3007"


def test_a_silent_tool_failure_names_the_tool_and_the_exit_code():
    from charpente.builder import _silent_failure
    from charpente.core.engine import STATUS_FAILED, ActionResult

    text = _silent_failure(ActionResult("x", STATUS_FAILED, returncode=3, command=["C:/bin/gcc.EXE", "-c"]))
    assert "gcc.EXE" in text and "code 3" in text


# ------------------------------------------------------------------ emscripten
def test_emscripten_is_never_the_native_default():
    only_emcc = lambda n: f"/emsdk/{n}" if n in ("emcc", "em++", "emar") else None      # noqa: E731
    found = toolchains.detect(OS.LINUX, only_emcc)
    assert [t.name for t in found] == ["emscripten"] and found[0].cross_only
    with pytest.raises(ChError) as exc:
        toolchains.pick_default(OS.LINUX, only_emcc)
    assert exc.value.code == "CH2001"


def test_emscripten_builds_the_wasm_platform_and_names_its_outputs(monkeypatch):
    monkeypatch.setattr(cross, "host_os", lambda: OS.LINUX)
    monkeypatch.setattr(platforms, "host", lambda: LINUX_X64)
    emcc = Toolchain(name="emscripten", c_compiler="emcc", cxx_compiler="em++", archiver="emar", linker="em++",
                     targets=("wasm32-emscripten",), cross_only=True)
    target_os, tc = _select("wasm32-emscripten", found=(GCC, emcc))
    assert (target_os, tc.name, tc.target) == (OS.WASM, "emscripten", "wasm32-emscripten")
    assert _select(None, found=(emcc, GCC))[1] is GCC                      # not chosen without --platform
    app = Target(name="app")
    assert flags.output_filename(app, OS.WASM, emcc) == "app.js"
    assert flags.side_outputs(app, OS.WASM, Path("out/app.js")) == [Path("out/app.wasm")]
    assert flags.side_outputs(app, OS.LINUX, Path("out/app")) == []


def test_an_emsdk_directory_becomes_a_toolchain_with_its_environment(tmp_path):
    suffix = ".bat" if os.name == "nt" else ""
    tools = tmp_path / "upstream" / "emscripten"
    tools.mkdir(parents=True)
    for tool in ("emcc", "em++", "emar"):
        (tools / f"{tool}{suffix}").write_text("")
    (tmp_path / ".emscripten").write_text("")
    tc = toolchains._emscripten_from(tmp_path)
    assert tc is not None and tc.cxx_compiler.endswith(f"em++{suffix}")
    assert dict(tc.env)["EM_CONFIG"].endswith(".emscripten") and "EMSDK" in dict(tc.env)
    assert toolchains._emscripten_from(tmp_path / "nowhere") is None


def test_toolchain_environment_reaches_the_actions(tmp_path):
    tc = Toolchain(name="emscripten", c_compiler="emcc", cxx_compiler="em++", archiver="emar", linker="em++",
                   targets=("wasm32-emscripten",), env=(("EM_CONFIG", "/x/.emscripten"),), cross_only=True)
    plan = plan_workspace(_workspace(tmp_path), cross.specialise(tc, platforms.get("wasm32-emscripten")), OS.WASM)
    assert all(("EM_CONFIG", "/x/.emscripten") in a.env for a in plan.graph.actions.values())
    link = next(a for a in plan.graph.actions.values() if a.kind == "link")
    assert [p.suffix for p in link.outputs] == [".js", ".wasm"]


# ------------------------------------------------------------------ installing emsdk
class _Recorder:
    def __init__(self, fail_at=None):
        self.calls, self.fail_at = [], fail_at

    def __call__(self, argv, **kwargs):
        import subprocess

        self.calls.append((list(argv), kwargs.get("cwd")))
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")
        if len(self.calls) == 1:                      # the clone creates the directory
            Path(argv[-1]).mkdir(parents=True)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def test_emsdk_install_runs_clone_install_activate_without_a_shell():
    rec = _Recorder()
    which = lambda n: f"/bin/{n}"                                                   # noqa: E731
    target = toolchain_install.install_emsdk("4.0.10", runner=rec, which=which, say=lambda t: None)
    assert target.name == "emsdk-4.0.10"
    assert [c[0][1] for c in rec.calls] == ["clone", "emsdk.py", "emsdk.py"]
    assert [c[0][2] for c in rec.calls[1:]] == ["install", "activate"]
    assert all(isinstance(a, str) for c in rec.calls for a in c[0])
    assert toolchain_install.install_emsdk("4.0.10", runner=rec, which=which) == target and len(rec.calls) == 3


def test_emsdk_failure_cleans_up_and_reports():
    rec = _Recorder(fail_at=2)
    with pytest.raises(ChError) as exc:
        toolchain_install.install_emsdk("latest", runner=rec, which=lambda n: f"/bin/{n}", say=lambda t: None)
    assert exc.value.code == "CH8005" and "boom" in str(exc.value)
    assert not (toolchains.toolchains_dir() / "emsdk-latest").exists()


def test_emsdk_needs_git_python_and_a_sane_version():
    with pytest.raises(ChError):
        toolchain_install.install_emsdk("latest", which=lambda n: None)
    with pytest.raises(ChError) as exc:
        toolchain_install.install_emsdk("../../evil", which=lambda n: f"/bin/{n}")
    assert "not 'latest'" in str(exc.value)


# ------------------------------------------------------------------ doctor
def test_doctor_reports_what_can_be_built_and_what_is_missing(monkeypatch, capsys):
    from charpente.commands import doctor

    monkeypatch.setattr(platforms, "host", lambda: LINUX_X64)
    monkeypatch.setattr(toolchains, "detect", lambda _os, which=None: [GCC, ZIG])
    report = doctor.gather()
    assert report["host"] == "linux-x64"
    assert "linux-arm64" in report["buildable"] and "wasm32-wasi" in report["buildable"]
    assert "android-arm64" in report["missing"] and "wasm32-emscripten" in report["missing"]
    assert doctor.execute(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["host"] == "linux-x64"


def test_doctor_fails_when_nothing_can_be_built(monkeypatch, capsys):
    from charpente.commands import doctor

    monkeypatch.setattr(platforms, "host", lambda: LINUX_X64)
    monkeypatch.setattr(toolchains, "detect", lambda _os, which=None: [])
    assert doctor.execute([]) == 1
    assert "none found" in capsys.readouterr().out
