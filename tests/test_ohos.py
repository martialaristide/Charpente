"""OpenHarmony/HarmonyOS native toolchain and SDK installer (fake SDK trees; the real SDK run is in docs/plans/phase-4c.md)."""
import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

import pytest
from helpers import GCC

from charpente import cross, flags, ohos, platforms, toolchain_install, toolchains
from charpente.core.planner import plan_workspace
from charpente.dsl.model import OS, Kind, Target, Workspace
from charpente.errors import ChError


def make_native(root: Path) -> Path:
    (root / "llvm" / "bin").mkdir(parents=True)
    (root / "sysroot").mkdir()
    return root


def test_native_sdk_is_found_from_the_environment_and_default_places(tmp_path):
    native = make_native(tmp_path / "sdk" / "native")
    assert ohos.find_native({"OHOS_NDK_HOME": str(native)}, tmp_path) == native
    assert ohos.find_native({"OHOS_SDK_HOME": str(tmp_path / "sdk")}, tmp_path) == native
    deveco = make_native(tmp_path / "Huawei" / "Sdk" / "openharmony" / "12" / "native")
    assert ohos.find_native({"LOCALAPPDATA": str(tmp_path)}, tmp_path) == deveco
    assert ohos.find_native({"OHOS_NDK_HOME": str(tmp_path / "not-a-sdk")}, tmp_path / "empty") is None


def test_the_toolchain_the_installer_lays_out_is_discovered(tmp_path):
    installed = make_native(toolchains.toolchains_dir() / "ohos-5.0.0")
    assert ohos.find_native({}, tmp_path) == installed


def test_specialisation_uses_the_musl_sysroot_and_the_ohos_triples(tmp_path):
    native = make_native(tmp_path / "native")
    tc = ohos.ohos_toolchain(native, "win32")
    assert tc.cross_only and tc.cxx_compiler.endswith("clang++.exe") and set(tc.targets) == set(ohos.TARGETS)
    arm64 = cross.specialise(tc, platforms.get("harmonyos-arm64"))
    assert arm64.cxx_args[0] == "--target=aarch64-linux-ohos" and f"--sysroot={native / 'sysroot'}" in arm64.cxx_args
    assert "-D__MUSL__" in arm64.c_args and "-D__MUSL__" not in arm64.ld_args
    assert {"-fno-addrsig", "-fstack-protector-strong", "-Werror=format-security"} <= set(arm64.c_args)
    assert {"-fuse-ld=lld", "--rtlib=compiler-rt", "-Wl,-z,noexecstack"} <= set(arm64.ld_args)
    arm = cross.specialise(tc, platforms.get("harmonyos-arm"))
    assert "-march=armv7a" in arm.c_args and arm.ld_args[0] == "--target=arm-linux-ohos"
    assert cross.specialise(tc, platforms.get("harmonyos-x64")).target == "harmonyos-x64"


def test_shared_libraries_for_ohos_are_pic_so_files(tmp_path):
    tc = cross.specialise(ohos.ohos_toolchain(make_native(tmp_path / "n"), "win32"), platforms.get("harmonyos-arm64"))
    lib = Target(name="entry", kind=Kind.SHARED_LIBRARY)
    assert "-fPIC" in flags.compile_args(tc, lib, Path("a.cpp"), Path("a.o"), debug=False)
    link = flags.link_args(tc, lib, [Path("a.o")], Path("libentry.so"))
    assert "-shared" in link and "-Wl,--no-undefined" in link and link[-2:] == ["-lunwind", "-lm"]
    assert "-static-libstdc++" not in link                                      # the SDK's default STL is shared
    static = Target(name="entry", kind=Kind.SHARED_LIBRARY, platform_settings={"harmony": {"stl": "static"}})
    assert "-static-libstdc++" in flags.link_args(tc, static, [Path("a.o")], Path("libentry.so"))
    exe = flags.link_args(tc, Target(name="t"), [Path("a.o")], Path("t"))
    assert "-Wl,--gc-sections" in exe and "-Wl,--no-undefined" not in exe
    assert flags.output_filename(lib, OS.OHOS, tc) == "libentry.so"
    (tmp_path / "a.cpp").write_text("x")
    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="entry", kind=Kind.SHARED_LIBRARY, source_patterns=["*.cpp"], location=tmp_path))
    plan = plan_workspace(ws, tc, OS.OHOS)
    assert not plan.errors and "harmonyos-arm64/link:entry" in plan.graph.actions


def test_a_mobile_app_is_the_native_library_of_the_harmonyos_app(tmp_path):
    tc = cross.specialise(ohos.ohos_toolchain(make_native(tmp_path / "n"), "win32"), platforms.get("harmonyos-arm64"))
    (tmp_path / "a.cpp").write_text("x")
    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="entry", kind=Kind.MOBILE_APP, source_patterns=["*.cpp"], location=tmp_path))
    plan = plan_workspace(ws, tc, OS.OHOS)
    assert not plan.errors and str(plan.outputs["entry"]).endswith("libentry.so")
    link = next(a for a in plan.graph.actions.values() if a.kind == "link")
    assert "-shared" in link.argv


def test_selection_routes_harmony_platforms_to_the_ohos_toolchain(tmp_path, monkeypatch):
    tc = ohos.ohos_toolchain(make_native(tmp_path / "n"), "win32")
    monkeypatch.setattr(cross, "host_os", lambda: OS.WINDOWS)
    monkeypatch.setattr(platforms, "host", lambda: platforms.get("windows-x64"))
    target_os, chosen = cross.select("harmonyos-arm64", None, detect=lambda _os: [GCC, tc])
    assert target_os == OS.OHOS and chosen.target == "harmonyos-arm64"
    with pytest.raises(ChError) as exc:
        cross.select("harmonyos-arm64", None, detect=lambda _os: [GCC])
    assert exc.value.code == "CH8002" and "SDK" in str(exc.value)


def test_detection_is_hermetic_with_an_injected_which():
    assert toolchains.detect_ohos(lambda n: "/x") == []


# ------------------------------------------------------------------ installer
def test_release_urls_are_built_from_a_validated_version():
    assert toolchain_install.ohos_release_url("5.0.0", host_tag="windows-x64").endswith("/5.0.0-Release/ohos-sdk-windows_linux-public.tar.gz")
    assert toolchain_install.ohos_release_url("5.0.0", host_tag="linux-x64").endswith("/5.0.0-Release/ohos-sdk-windows_linux-public.tar.gz")
    assert toolchain_install.ohos_release_url("5.0.0", host_tag="mac").endswith("/5.0.0-Release/ohos-sdk-mac-public.tar.gz")          # macOS has its own archive
    assert toolchain_install.ohos_release_url("5.0.0").endswith(".tar.gz")                                                           # this machine's
    assert "/6.0-Release/" in toolchain_install.ohos_release_url("6.0-Release")
    for bad in ("../x", "5.0.0/evil", "latest", ""):
        with pytest.raises(ChError):
            toolchain_install.ohos_release_url(bad)


def test_the_native_member_is_picked_for_the_host():
    names = ["ohos-sdk/windows/ets-windows-x64-5.0.0.zip", "ohos-sdk/windows/native-windows-x64-5.0.0.zip",
             "ohos-sdk/linux/native-linux-x64-5.0.0.zip", "ohos-sdk/linux/toolchains-linux-x64-5.0.0.zip"]
    assert toolchain_install.pick_ohos_native(names, "windows-x64") == "ohos-sdk/windows/native-windows-x64-5.0.0.zip"
    assert toolchain_install.pick_ohos_native(names, "linux-x64") == "ohos-sdk/linux/native-linux-x64-5.0.0.zip"
    assert toolchain_install.pick_ohos_native(names, "mac") is None


def _sdk_release(tmp_path, native_present=True):
    """A fake release folder: the .tar.gz holding several zips, and its .sha256 file, served from disk."""
    release = tmp_path / "repo" / "5.0.0-Release"
    release.mkdir(parents=True)
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("native/llvm/bin/clang.exe", "x")
        zf.writestr("native/sysroot/usr/include/stdio.h", "x")
    archive = release / "ohos-sdk-windows_linux-public.tar.gz"
    native_name = "ohos-sdk/windows/native-windows-x64-5.0.0.zip" if native_present else "ohos-sdk/windows/other.zip"
    with tarfile.open(archive, "w:gz") as tf:
        for name, data in (("ohos-sdk/windows/ets-windows-x64-5.0.0.zip", b"ets"), (native_name, inner.getvalue())):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (release / (archive.name + ".sha256")).write_text(digest + "\n")
    return (tmp_path / "repo").as_uri() + "/", digest


def test_install_verifies_the_archive_and_unpacks_only_the_native_component(tmp_path):
    base, _digest = _sdk_release(tmp_path)
    target = toolchain_install.install_ohos("5.0.0", base=base, say=lambda t: None, host_tag="windows-x64")
    assert target.name == "ohos-5.0.0" and (target / "llvm" / "bin" / "clang.exe").is_file()
    assert (target / "sysroot").is_dir() and not any("ets" in p.name for p in target.iterdir())
    assert ohos.find_native({}, tmp_path) == target
    assert ("ohos", "5.0.0", target) in toolchain_install.installed()
    assert not (toolchains.toolchains_dir() / "downloads" / "ohos-sdk-windows_linux-public.tar.gz").exists()
    assert toolchain_install.install_ohos("5.0.0", base=base, say=lambda t: None, host_tag="windows-x64") == target


def test_a_missing_native_component_or_bad_checksum_installs_nothing(tmp_path):
    base, _ = _sdk_release(tmp_path)
    other = tmp_path / "second"
    other.mkdir()
    base_missing, _ = _sdk_release(other, native_present=False)
    with pytest.raises(ChError) as exc:
        toolchain_install.install_ohos("5.0.0", base=base_missing, say=lambda t: None, host_tag="windows-x64")
    assert "no native component" in str(exc.value)
    assert not (toolchains.toolchains_dir() / "ohos-5.0.0").exists()
    (tmp_path / "repo" / "5.0.0-Release" / "ohos-sdk-windows_linux-public.tar.gz.sha256").write_text("0" * 64 + "\n")
    with pytest.raises(ChError) as exc:
        toolchain_install.install_ohos("5.0.0", base=base, say=lambda t: None, host_tag="windows-x64")
    assert exc.value.code == "CH6002"


def test_sdk_info_and_alignment_with_the_sdks_own_toolchain_file(tmp_path):
    native = make_native(tmp_path / "native")
    assert ohos.sdk_info(native) == {}
    (native / "oh-uni-package.json").write_text('{"version": "5.0.0.71", "apiVersion": "12"}')
    assert ohos.sdk_info(native) == {"version": "5.0.0.71", "api": "12"}
    assert "not found" in ohos.alignment(native)[0]
    reference = native / "build" / "cmake"
    reference.mkdir(parents=True)
    words = " ".join(ohos._REFERENCE_WORDS)
    (reference / "ohos.toolchain.cmake").write_text(words)
    assert ohos.alignment(native) == []
    (reference / "ohos.toolchain.cmake").write_text(words.replace("-fno-addrsig", "-fsomething-new"))
    assert ohos.alignment(native) == ["-fno-addrsig"]                               # a newer SDK changed a default
