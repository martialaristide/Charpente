"""iOS and visionOS: the Xcode toolchain as a cross compiler, `.app` bundles, code signing, `.ipa`, the simulator.

**This module was written and unit-tested without a Mac.** Nothing here has been run against a real Xcode,
simulator or device; every command it builds is documented Apple tooling (`xcrun`, `clang -target ... -isysroot`,
`codesign`, `simctl`, `devicectl`) and is exercised in tests only through a recording runner. `charpente platforms`
therefore lists these platforms as Tier 2/3: what Charpente can promise is the command lines and the bundle
layout, not that a given Xcode version accepts them.

The Apple SDKs cannot be redistributed, so nothing is downloaded: Xcode must be installed (`xcode-select -p`).
"""
from __future__ import annotations

import plistlib
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .core import process
from .errors import ChError
from .toolchains import Toolchain

#: platform -> (SDK name for `xcrun --sdk`, clang triple with {v} for the minimum OS version, default minimum)
TARGETS: Dict[str, Tuple[str, str, str]] = {
    "ios-arm64": ("iphoneos", "arm64-apple-ios{v}", "13.0"),
    "ios-sim-arm64": ("iphonesimulator", "arm64-apple-ios{v}-simulator", "13.0"),
    "ios-sim-x64": ("iphonesimulator", "x86_64-apple-ios{v}-simulator", "13.0"),
    "visionos-arm64": ("xros", "arm64-apple-xros{v}", "1.0"),
    "visionos-sim-arm64": ("xrsimulator", "arm64-apple-xros{v}-simulator", "1.0"),
}
_VERSION = re.compile(r"^\d+(\.\d+){1,2}$")
_BUNDLE_ID = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")

Runner = Optional[process.Runner]


# ------------------------------------------------------------------ toolchain
def xcode_toolchain(*, runner: Runner = None, which: Callable[[str], Optional[str]] = shutil.which,
                    platform_name: str = sys.platform) -> Optional[Toolchain]:
    """Xcode's clang as a cross-only toolchain, on macOS with Xcode installed (else None)."""
    if platform_name != "darwin":
        return None
    xcrun = which("xcrun")
    if not xcrun:
        return None
    found: Dict[str, str] = {}
    for tool in ("clang", "clang++", "ar"):
        result = process.run([xcrun, "--find", tool], runner=runner, timeout=60)
        if result.returncode != 0 or not result.output.strip():
            return None
        found[tool] = result.output.strip().splitlines()[0]
    return Toolchain(name="xcode", c_compiler=found["clang"], cxx_compiler=found["clang++"], archiver=found["ar"],
                     linker=found["clang++"], targets=tuple(TARGETS), cross_only=True, extras=(("xcrun", xcrun),))


def sdk_path(toolchain: Toolchain, sdk: str, *, runner: Runner = None) -> str:
    xcrun = dict(toolchain.extras).get("xcrun", "xcrun")
    result = process.run([xcrun, "--sdk", sdk, "--show-sdk-path"], runner=runner, timeout=60)
    path = result.output.strip().splitlines()[0] if result.output.strip() else ""
    if result.returncode != 0 or not path:
        raise ChError("CH8007", what=f"the {sdk} SDK", hint="install Xcode (and its command line tools) and run "
                                                            "`xcode-select --install`")
    return path


def specialise_xcode(toolchain: Toolchain, platform_name: str, min_os: Optional[str] = None, *,
                     runner: Runner = None) -> Toolchain:
    """`clang -target arm64-apple-ios13.0 -isysroot <sdk>`; `min_os` is the deployment target."""
    sdk, triple, default = TARGETS[platform_name]
    version = min_os or default
    if not _VERSION.match(version):
        raise ChError("CH8006", platform="ios", detail=f"min_os {version!r} is not a version like 13.0")
    args = ("-target", triple.format(v=version), "-isysroot", sdk_path(toolchain, sdk, runner=runner))
    extras = tuple(toolchain.extras) + (("min_os", version), ("sdk", sdk))
    return replace(toolchain, c_args=args, cxx_args=args, ld_args=args, target=platform_name, extras=extras)


# ------------------------------------------------------------------ settings and the bundle
@dataclass(frozen=True)
class AppSettings:
    bundle_id: str
    name: str
    executable: str
    version: str = "1.0"
    build: str = "1"
    min_os: str = "13.0"
    device_family: Tuple[int, ...] = (1, 2)          # iPhone, iPad (visionOS: 7)
    orientations: Tuple[str, ...] = ()
    frameworks: Tuple[str, ...] = ()
    identity: str = ""                                # code-signing identity ("-" = ad hoc, the simulator's)
    entitlements: str = ""
    provisioning_profile: str = ""
    resources: str = ""
    extra_plist: Tuple[Tuple[str, Any], ...] = ()
    vision: bool = False


_ORIENTATIONS = {"portrait": "UIInterfaceOrientationPortrait", "landscape-left": "UIInterfaceOrientationLandscapeLeft",
                 "landscape-right": "UIInterfaceOrientationLandscapeRight",
                 "upside-down": "UIInterfaceOrientationPortraitUpsideDown"}
_KNOWN = {"bundle_id", "name", "version", "build", "min_os", "device_family", "orientations", "frameworks",
          "identity", "entitlements", "provisioning_profile", "resources", "plist"}


def settings_from(target_name: str, raw: Mapping[str, Any], platform_name: str) -> AppSettings:
    unknown = sorted(set(raw) - _KNOWN)
    if unknown:
        raise ChError("CH8006", platform="ios", detail=f"unknown setting(s) {', '.join(unknown)} "
                                                       f"(known: {', '.join(sorted(_KNOWN))})")
    bundle_id = str(raw.get("bundle_id", ""))
    if not bundle_id:
        raise ChError("CH8006", platform="ios",
                      detail=f"target {target_name!r} needs platform_settings(\"ios\", bundle_id=\"com.example.app\")")
    if not _BUNDLE_ID.match(bundle_id):
        raise ChError("CH8006", platform="ios", detail=f"{bundle_id!r} is not a valid bundle identifier")
    vision = platform_name.startswith("visionos")
    min_os = str(raw.get("min_os", TARGETS[platform_name][2]))
    if not _VERSION.match(min_os):
        raise ChError("CH8006", platform="ios", detail=f"min_os {min_os!r} is not a version like 13.0")
    orientations = tuple(raw.get("orientations", ()))
    for item in orientations:
        if item not in _ORIENTATIONS:
            raise ChError("CH8006", platform="ios", detail=f"orientation {item!r} is not one of {', '.join(_ORIENTATIONS)}")
    family = tuple(int(x) for x in raw.get("device_family", (7,) if vision else (1, 2)))
    if any(x not in (1, 2, 3, 4, 7) for x in family):
        raise ChError("CH8006", platform="ios", detail="device_family entries are 1 (iPhone), 2 (iPad) or 7 (Vision)")
    plist = raw.get("plist", {})
    if not isinstance(plist, Mapping):
        raise ChError("CH8006", platform="ios", detail="plist must be a dictionary of extra Info.plist keys")
    simulator = "sim" in platform_name
    return AppSettings(
        bundle_id=bundle_id, name=str(raw.get("name", target_name)), executable=target_name,
        version=str(raw.get("version", "1.0")), build=str(raw.get("build", "1")), min_os=min_os, device_family=family,
        orientations=orientations, frameworks=tuple(str(f) for f in raw.get("frameworks", ())),
        identity=str(raw.get("identity", "-" if simulator else "")), entitlements=str(raw.get("entitlements", "")),
        provisioning_profile=str(raw.get("provisioning_profile", "")), resources=str(raw.get("resources", "")),
        extra_plist=tuple(sorted(plist.items())), vision=vision)


def info_plist(app: AppSettings, platform_name: str) -> bytes:
    """The bundle's Info.plist (XML), built with `plistlib`."""
    sdk = TARGETS[platform_name][0]
    data: Dict[str, Any] = {
        "CFBundleIdentifier": app.bundle_id, "CFBundleName": app.name, "CFBundleDisplayName": app.name,
        "CFBundleExecutable": app.executable, "CFBundlePackageType": "APPL", "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleVersion": app.build, "CFBundleShortVersionString": app.version, "MinimumOSVersion": app.min_os,
        "UIDeviceFamily": list(app.device_family), "CFBundleSupportedPlatforms": [{
            "iphoneos": "iPhoneOS", "iphonesimulator": "iPhoneSimulator", "xros": "XROS", "xrsimulator": "XRSimulator"}[sdk]],
        "UILaunchScreen": {}, "LSRequiresIPhoneOS": not app.vision,
    }
    if not app.vision and "sim" not in platform_name:
        data["UIRequiredDeviceCapabilities"] = ["arm64"]
    if app.orientations:
        data["UISupportedInterfaceOrientations"] = [_ORIENTATIONS[o] for o in app.orientations]
    data.update(dict(app.extra_plist))
    return plistlib.dumps(data, fmt=plistlib.FMT_XML, sort_keys=True)


def build_bundle(app: AppSettings, platform_name: str, executable: Path, out_dir: Path, workspace_root: Path) -> Path:
    """`<out_dir>/<name>.app` with the executable, Info.plist, PkgInfo, resources and provisioning profile."""
    bundle = out_dir / f"{app.name}.app"
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    shutil.copy2(executable, bundle / app.executable)
    (bundle / "Info.plist").write_bytes(info_plist(app, platform_name))
    (bundle / "PkgInfo").write_text("APPL????", encoding="ascii")
    if app.resources:
        source = workspace_root / app.resources
        if not source.is_dir():
            raise ChError("CH8006", platform="ios", detail=f"resources folder {app.resources!r} does not exist")
        shutil.copytree(source, bundle, dirs_exist_ok=True)
    if app.provisioning_profile:
        profile = workspace_root / app.provisioning_profile
        if not profile.is_file():
            raise ChError("CH8006", platform="ios", detail=f"provisioning profile {app.provisioning_profile!r} not found")
        shutil.copy2(profile, bundle / "embedded.mobileprovision")
    return bundle


# ------------------------------------------------------------------ signing, ipa, simulator, devices
def codesign_argv(bundle: Path, app: AppSettings, workspace_root: Path, *, codesign: str = "codesign") -> List[str]:
    """Ad-hoc (`-`) for the simulator, a real identity for devices; entitlements from the project."""
    if not app.identity:
        raise ChError("CH8006", platform="ios", detail='a device build needs platform_settings("ios", identity="Apple '
                      'Development: Name (TEAMID)") -- see `security find-identity -p codesigning`')
    argv = [codesign, "--force", "--sign", app.identity, "--timestamp=none"]
    if app.entitlements:
        argv += ["--entitlements", str(workspace_root / app.entitlements)]
    return [*argv, str(bundle)]


def make_ipa(bundle: Path, ipa: Path) -> Path:
    """`Payload/<App>.app/...` in a zip -- the format both TestFlight uploads and device installs use."""
    ipa.parent.mkdir(parents=True, exist_ok=True)
    if ipa.exists():
        ipa.unlink()
    with zipfile.ZipFile(ipa, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                zf.write(path, f"Payload/{bundle.name}/{path.relative_to(bundle).as_posix()}")
    return ipa


def simctl_install_argv(bundle: Path, device: str = "booted", xcrun: str = "xcrun") -> List[str]:
    return [xcrun, "simctl", "install", device, str(bundle)]


def simctl_launch_argv(bundle_id: str, device: str = "booted", xcrun: str = "xcrun") -> List[str]:
    return [xcrun, "simctl", "launch", device, bundle_id]


def device_install_argv(bundle: Path, device: str, xcrun: str = "xcrun") -> List[str]:
    return [xcrun, "devicectl", "device", "install", "app", "--device", device, str(bundle)]


def device_launch_argv(bundle_id: str, device: str, xcrun: str = "xcrun") -> List[str]:
    return [xcrun, "devicectl", "device", "process", "launch", "--device", device, bundle_id]


def link_frameworks(frameworks: Sequence[str]) -> List[str]:
    args: List[str] = []
    for framework in frameworks:
        if not re.fullmatch(r"[A-Za-z0-9_]+", framework):
            raise ChError("CH8006", platform="ios", detail=f"invalid framework name {framework!r}")
        args += ["-framework", framework]
    return args
