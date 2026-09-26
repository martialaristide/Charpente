"""iOS/visionOS (no Mac involved: recording runner and fake trees) and Android XR profiles."""
import plistlib
import subprocess
import zipfile
from pathlib import Path

import pytest
from helpers import GCC

from charpente import android, apple, cross, flags, platforms, toolchains
from charpente.core.planner import plan_workspace
from charpente.dsl.model import OS, Kind, Language, Target, Workspace
from charpente.errors import ChError


class Rec:
    def __init__(self, sdk="/Xcode/SDKs/iPhoneOS.sdk", fail=False):
        self.calls, self.sdk, self.fail = [], sdk, fail

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if self.fail:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="nope")
        if "--find" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout=f"/Xcode/bin/{argv[-1]}\n", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout=self.sdk + "\n", stderr="")


def xcode():
    tc = apple.xcode_toolchain(runner=Rec(), which=lambda n: "/usr/bin/xcrun", platform_name="darwin")
    assert tc is not None
    return tc


# ------------------------------------------------------------------ toolchain
def test_xcode_is_only_detected_on_a_mac_with_xcrun():
    assert apple.xcode_toolchain(runner=Rec(), which=lambda n: "/x", platform_name="win32") is None
    assert apple.xcode_toolchain(runner=Rec(), which=lambda n: None, platform_name="darwin") is None
    assert apple.xcode_toolchain(runner=Rec(fail=True), which=lambda n: "/x", platform_name="darwin") is None
    tc = xcode()
    assert tc.cross_only and tc.cxx_compiler == "/Xcode/bin/clang++" and set(tc.targets) == set(apple.TARGETS)


def test_specialisation_sets_target_triple_and_sdk_root():
    tc = xcode()
    device = apple.specialise_xcode(tc, "ios-arm64", "15.0", runner=Rec())
    assert device.c_args == ("-target", "arm64-apple-ios15.0", "-isysroot", "/Xcode/SDKs/iPhoneOS.sdk")
    assert device.target == "ios-arm64" and dict(device.extras)["min_os"] == "15.0"
    sim = apple.specialise_xcode(tc, "ios-sim-x64", runner=Rec(sdk="/Xcode/SDKs/iPhoneSimulator.sdk"))
    assert sim.ld_args[1] == "x86_64-apple-ios13.0-simulator"
    vision = apple.specialise_xcode(tc, "visionos-arm64", runner=Rec(sdk="/X/XROS.sdk"))
    assert vision.c_args[1] == "arm64-apple-xros1.0"
    with pytest.raises(ChError):
        apple.specialise_xcode(tc, "ios-arm64", "latest", runner=Rec())
    with pytest.raises(ChError) as exc:
        apple.specialise_xcode(tc, "ios-arm64", runner=Rec(fail=True))
    assert exc.value.code == "CH8007" and "Xcode" in str(exc.value)


def test_cross_selection_routes_apple_platforms_to_xcode(monkeypatch):
    monkeypatch.setattr(cross, "host_os", lambda: OS.MACOS)
    monkeypatch.setattr(platforms, "host", lambda: platforms.get("macos-arm64"))
    monkeypatch.setattr(apple, "sdk_path", lambda tc, sdk, runner=None: "/sdk")
    target_os, tc = cross.select("ios-arm64", None, detect=lambda _os: [GCC, xcode()], apple_min="16.0")
    assert target_os == OS.IOS and tc.c_args[1] == "arm64-apple-ios16.0"
    with pytest.raises(ChError):
        cross.select("ios-arm64", None, detect=lambda _os: [GCC])          # no Xcode: CH8002 with the hint
    assert cross.select(None, None, detect=lambda _os: [xcode(), GCC])[1] is GCC


def test_detection_is_hermetic_with_an_injected_which():
    assert toolchains.detect_xcode(lambda n: "/x") == []


# ------------------------------------------------------------------ flags and planning
def test_ios_compile_and_link_lines(tmp_path):
    tc = apple.specialise_xcode(xcode(), "ios-arm64", runner=Rec())
    app = Target(name="app", kind=Kind.MOBILE_APP, language=Language.CPP,
                 platform_settings={"ios": {"frameworks": ["UIKit", "Metal"]}})
    objc = flags.compile_args(tc, app, Path("a.mm"), Path("a.o"), debug=True)
    assert "-fobjc-arc" in objc and objc[1:5] == ["-target", "arm64-apple-ios13.0", "-isysroot", "/Xcode/SDKs/iPhoneOS.sdk"]
    link = flags.link_args(tc, app, [Path("a.o")], Path("app"))
    assert link.count("-framework") == 2 and "-shared" not in link
    assert flags.output_filename(app, OS.IOS, tc) == "app"
    with pytest.raises(ChError):
        flags.link_args(tc, Target(name="x", platform_settings={"ios": {"frameworks": ["Bad Name"]}}), [], Path("x"))


def test_a_mobile_app_plans_for_ios_but_not_for_a_desktop(tmp_path):
    (tmp_path / "a.mm").write_text("x")
    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="app", kind=Kind.MOBILE_APP, source_patterns=["*.mm"], location=tmp_path))
    tc = apple.specialise_xcode(xcode(), "ios-arm64", runner=Rec())
    assert not plan_workspace(ws, tc, OS.IOS).errors
    assert plan_workspace(ws, GCC, OS.LINUX).errors["app"].code == "CH3007"


# ------------------------------------------------------------------ settings, plist, bundle
def test_settings_validation():
    ok = apple.settings_from("app", {"bundle_id": "com.example.app", "orientations": ["portrait"]}, "ios-sim-arm64")
    assert ok.identity == "-" and ok.min_os == "13.0" and ok.executable == "app" and not ok.vision
    device = apple.settings_from("app", {"bundle_id": "com.example.app"}, "ios-arm64")
    assert device.identity == ""
    vision = apple.settings_from("app", {"bundle_id": "com.example.app"}, "visionos-arm64")
    assert vision.vision and vision.device_family == (7,) and vision.min_os == "1.0"
    for raw, fragment in (({}, "needs platform_settings"), ({"bundle_id": "nodots"}, "valid bundle identifier"),
                          ({"bundle_id": "a.b", "min_os": "new"}, "min_os"), ({"bundle_id": "a.b", "colour": 1}, "unknown"),
                          ({"bundle_id": "a.b", "orientations": ["sideways"]}, "orientation"),
                          ({"bundle_id": "a.b", "device_family": [9]}, "device_family"),
                          ({"bundle_id": "a.b", "plist": 3}, "plist")):
        with pytest.raises(ChError) as exc:
            apple.settings_from("app", raw, "ios-arm64")
        assert exc.value.code == "CH8006" and fragment in str(exc.value)


def test_info_plist_is_a_valid_plist_with_the_essentials():
    app = apple.settings_from("app", {"bundle_id": "com.example.app", "name": "My App", "version": "2.1", "build": "7",
                                      "orientations": ["portrait", "landscape-left"],
                                      "plist": {"NSCameraUsageDescription": "Scanning"}}, "ios-arm64")
    plist = plistlib.loads(apple.info_plist(app, "ios-arm64"))
    assert plist["CFBundleIdentifier"] == "com.example.app" and plist["CFBundleExecutable"] == "app"
    assert plist["CFBundleShortVersionString"] == "2.1" and plist["CFBundleVersion"] == "7"
    assert plist["UISupportedInterfaceOrientations"] == ["UIInterfaceOrientationPortrait", "UIInterfaceOrientationLandscapeLeft"]
    assert plist["NSCameraUsageDescription"] == "Scanning" and plist["UIRequiredDeviceCapabilities"] == ["arm64"]
    assert plist["CFBundleSupportedPlatforms"] == ["iPhoneOS"]
    sim = plistlib.loads(apple.info_plist(apple.settings_from("app", {"bundle_id": "a.b"}, "ios-sim-arm64"), "ios-sim-arm64"))
    assert sim["CFBundleSupportedPlatforms"] == ["iPhoneSimulator"] and "UIRequiredDeviceCapabilities" not in sim
    vision = plistlib.loads(apple.info_plist(apple.settings_from("app", {"bundle_id": "a.b"}, "visionos-arm64"), "visionos-arm64"))
    assert vision["CFBundleSupportedPlatforms"] == ["XROS"] and vision["UIDeviceFamily"] == [7]


def test_bundle_layout_and_ipa(tmp_path):
    exe = tmp_path / "app"
    exe.write_bytes(b"macho")
    (tmp_path / "res").mkdir()
    (tmp_path / "res" / "logo.png").write_bytes(b"png")
    (tmp_path / "prof.mobileprovision").write_bytes(b"profile")
    app = apple.settings_from("app", {"bundle_id": "com.example.app", "resources": "res",
                                      "provisioning_profile": "prof.mobileprovision"}, "ios-arm64")
    bundle = apple.build_bundle(app, "ios-arm64", exe, tmp_path / "dist", tmp_path)
    assert bundle.name == "app.app"
    assert sorted(p.name for p in bundle.iterdir()) == ["Info.plist", "PkgInfo", "app", "embedded.mobileprovision", "logo.png"]
    assert (bundle / "PkgInfo").read_text() == "APPL????"
    again = apple.build_bundle(app, "ios-arm64", exe, tmp_path / "dist", tmp_path)          # rebuilt from scratch
    assert again == bundle
    ipa = apple.make_ipa(bundle, tmp_path / "dist" / "app.ipa")
    with zipfile.ZipFile(ipa) as zf:
        assert "Payload/app.app/Info.plist" in zf.namelist() and "Payload/app.app/app" in zf.namelist()
    missing = apple.settings_from("app", {"bundle_id": "a.b", "resources": "nope"}, "ios-arm64")
    with pytest.raises(ChError):
        apple.build_bundle(missing, "ios-arm64", exe, tmp_path / "d2", tmp_path)


def test_signing_and_installation_commands():
    sim = apple.settings_from("app", {"bundle_id": "a.b", "entitlements": "app.entitlements"}, "ios-sim-arm64")
    bundle = Path("/b/app.app")
    assert apple.codesign_argv(bundle, sim, Path("/w")) == [
        "codesign", "--force", "--sign", "-", "--timestamp=none", "--entitlements", str(Path("/w/app.entitlements")),
        str(bundle)]
    device = apple.settings_from("app", {"bundle_id": "a.b"}, "ios-arm64")
    with pytest.raises(ChError) as exc:
        apple.codesign_argv(Path("/b/app.app"), device, Path("/w"))
    assert "identity" in str(exc.value)
    signed = apple.settings_from("app", {"bundle_id": "a.b", "identity": "Apple Development: Me (ABC)"}, "ios-arm64")
    assert apple.codesign_argv(Path("/b/app.app"), signed, Path("/w"))[3] == "Apple Development: Me (ABC)"
    assert apple.simctl_install_argv(bundle) == ["xcrun", "simctl", "install", "booted", str(bundle)]
    assert apple.simctl_launch_argv("a.b", "UDID") == ["xcrun", "simctl", "launch", "UDID", "a.b"]
    assert apple.device_install_argv(Path("/b/app.app"), "D1")[:5] == ["xcrun", "devicectl", "device", "install", "app"]
    assert apple.device_launch_argv("a.b", "D1")[-1] == "a.b"


def test_only_a_mobile_app_becomes_a_bundle(tmp_path):
    import argparse

    from charpente.commands import _apple

    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="tool", kind=Kind.EXECUTABLE, location=tmp_path))
    with pytest.raises(ChError) as exc:
        _apple.build_app(argparse.Namespace(platform="ios-arm64"), ws, ws.targets["tool"])
    assert "MOBILE_APP" in str(exc.value)
    ws.add_target(Target(name="app", kind=Kind.MOBILE_APP, location=tmp_path))
    with pytest.raises(ChError) as exc:
        _apple.build_app(argparse.Namespace(platform="linux-x64"), ws, ws.targets["app"])
    assert "Apple platform" in str(exc.value)


# ------------------------------------------------------------------ Android XR profiles
def _manifest(xr):
    import xml.etree.ElementTree as ET

    return ET.fromstring(android.manifest_xml(android.AppSettings(package="a.b", label="A", library="x", xr=xr)))


NS = "{http://schemas.android.com/apk/res/android}"


def test_a_plain_app_has_no_headset_declarations():
    root = _manifest("")
    assert not [f for f in root.findall("uses-feature")] and root.find("queries") is None
    assert "IMMERSIVE_HMD" not in android.manifest_xml(android.AppSettings(package="a.b", label="A"))


def test_openxr_profile_declares_headtracking_permissions_and_runtime_brokers():
    root = _manifest("openxr")
    assert root.find("uses-feature").get(NS + "name") == "android.hardware.vr.headtracking"
    perms = [p.get(NS + "name") for p in root.findall("uses-permission")]
    assert "org.khronos.openxr.permission.OPENXR" in perms and "org.khronos.openxr.permission.OPENXR_SYSTEM" in perms
    assert len(root.find("queries").findall("provider")) == 2
    categories = [c.get(NS + "name") for c in root.iter("category")]
    assert "org.khronos.openxr.intent.category.IMMERSIVE_HMD" in categories and "com.oculus.intent.category.VR" not in categories


def test_quest_and_pico_add_their_vendor_declarations():
    quest = _manifest("quest")
    assert [m.get(NS + "name") for m in quest.find("application").findall("meta-data")] == ["com.oculus.supportedDevices"]
    assert "com.oculus.intent.category.VR" in [c.get(NS + "name") for c in quest.iter("category")]
    pico = _manifest("pico")
    assert [m.get(NS + "name") for m in pico.find("application").findall("meta-data")] == ["pvr.app.type"]


def test_xr_setting_is_validated_and_xr_apps_build_like_mobile_apps(tmp_path):
    with pytest.raises(ChError):
        android.settings_from("a", {"package": "a.b", "xr": "vive"}, debuggable=False)
    assert android.settings_from("a", {"package": "a.b", "xr": "quest"}, debuggable=False).xr == "quest"
    ndk = tmp_path / "ndk"
    (ndk / "toolchains" / "llvm" / "prebuilt").mkdir(parents=True)
    tc = cross.specialise(android.ndk_toolchain(ndk, "win32"), platforms.get("android-arm64"))
    (tmp_path / "a.cpp").write_text("x")
    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="xr", kind=Kind.XR_APP, source_patterns=["*.cpp"], location=tmp_path))
    plan = plan_workspace(ws, tc, OS.ANDROID)
    assert not plan.errors and str(plan.outputs["xr"]).endswith("libxr.so")
