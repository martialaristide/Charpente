"""Android: SDK/NDK discovery, the NDK toolchain, manifest, APK steps, adb parsing, SDK component install.

Everything runs against fake SDK trees, a recording process runner and a repository served from disk.
The real end-to-end run (NDK build, signed APK, install and launch on an emulator) is described in
docs/plans/phase-4b.md.
"""
import hashlib
import subprocess
import zipfile
from pathlib import Path

import pytest
from helpers import GCC

from charpente import android, cross, flags, platforms, toolchain_install, toolchains
from charpente.core.planner import plan_workspace
from charpente.dsl.model import OS, Kind, Language, Target, Workspace
from charpente.errors import ChError

WIN = "win32"


def make_sdk(root: Path, *, ndk="28.2.13676358", build_tools=("34.0.0", "36.1.0"), platforms_=("android-34", "android-36")):
    (root / "ndk" / ndk / "toolchains" / "llvm" / "prebuilt" / "windows-x86_64" / "bin").mkdir(parents=True)
    (root / "ndk" / ndk / "sources" / "android" / "native_app_glue").mkdir(parents=True)
    (root / "ndk" / ndk / "sources" / "android" / "native_app_glue" / "android_native_app_glue.c").write_text("")
    for v in build_tools:
        d = root / "build-tools" / v
        (d / "lib").mkdir(parents=True)
        for tool in ("aapt2.exe", "zipalign.exe", "apksigner.bat"):
            (d / tool).write_text("")
        (d / "lib" / "apksigner.jar").write_text("")
    for p in platforms_:
        (root / "platforms" / p).mkdir(parents=True)
        (root / "platforms" / p / "android.jar").write_text("")
    (root / "platform-tools").mkdir()
    (root / "platform-tools" / "adb.exe").write_text("")
    return root


class Recorder:
    def __init__(self, fail_containing=None, output=""):
        self.calls, self.fail, self.output = [], fail_containing, output

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if self.fail and self.fail in " ".join(argv):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="tool said no")
        return subprocess.CompletedProcess(argv, 0, stdout=self.output, stderr="")


# ------------------------------------------------------------------ discovery
def test_sdk_is_found_from_the_environment_and_picks_the_newest_tools(tmp_path):
    sdk = make_sdk(tmp_path / "sdk")
    found = android.find_sdk({"ANDROID_HOME": str(sdk)}, tmp_path)
    assert found is not None and found.root == sdk
    assert found.ndk.name == "28.2.13676358"
    assert found.build_tools.name == "36.1.0"                      # numeric, not lexical, ordering
    assert found.android_jar.parent.name == "android-36"
    assert android.find_sdk({"ANDROID_HOME": str(sdk)}, tmp_path, api=34).android_jar.parent.name == "android-34"
    assert found.tool("aapt2").name == "aapt2.exe"
    assert found.tool("adb").name == "adb.exe"
    assert found.tool("nothing") is None


def test_an_explicit_ndk_wins_over_the_sdks(tmp_path):
    sdk = make_sdk(tmp_path / "sdk")
    other = make_sdk(tmp_path / "other", ndk="27.0.1")
    found = android.find_sdk({"ANDROID_HOME": str(sdk), "ANDROID_NDK_HOME": str(other / "ndk" / "27.0.1")}, tmp_path)
    assert found.ndk.name == "27.0.1"


def test_no_sdk_anywhere_is_none(tmp_path):
    assert android.find_sdk({}, tmp_path) is None


def test_sdk_search_order_per_os(tmp_path):
    windows = android.sdk_roots({"LOCALAPPDATA": "C:/L"}, tmp_path, "win32")
    assert Path("C:/L/Android/Sdk") in windows
    assert tmp_path / "Library" / "Android" / "sdk" in android.sdk_roots({}, tmp_path, "darwin")
    assert tmp_path / "Android" / "Sdk" in android.sdk_roots({}, tmp_path, "linux")


# ------------------------------------------------------------------ the NDK toolchain
def test_ndk_toolchain_and_its_specialisation(tmp_path):
    ndk = make_sdk(tmp_path / "sdk").joinpath("ndk", "28.2.13676358")
    tc = android.ndk_toolchain(ndk, WIN)
    assert tc.cross_only and set(tc.targets) == {"android-arm64", "android-arm", "android-x64"}
    assert tc.cxx_compiler.endswith("clang++.exe") and tc.archiver.endswith("llvm-ar.exe")
    arm64 = cross.specialise(tc, platforms.get("android-arm64"), 26)
    assert arm64.cxx_args == ("--target=aarch64-linux-android26",)
    assert arm64.target == "android-arm64" and dict(arm64.extras)["abi"] == "arm64-v8a"
    assert cross.specialise(tc, platforms.get("android-arm")).c_args == ("--target=armv7a-linux-androideabi24",)
    assert android.native_app_glue_dir(arm64) == ndk / "sources" / "android" / "native_app_glue"
    assert android.native_app_glue_dir(GCC) is None


def test_ndk_is_only_selected_for_android_platforms(tmp_path, monkeypatch):
    ndk = make_sdk(tmp_path / "sdk").joinpath("ndk", "28.2.13676358")
    tc = android.ndk_toolchain(ndk, WIN)
    monkeypatch.setattr(cross, "host_os", lambda: OS.WINDOWS)
    monkeypatch.setattr(platforms, "host", lambda: platforms.get("windows-x64"))
    target_os, chosen = cross.select("android-arm64", None, detect=lambda _os: [GCC, tc], android_api=28)
    assert target_os == OS.ANDROID and chosen.cxx_args == ("--target=aarch64-linux-android28",)
    assert cross.select(None, None, detect=lambda _os: [tc, GCC])[1] is GCC


# ------------------------------------------------------------------ flags and planning
def _android_toolchain(tmp_path, platform="android-arm64"):
    ndk = make_sdk(tmp_path / "sdk").joinpath("ndk", "28.2.13676358")
    return cross.specialise(android.ndk_toolchain(ndk, WIN), platforms.get(platform))


def test_an_android_app_is_a_pic_shared_library_with_static_libcxx(tmp_path):
    tc = _android_toolchain(tmp_path)
    app = Target(name="game", kind=Kind.MOBILE_APP, language=Language.CPP)
    assert "-fPIC" in flags.compile_args(tc, app, Path("a.cpp"), Path("a.o"), debug=False)
    link = flags.link_args(tc, app, [Path("a.o")], Path("libgame.so"))
    assert "-shared" in link and "-static-libstdc++" in link and link[1] == "--target=aarch64-linux-android24"
    assert flags.output_filename(app, OS.ANDROID, tc) == "libgame.so"
    shared = Target(name="game", kind=Kind.MOBILE_APP, platform_settings={"android": {"stl": "shared"}})
    assert "-static-libstdc++" not in flags.link_args(tc, shared, [Path("a.o")], Path("libgame.so"))


def test_shared_libraries_get_fpic_but_not_on_windows_or_for_executables():
    lib = Target(name="p", kind=Kind.SHARED_LIBRARY)
    assert "-fPIC" in flags.compile_args(GCC, lib, Path("a.cpp"), Path("a.o"), debug=False)
    mingw = toolchains.Toolchain(name="mingw", c_compiler="gcc", cxx_compiler="g++", archiver="ar", linker="g++")
    assert "-fPIC" not in flags.compile_args(mingw, lib, Path("a.cpp"), Path("a.o"), debug=False)
    assert "-fPIC" not in flags.compile_args(GCC, Target(name="p"), Path("a.cpp"), Path("a.o"), debug=False)


def test_mobile_apps_are_only_buildable_for_android(tmp_path):
    (tmp_path / "a.cpp").write_text("x")
    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="game", kind=Kind.MOBILE_APP, source_patterns=["*.cpp"], location=tmp_path))
    assert plan_workspace(ws, GCC, OS.LINUX).errors["game"].code == "CH3007"
    plan = plan_workspace(ws, _android_toolchain(tmp_path), OS.ANDROID)
    assert not plan.errors and str(plan.outputs["game"]).endswith("libgame.so")


def test_native_app_glue_is_compiled_as_c_and_linked_with_the_right_libraries(tmp_path):
    (tmp_path / "a.cpp").write_text("x")
    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="game", kind=Kind.MOBILE_APP, source_patterns=["*.cpp"], location=tmp_path,
                         platform_settings={"android": {"package": "a.b", "native_app_glue": True}}))
    plan = plan_workspace(ws, _android_toolchain(tmp_path), OS.ANDROID)
    assert not plan.errors
    glue = next(a for a in plan.graph.actions.values() if a.source and a.source.name == "android_native_app_glue.c")
    assert "-std=c11" in glue.argv and not any(a.startswith("-std=c++") for a in glue.argv)
    assert any(a.startswith("-I") and "native_app_glue" in a for a in next(
        a for a in plan.graph.actions.values() if a.source and a.source.name == "a.cpp").argv)
    link = next(a for a in plan.graph.actions.values() if a.kind == "link")
    assert "-landroid" in link.argv and "-llog" in link.argv and "ANativeActivity_onCreate" in link.argv


def test_glue_without_the_ndk_sources_is_an_error_not_a_silent_omission(tmp_path):
    (tmp_path / "a.cpp").write_text("x")
    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="game", kind=Kind.MOBILE_APP, source_patterns=["*.cpp"], location=tmp_path,
                         platform_settings={"android": {"native_app_glue": True}}))
    tc = toolchains.Toolchain(name="ndk", c_compiler="c", cxx_compiler="c", archiver="a", linker="c",
                              targets=("android-arm64",), target="android-arm64", cross_only=True)
    assert plan_workspace(ws, tc, OS.ANDROID).errors["game"].code == "CH8007"


# ------------------------------------------------------------------ settings and manifest
def test_settings_are_validated_with_clear_errors():
    ok = android.settings_from("app", {"package": "com.example.app", "min_sdk": 26, "permissions": ["INTERNET"]},
                               debuggable=True)
    assert ok.min_sdk == 26 and ok.debuggable and ok.label == "app" and ok.library == "app"
    for raw, fragment in (({}, "needs android(package"), ({"package": "nodots"}, "not a valid application id"),
                          ({"package": "a.b", "min_sdk": "24"}, "positive integer"),
                          ({"package": "a.b", "orientation": "diagonal"}, "orientation"),
                          ({"package": "a.b", "colour": 1}, "unknown setting"),
                          ({"package": "a.b", "stl": "dynamic"}, "stl"),
                          ({"package": "a.b", "permissions": ["bad name"]}, "permission")):
        with pytest.raises(ChError) as exc:
            android.settings_from("app", raw, debuggable=False)
        assert exc.value.code == "CH8006" and fragment in str(exc.value)


def test_manifest_declares_the_native_activity_and_escapes_values():
    app = android.AppSettings(package="com.example.app", label='Tom & "Jerry"', library="game", min_sdk=26,
                              permissions=("INTERNET", "com.vendor.PERM"), gles_version="0x00030000",
                              orientation="landscape", debuggable=True)
    xml = android.manifest_xml(app)
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)                                       # well-formed
    ns = "{http://schemas.android.com/apk/res/android}"
    assert root.get("package") == "com.example.app"
    assert root.find("uses-sdk").get(ns + "minSdkVersion") == "26"
    assert [p.get(ns + "name") for p in root.findall("uses-permission")] == ["android.permission.INTERNET", "com.vendor.PERM"]
    application = root.find("application")
    assert application.get(ns + "label") == 'Tom & "Jerry"' and application.get(ns + "debuggable") == "true"
    activity = application.find("activity")
    assert activity.get(ns + "name") == "android.app.NativeActivity"
    assert activity.get(ns + "screenOrientation") == "landscape"
    assert activity.find("meta-data").get(ns + "value") == "game"


# ------------------------------------------------------------------ APK steps
def _steps(tmp_path, **kw):
    sdk = android.find_sdk({"ANDROID_HOME": str(make_sdk(tmp_path / "sdk"))}, tmp_path)
    app = android.AppSettings(package="a.b", label="A", library="game", **kw)
    signing = android.Signing(tmp_path / "k.jks", "key", "pass:android", "pass:android", True)
    steps = android.apk_steps(sdk, app, tmp_path / "stage", {"arm64-v8a": [tmp_path / "libgame.so"]}, signing,
                              tmp_path / "out.apk", which=lambda n: "/jdk/java")
    return steps


def test_apk_steps_run_in_order_and_use_argument_lists(tmp_path):
    steps = _steps(tmp_path)
    assert [s.label for s in steps] == ["Linking the manifest and resources", "Adding native libraries", "Aligning",
                                        "Signing"]
    link, _, align, sign = steps
    assert "--manifest" in link.argv and "--min-sdk-version" in link.argv
    assert align.argv[1:5] == ("-f", "-P", "16", "4")                     # build-tools 36: 16 KB pages
    assert sign.argv[:3] == ("/jdk/java", "-jar", str(tmp_path / "sdk" / "build-tools" / "36.1.0" / "lib" / "apksigner.jar"))
    assert "--v4-signing-enabled" in sign.argv and sign.argv[-2:] == (str(tmp_path / "out.apk"), str(tmp_path / "stage" / "aligned.apk"))
    assert all(isinstance(a, str) for s in steps for a in s.argv)


def test_older_build_tools_use_the_4kb_page_option(tmp_path):
    sdk = android.find_sdk({"ANDROID_HOME": str(make_sdk(tmp_path / "sdk", build_tools=("34.0.0",)))}, tmp_path)
    app = android.AppSettings(package="a.b", label="A", library="game")
    signing = android.Signing(tmp_path / "k.jks", "key", "pass:android", "pass:android", True)
    steps = android.apk_steps(sdk, app, tmp_path / "s", {}, signing, tmp_path / "o.apk", which=lambda n: None)
    assert steps[2].argv[1:4] == ("-f", "-p", "4")
    assert steps[3].argv[0].endswith("apksigner.bat")                     # no java on PATH: the wrapper script


def test_resources_and_assets_add_their_own_steps(tmp_path):
    steps = _steps(tmp_path, resources="res", assets="assets")
    assert steps[0].label == "Compiling resources"
    link = steps[1].argv
    assert "-A" in link and "assets" in link


def test_missing_build_tools_or_platform_is_reported_with_the_install_command(tmp_path):
    with pytest.raises(ChError) as exc:
        android.require_tools(None)
    assert exc.value.code == "CH8007" and "build-tools" in str(exc.value)
    bare = android.Sdk(root=tmp_path, build_tools=None)
    with pytest.raises(ChError):
        android.require_tools(bare)


def test_libraries_are_stored_uncompressed_under_lib_abi(tmp_path):
    apk = tmp_path / "base.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", "x")
    lib = tmp_path / "libgame.so"
    lib.write_bytes(b"\x7fELF" + b"0" * 1000)
    stl = tmp_path / "libc++_shared.so"
    stl.write_bytes(b"stl")
    android.add_libraries(apk, [f"arm64-v8a={lib}", f"arm64-v8a={stl}"])
    with zipfile.ZipFile(apk) as zf:
        infos = {i.filename: i for i in zf.infolist()}
    assert set(infos) == {"AndroidManifest.xml", "lib/arm64-v8a/libgame.so", "lib/arm64-v8a/libc++_shared.so"}
    assert infos["lib/arm64-v8a/libgame.so"].compress_type == zipfile.ZIP_STORED


def test_build_apk_runs_every_step_and_names_the_one_that_fails(tmp_path):
    sdk = android.find_sdk({"ANDROID_HOME": str(make_sdk(tmp_path / "sdk"))}, tmp_path)
    lib = tmp_path / "libgame.so"
    lib.write_bytes(b"elf")
    app = android.AppSettings(package="a.b", label="A", library="game")
    signing = android.Signing(tmp_path / "k.jks", "key", "pass:android", "pass:android", True)
    ok = Recorder()
    (tmp_path / "stage").mkdir()

    def aapt2_creates_the_apk(argv, **kw):
        if "link" in argv:
            with zipfile.ZipFile(argv[argv.index("-o") + 1], "w") as zf:
                zf.writestr("AndroidManifest.xml", "x")
        return ok(argv, **kw)

    said = []
    android.build_apk(sdk, app, {"arm64-v8a": [lib]}, signing, tmp_path / "dist" / "a.apk", tmp_path / "stage",
                      runner=aapt2_creates_the_apk, which=lambda n: "/jdk/java", say=said.append)
    assert said == ["Linking the manifest and resources", "Adding native libraries", "Aligning", "Signing"]
    assert (tmp_path / "stage" / "AndroidManifest.xml").is_file()
    assert [Path(c[0]).name for c in ok.calls] == ["aapt2.exe", "zipalign.exe", "java"]

    failing = Recorder(fail_containing="zipalign")
    with pytest.raises(ChError) as exc:
        android.build_apk(sdk, app, {"arm64-v8a": [lib]}, signing, tmp_path / "dist" / "b.apk", tmp_path / "stage2",
                          runner=lambda argv, **kw: (aapt2_creates_the_apk(argv, **kw) if "link" in argv else failing(argv)),
                          which=lambda n: "/jdk/java")
    assert exc.value.code == "CH8008" and "Aligning" in str(exc.value) and "tool said no" in str(exc.value)


def test_badging_and_verify_parse_the_tools_output(tmp_path):
    sdk = android.find_sdk({"ANDROID_HOME": str(make_sdk(tmp_path / "sdk"))}, tmp_path)
    text = ("package: name='a.b' versionCode='3' versionName='1.2' platformBuildVersionName='16'\n"
            "sdkVersion:'24'\nnative-code: 'arm64-v8a' 'x86_64'\n")
    facts = android.badging(sdk, tmp_path / "a.apk", runner=Recorder(output=text))
    assert facts == {"name": "a.b", "versionCode": "3", "versionName": "1.2", "minSdk": "24",
                     "native-code": "arm64-v8a x86_64"}
    assert "Verifies" in android.verify_apk(sdk, tmp_path / "a.apk", runner=Recorder(output="Verifies\n"),
                                            which=lambda n: "/jdk/java")
    with pytest.raises(ChError) as exc:
        android.verify_apk(sdk, tmp_path / "a.apk", runner=Recorder(fail_containing="verify"), which=lambda n: "/jdk/java")
    assert exc.value.code == "CH8008"


# ------------------------------------------------------------------ signing keys
def test_the_sdks_debug_keystore_is_reused(tmp_path):
    (tmp_path / ".android").mkdir()
    (tmp_path / ".android" / "debug.keystore").write_text("k")
    signing = android.debug_signing(tmp_path)
    assert signing.debug and signing.alias == "androiddebugkey" and signing.store_pass == "pass:android"


def test_a_debug_keystore_is_created_with_keytool_when_missing(tmp_path):
    rec = Recorder()
    with pytest.raises(ChError):                                       # nothing created -> keytool wrote nothing, still returns Signing
        android.debug_signing(tmp_path, runner=rec, which=lambda n: None)
    signing = android.debug_signing(tmp_path, runner=rec, which=lambda n: "/jdk/keytool")
    assert rec.calls[0][0] == "/jdk/keytool" and "-genkeypair" in rec.calls[0]
    assert signing.keystore.name == "debug.keystore"
    with pytest.raises(ChError):
        android.debug_signing(tmp_path, create=False, which=lambda n: None) if False else android.debug_signing(
            tmp_path / "other", create=False)


def test_release_signing_takes_the_password_from_the_environment_only(tmp_path):
    store = tmp_path / "release.jks"
    store.write_text("k")
    with pytest.raises(ChError) as exc:
        android.release_signing(store, "rel", env={})
    assert "CHARPENTE_KEYSTORE_PASSWORD" in str(exc.value)
    signing = android.release_signing(store, "rel", env={"CHARPENTE_KEYSTORE_PASSWORD": "s3cret"})
    assert signing.store_pass == "env:CHARPENTE_KEYSTORE_PASSWORD" and not signing.debug
    assert "s3cret" not in repr(signing)
    with pytest.raises(ChError):
        android.release_signing(tmp_path / "missing.jks", "rel", env={"CHARPENTE_KEYSTORE_PASSWORD": "x"})


# ------------------------------------------------------------------ adb
def test_devices_are_parsed_and_selected():
    text = "List of devices attached\nemulator-5554\tdevice\nABC123\tunauthorized\n\n* daemon started\n"
    devices = android.parse_devices(text)
    assert devices == [("emulator-5554", "device"), ("ABC123", "unauthorized")]
    assert android.select_device(devices, None) == "emulator-5554"
    with pytest.raises(ChError) as exc:
        android.select_device(devices, "ABC123")
    assert exc.value.code == "CH8009" and "unauthorized" not in str(exc.value).split("ready:")[0]
    with pytest.raises(ChError):
        android.select_device([], None)
    with pytest.raises(ChError) as exc:
        android.select_device([("a", "device"), ("b", "device")], None)
    assert "--device" in str(exc.value)


def test_install_and_launch_use_the_chosen_device_and_report_failures(tmp_path):
    rec = Recorder(output="Success")
    android.install_and_launch("adb", tmp_path / "a.apk", "a.b", serial="S1", runner=rec)
    assert rec.calls[0][:4] == ["adb", "-s", "S1", "install"] and rec.calls[1][-6:-1] == [
        "monkey", "-p", "a.b", "-c", "android.intent.category.LAUNCHER"]
    with pytest.raises(ChError) as exc:
        android.install_and_launch("adb", tmp_path / "a.apk", "a.b", runner=Recorder(output="Failure [INSTALL_FAILED_X]"))
    assert "adb install" in str(exc.value)
    with pytest.raises(ChError):
        android.install_and_launch("adb", tmp_path / "a.apk", "a.b", runner=Recorder(output="** No activities found"))


# ------------------------------------------------------------------ installing SDK components
REPO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sdk:sdk-repository xmlns:sdk="http://schemas.android.com/sdk/android/repo/repository2/03">
  <license id="android-sdk-license" type="text">Terms and Conditions - read me</license>
  <channel id="channel-0">stable</channel><channel id="channel-1">beta</channel>
  {packages}
</sdk:sdk-repository>"""


def _package(path, url, sha1, size, host=None, channel="channel-0", preview=False, extra=()):
    """One remotePackage; `extra` adds more archives as (host, url, sha1) -- one package, several hosts."""
    archives = []
    for archive_host, archive_url, archive_sha in [(host, url, sha1), *extra]:
        host_xml = f"<host-os>{archive_host}</host-os>" if archive_host else ""
        archives.append(f'<archive><complete><size>{size}</size><checksum type="sha1">{archive_sha}</checksum>'
                        f'<url>{archive_url}</url></complete>{host_xml}</archive>')
    prev = "<preview>1</preview>" if preview else ""
    return (f'<remotePackage path="{path}"><revision><major>1</major>{prev}</revision>'
            f'<display-name>{path} pkg</display-name><uses-license ref="android-sdk-license"/>'
            f'<channelRef ref="{channel}"/><archives>{"".join(archives)}</archives></remotePackage>')


def _repo(tmp_path, packages):
    (tmp_path / "repository2-3.xml").write_text(REPO_XML.format(packages="".join(packages)), encoding="utf-8")
    return tmp_path.as_uri() + "/"


def _zip_with(path, names):
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            zf.writestr(name, "data")
    return hashlib.sha1(path.read_bytes()).hexdigest(), path.stat().st_size


def test_ndk_install_needs_the_license_to_be_accepted_and_shows_it(tmp_path):
    (tmp_path / "repo").mkdir()
    sha, size = _zip_with(tmp_path / "repo" / "ndk.zip", ["android-ndk-r99/toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe"])
    base = _repo(tmp_path / "repo", [_package("ndk;99.0.1", "ndk.zip", sha, size)])
    said = []
    with pytest.raises(ChError) as exc:
        toolchain_install.install_android("ndk", base_url=base, say=said.append)
    assert exc.value.code == "CH8010" and "read me" in said[0]
    assert not (toolchain_install.android_sdk_root() / "ndk").exists()


def test_accepted_install_verifies_sha1_and_lays_out_like_the_sdk(tmp_path):
    (tmp_path / "repo").mkdir()
    sha, size = _zip_with(tmp_path / "repo" / "ndk.zip", ["android-ndk-r99/toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe"])
    base = _repo(tmp_path / "repo", [_package("ndk;99.0.1", "ndk.zip", sha, size)])
    target = toolchain_install.install_android("ndk", accept_license=True, base_url=base, say=lambda t: None)
    assert target == toolchain_install.android_sdk_root() / "ndk" / "99.0.1"
    assert (target / "toolchains" / "llvm").is_dir() and (target / "charpente-install.json").is_file()
    assert ("ndk", "99.0.1", target) in toolchain_install.installed()
    found = android.find_sdk({}, tmp_path)
    assert found is not None and found.ndk == target                   # the SDK Charpente maintains is discovered
    assert toolchain_install.remove("ndk@99.0.1") == target.resolve()


def test_a_wrong_checksum_installs_nothing(tmp_path):
    (tmp_path / "repo").mkdir()
    _, size = _zip_with(tmp_path / "repo" / "bt.zip", ["android-15/aapt2.exe"])
    base = _repo(tmp_path / "repo", [_package("build-tools;35.0.0", "bt.zip", "0" * 40, size)])
    with pytest.raises(ChError) as exc:
        toolchain_install.install_android("build-tools", accept_license=True, base_url=base, say=lambda t: None)
    assert exc.value.code == "CH6002"
    assert not (toolchain_install.android_sdk_root() / "build-tools").exists()


def test_component_resolution_prefers_the_newest_stable_release_for_this_host():
    import xml.etree.ElementTree as ET

    packages = [_package("ndk;27.0.1", "a.zip", "1" * 40, 1, host="windows"),
                _package("ndk;28.0.2", "b.zip", "2" * 40, 1, host="windows", extra=[("linux", "b-linux.zip", "3" * 40)]),
                _package("ndk;29.0.0-rc1", "c.zip", "4" * 40, 1, host="windows", preview=True),
                _package("ndk;30.0.0", "d.zip", "5" * 40, 1, host="windows", channel="channel-2"),
                _package("platforms;android-34", "p34.zip", "6" * 40, 1),
                _package("platforms;android-35", "p35.zip", "7" * 40, 1),
                _package("platforms;android-34-ext12", "e.zip", "8" * 40, 1),
                _package("platform-tools", "pt.zip", "9" * 40, 1, host="windows")]
    root = ET.fromstring(REPO_XML.format(packages="".join(packages)))
    assert toolchain_install.resolve_android(root, "ndk", "windows").url == "b.zip"
    assert toolchain_install.resolve_android(root, "ndk", "linux").url == "b-linux.zip"
    assert toolchain_install.resolve_android(root, "ndk@27.0.1", "windows").url == "a.zip"
    assert toolchain_install.resolve_android(root, "platform", "windows").url == "p35.zip"
    assert toolchain_install.resolve_android(root, "platform@34", "windows").url == "p34.zip"
    assert toolchain_install.resolve_android(root, "platform-tools", "windows").install_subdir == "platform-tools"
    assert toolchain_install.resolve_android(root, "ndk", "windows").install_subdir == "ndk/28.0.2"
    for bad in ("gradle", "ndk@1.2.3"):
        with pytest.raises(ChError):
            toolchain_install.resolve_android(root, bad, "windows")
    with pytest.raises(ChError) as exc:
        toolchain_install.resolve_android(root, "ndk", "macosx")
    assert "no download" in str(exc.value)


def test_a_manifest_that_declares_entities_is_refused(tmp_path):
    (tmp_path / "repository2-3.xml").write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')
    with pytest.raises(ChError) as exc:
        toolchain_install.fetch_android_manifest(tmp_path.as_uri() + "/")
    assert "entities" in str(exc.value)


def test_symlinks_in_toolchain_zips_stay_inside_the_archive(tmp_path):
    import os
    import stat

    from charpente.pkg import fetch

    def make(name, target):
        path = tmp_path / name
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("top/real", "x")
            info = zipfile.ZipInfo("top/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
        return path

    fetch.extract(make("ok.zip", "real"), tmp_path / "ok", strip_prefix="*", keep_exec=True)
    assert (tmp_path / "ok" / "real").is_file()
    if os.name != "nt":
        assert (tmp_path / "ok" / "link").is_symlink()
    with pytest.raises(ChError) as exc:
        fetch.extract(make("evil.zip", "../../etc/passwd"), tmp_path / "evil", strip_prefix="*", keep_exec=True)
    assert exc.value.code == "CH6012"


def test_doctor_lists_android_platforms_as_buildable_with_an_ndk(monkeypatch):
    from charpente.commands import doctor

    tc = toolchains.Toolchain(name="ndk", c_compiler="c", cxx_compiler="c", archiver="a", linker="c",
                              targets=tuple(android.ABIS), cross_only=True)
    monkeypatch.setattr(platforms, "host", lambda: platforms.get("windows-x64"))
    monkeypatch.setattr(toolchains, "detect", lambda _os, which=None: [GCC, tc])
    assert "android-arm64" in doctor.gather()["buildable"]


def test_only_a_mobile_app_target_can_become_an_apk(tmp_path):
    import argparse

    from charpente.commands import _android

    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="tool", kind=Kind.EXECUTABLE, location=tmp_path))
    with pytest.raises(ChError) as exc:
        _android.build_apk(argparse.Namespace(platform=None), ws, ws.targets["tool"])
    assert exc.value.code == "CH8006" and "MOBILE_APP" in str(exc.value)
    assert _android._platforms(argparse.Namespace(platform="android-arm64, android-x64")) == ["android-arm64", "android-x64"]
    with pytest.raises(ChError):
        _android._platforms(argparse.Namespace(platform="linux-x64"))
