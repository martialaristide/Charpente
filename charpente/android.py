"""Android: finding the SDK/NDK, the NDK as a toolchain, and building an APK without Gradle.

A native Android app (`Kind.MOBILE_APP`) is a shared library loaded by Android's `NativeActivity`.
Building it needs only the NDK's clang; packaging it as an APK needs three tools from the SDK's
build-tools (`aapt2`, `zipalign`, `apksigner`) and the platform's `android.jar`. Every step is an
argv list run through the process layer -- never a shell.

Nothing here downloads: `charpente toolchain install ndk` (see toolchain_install.py) does that,
after the Android SDK license has been accepted. An SDK you already have (Android Studio, or
`ANDROID_HOME`) is used as it is.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from xml.sax.saxutils import quoteattr

from .core import process
from .errors import ChError
from .toolchains import Toolchain, toolchains_dir

DEFAULT_API = 24
DEFAULT_TARGET_SDK = 34

#: platform name -> (Android ABI directory name, clang target triple without the API level)
ABIS: Dict[str, Tuple[str, str]] = {
    "android-arm64": ("arm64-v8a", "aarch64-linux-android"),
    "android-arm": ("armeabi-v7a", "armv7a-linux-androideabi"),
    "android-x64": ("x86_64", "x86_64-linux-android"),
}

_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")


# ------------------------------------------------------------------ locating things
def _numeric(text: str) -> Tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text))


def sdk_roots(env: Mapping[str, str], home: Path, platform_name: str = sys.platform) -> List[Path]:
    """Places an Android SDK may be, most specific first."""
    roots: List[Path] = []
    for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if env.get(name):
            roots.append(Path(env[name]))
    if platform_name == "win32" and env.get("LOCALAPPDATA"):
        roots.append(Path(env["LOCALAPPDATA"]) / "Android" / "Sdk")
    elif platform_name == "darwin":
        roots.append(home / "Library" / "Android" / "sdk")
    else:
        roots.append(home / "Android" / "Sdk")
    roots.append(toolchains_dir() / "android-sdk")          # what `charpente toolchain install` maintains
    return roots


def host_tag(platform_name: str = sys.platform) -> str:
    """The NDK's name for this host (`windows-x86_64`, `linux-x86_64`, `darwin-x86_64`)."""
    return {"win32": "windows-x86_64", "darwin": "darwin-x86_64"}.get(platform_name, "linux-x86_64")


@dataclass(frozen=True)
class Sdk:
    root: Path
    ndk: Optional[Path] = None
    build_tools: Optional[Path] = None
    android_jar: Optional[Path] = None
    platform_tools: Optional[Path] = None

    def tool(self, name: str) -> Optional[Path]:
        """An executable of the build-tools or platform-tools, whatever the host's suffix."""
        folders = [f for f in (self.build_tools, self.platform_tools) if f is not None]
        for folder in folders:
            for suffix in (".exe", ".bat", ""):
                candidate = folder / f"{name}{suffix}"
                if candidate.is_file():
                    return candidate
        return None


def _newest_dir(parent: Path, must_have: Callable[[Path], bool] = lambda p: True) -> Optional[Path]:
    if not parent.is_dir():
        return None
    candidates = [d for d in parent.iterdir() if d.is_dir() and must_have(d) and _numeric(d.name)]
    return max(candidates, key=lambda d: _numeric(d.name)) if candidates else None


def _has_ndk(path: Path) -> bool:
    return (path / "toolchains" / "llvm" / "prebuilt").is_dir()


def _android_jar(sdk_root: Path, api: Optional[int]) -> Optional[Path]:
    platforms = sdk_root / "platforms"
    if not platforms.is_dir():
        return None
    if api is not None and (platforms / f"android-{api}" / "android.jar").is_file():
        return platforms / f"android-{api}" / "android.jar"
    best = _newest_dir(platforms, lambda p: (p / "android.jar").is_file())
    return best / "android.jar" if best else None


def find_sdk(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
             api: Optional[int] = None) -> Optional[Sdk]:
    """The first Android SDK found (with an NDK from `ANDROID_NDK_HOME`/`ANDROID_NDK_ROOT` when set,
    else the newest one in `<sdk>/ndk`). `api` picks the platform jar when several are installed."""
    env = os.environ if env is None else env
    home = home or Path.home()
    explicit_ndk: Optional[Path] = None
    for name in ("ANDROID_NDK_HOME", "ANDROID_NDK_ROOT", "ANDROID_NDK"):
        if env.get(name) and _has_ndk(Path(env[name])):
            explicit_ndk = Path(env[name])
            break
    for root in sdk_roots(env, home):
        if not root.is_dir():
            continue
        ndk = explicit_ndk or _newest_dir(root / "ndk", _has_ndk)
        build_tools = _newest_dir(root / "build-tools", lambda p: any(p.glob("aapt2*")))
        platform_tools = root / "platform-tools" if (root / "platform-tools").is_dir() else None
        if ndk or build_tools or platform_tools:
            return Sdk(root=root, ndk=ndk, build_tools=build_tools, android_jar=_android_jar(root, api),
                       platform_tools=platform_tools)
    if explicit_ndk:
        return Sdk(root=explicit_ndk.parent, ndk=explicit_ndk)
    return None


# ------------------------------------------------------------------ the NDK as a toolchain
def ndk_toolchain(ndk: Path, platform_name: str = sys.platform) -> Toolchain:
    """The NDK's LLVM as a cross-only toolchain; `cross.specialise` adds the target and API level."""
    bin_dir = ndk / "toolchains" / "llvm" / "prebuilt" / host_tag(platform_name) / "bin"
    suffix = ".exe" if platform_name == "win32" else ""
    clang, clangxx, ar = bin_dir / f"clang{suffix}", bin_dir / f"clang++{suffix}", bin_dir / f"llvm-ar{suffix}"
    return Toolchain(name="ndk", c_compiler=str(clang), cxx_compiler=str(clangxx), archiver=str(ar),
                     linker=str(clangxx), targets=tuple(ABIS), cross_only=True,
                     extras=(("ndk_root", str(ndk)),))


def specialise_ndk(toolchain: Toolchain, platform_name: str, api: int = DEFAULT_API) -> Toolchain:
    """`clang --target=aarch64-linux-android24`: the API level is the minimum Android version the code
    may assume, and must not be lower than the manifest's minSdkVersion."""
    abi, triple = ABIS[platform_name]
    flag = (f"--target={triple}{api}",)
    extras = tuple(toolchain.extras) + (("api", str(api)), ("abi", abi))
    return replace(toolchain, c_args=flag, cxx_args=flag, ld_args=flag, target=platform_name, extras=extras)


def native_app_glue_dir(toolchain: Toolchain) -> Optional[Path]:
    """The NDK's `android_native_app_glue` sources (the helper NativeActivity apps build with)."""
    root = dict(toolchain.extras).get("ndk_root")
    if not root:
        return None
    glue = Path(root) / "sources" / "android" / "native_app_glue"
    return glue if (glue / "android_native_app_glue.c").is_file() else None


# ------------------------------------------------------------------ manifest
@dataclass(frozen=True)
class AppSettings:
    package: str
    label: str
    min_sdk: int = DEFAULT_API
    target_sdk: int = DEFAULT_TARGET_SDK
    version_code: int = 1
    version_name: str = "1.0"
    library: str = ""                     # `libNAME.so` without lib/.so
    permissions: Tuple[str, ...] = ()
    debuggable: bool = False
    gles_version: str = ""                # "0x00030000" for OpenGL ES 3.0
    orientation: str = ""
    assets: str = ""
    resources: str = ""
    #: "static" (default: libc++ linked into the app's library) or "shared" (libc++_shared.so shipped in the APK).
    stl: str = "static"


def settings_from(target_name: str, raw: Mapping[str, Any], *, debuggable: bool) -> AppSettings:
    """Validate a target's `platform_settings("android", ...)`. Bad values are errors, not guesses."""
    known = {"package", "label", "min_sdk", "target_sdk", "version_code", "version_name", "permissions",
             "gles_version", "orientation", "assets", "resources", "native_app_glue", "debuggable", "stl"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ChError("CH8006", platform="android", detail=f"unknown setting(s) {', '.join(unknown)} "
                                                          f"(known: {', '.join(sorted(known))})")
    package = str(raw.get("package", ""))
    if not package:
        raise ChError("CH8006", platform="android",
                      detail=f"target {target_name!r} needs android(package=\"com.example.app\")")
    if not _PACKAGE.match(package):
        raise ChError("CH8006", platform="android", detail=f"{package!r} is not a valid application id")
    for key in ("min_sdk", "target_sdk", "version_code"):
        if key in raw and (not isinstance(raw[key], int) or isinstance(raw[key], bool) or raw[key] < 1):
            raise ChError("CH8006", platform="android", detail=f"{key} must be a positive integer")
    orientation = str(raw.get("orientation", ""))
    if orientation and orientation not in ("portrait", "landscape", "sensor", "unspecified", "user"):
        raise ChError("CH8006", platform="android", detail=f"orientation {orientation!r} is not one of "
                                                          "portrait, landscape, sensor, user, unspecified")
    stl = str(raw.get("stl", "static"))
    if stl not in ("static", "shared"):
        raise ChError("CH8006", platform="android", detail=f"stl must be \"static\" or \"shared\", not {stl!r}")
    permissions = raw.get("permissions", ())
    if isinstance(permissions, str):
        permissions = (permissions,)
    for permission in permissions:
        if not re.fullmatch(r"[A-Za-z0-9_.]+", str(permission)):
            raise ChError("CH8006", platform="android", detail=f"invalid permission name {permission!r}")
    return AppSettings(
        package=package, label=str(raw.get("label", target_name)),
        min_sdk=int(raw.get("min_sdk", DEFAULT_API)), target_sdk=int(raw.get("target_sdk", DEFAULT_TARGET_SDK)),
        version_code=int(raw.get("version_code", 1)), version_name=str(raw.get("version_name", "1.0")),
        library=target_name, permissions=tuple(str(p) for p in permissions),
        debuggable=bool(raw.get("debuggable", debuggable)), gles_version=str(raw.get("gles_version", "")),
        orientation=orientation, assets=str(raw.get("assets", "")), resources=str(raw.get("resources", "")),
        stl=stl)


def manifest_xml(app: AppSettings) -> str:
    """AndroidManifest.xml for a `NativeActivity` app whose code is `lib<app.library>.so`."""
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<manifest xmlns:android="http://schemas.android.com/apk/res/android"',
             f'    package={quoteattr(app.package)}',
             f'    android:versionCode="{app.version_code}" android:versionName={quoteattr(app.version_name)}>',
             f'  <uses-sdk android:minSdkVersion="{app.min_sdk}" android:targetSdkVersion="{app.target_sdk}"/>']
    for permission in app.permissions:
        name = permission if "." in permission else f"android.permission.{permission}"
        lines.append(f'  <uses-permission android:name={quoteattr(name)}/>')
    if app.gles_version:
        lines.append(f'  <uses-feature android:glEsVersion="{app.gles_version}" android:required="true"/>')
    lines.append(f'  <application android:label={quoteattr(app.label)} android:hasCode="false"'
                 f' android:debuggable="{"true" if app.debuggable else "false"}">')
    activity = ['    <activity android:name="android.app.NativeActivity"',
                f'        android:label={quoteattr(app.label)} android:exported="true"',
                '        android:configChanges="orientation|keyboardHidden|screenSize|smallestScreenSize"']
    if app.orientation:
        activity[-1] += f' android:screenOrientation="{app.orientation}"'
    activity[-1] += ">"
    lines += activity
    lines += [f'      <meta-data android:name="android.app.lib_name" android:value={quoteattr(app.library)}/>',
              '      <intent-filter>',
              '        <action android:name="android.intent.action.MAIN"/>',
              '        <category android:name="android.intent.category.LAUNCHER"/>',
              '      </intent-filter>',
              '    </activity>',
              '  </application>',
              '</manifest>', '']
    return "\n".join(lines)


# ------------------------------------------------------------------ signing keys
DEBUG_STORE_PASSWORD = "android"          # the Android SDK's published debug key: never for release
DEBUG_KEY_ALIAS = "androiddebugkey"


@dataclass(frozen=True)
class Signing:
    keystore: Path
    alias: str
    #: How the password reaches apksigner: `pass:...` (only for the public debug key) or `env:NAME`.
    store_pass: str
    key_pass: str
    debug: bool


def debug_signing(home: Optional[Path] = None, *, runner: Optional[process.Runner] = None,
                  which: Callable[[str], Optional[str]] = shutil.which, create: bool = True) -> Signing:
    """The standard Android debug key: the SDK's own `~/.android/debug.keystore` if present, else one
    created with `keytool` under Charpente's directory."""
    home = home or Path.home()
    sdk_store = home / ".android" / "debug.keystore"
    from .dsl.trust import config_dir

    own = config_dir() / "android" / "debug.keystore"
    for store in (sdk_store, own):
        if store.is_file():
            return Signing(store, DEBUG_KEY_ALIAS, f"pass:{DEBUG_STORE_PASSWORD}", f"pass:{DEBUG_STORE_PASSWORD}", True)
    if not create:
        raise ChError("CH8007", what="a debug keystore", hint="it is created on the first `package --format apk`")
    keytool = which("keytool")
    if not keytool:
        raise ChError("CH8007", what="keytool (a JDK)", hint="install a JDK (17 or newer) and put it on PATH")
    own.parent.mkdir(parents=True, exist_ok=True)
    result = process.run([keytool, "-genkeypair", "-keystore", str(own), "-storepass", DEBUG_STORE_PASSWORD,
                          "-keypass", DEBUG_STORE_PASSWORD, "-alias", DEBUG_KEY_ALIAS, "-keyalg", "RSA",
                          "-keysize", "2048", "-validity", "10000", "-dname", "CN=Android Debug,O=Android,C=US"],
                         runner=runner, timeout=120)
    if result.returncode != 0:
        raise ChError("CH8008", step="keytool", detail=result.output.strip()[-400:])
    return Signing(own, DEBUG_KEY_ALIAS, f"pass:{DEBUG_STORE_PASSWORD}", f"pass:{DEBUG_STORE_PASSWORD}", True)


def release_signing(keystore: Path, alias: str, env_var: str = "CHARPENTE_KEYSTORE_PASSWORD",
                    env: Optional[Mapping[str, str]] = None) -> Signing:
    """A release key: the password comes from the environment, never from the command line."""
    env = os.environ if env is None else env
    if not keystore.is_file():
        raise ChError("CH8007", what=f"the keystore {keystore}", hint="create one with `keytool -genkeypair`")
    if not env.get(env_var):
        raise ChError("CH8006", platform="android", detail=f"set the keystore password in ${env_var} "
                                                          "(passwords are never taken from the command line)")
    return Signing(keystore, alias, f"env:{env_var}", f"env:{env_var}", False)


# ------------------------------------------------------------------ building the APK
@dataclass(frozen=True)
class ApkStep:
    label: str
    argv: Tuple[str, ...]


def _java_apksigner(sdk: Sdk, which: Callable[[str], Optional[str]]) -> List[str]:
    """`java -jar apksigner.jar` (no batch-file quoting on Windows); the wrapper script as a fallback."""
    java = which("java")
    jar = sdk.build_tools / "lib" / "apksigner.jar" if sdk.build_tools else None
    if java and jar is not None and jar.is_file():
        return [java, "-jar", str(jar)]
    wrapper = sdk.tool("apksigner")
    if wrapper is None:
        raise ChError("CH8007", what="apksigner", hint="install Android SDK build-tools")
    return [str(wrapper)]


def require_tools(sdk: Optional[Sdk]) -> Sdk:
    if sdk is None or sdk.build_tools is None or sdk.tool("aapt2") is None or sdk.tool("zipalign") is None:
        raise ChError("CH8007", what="the Android SDK build-tools (aapt2, zipalign, apksigner)",
                      hint="install them with Android Studio's SDK Manager, or "
                           "`charpente toolchain install android-build-tools --accept-android-license`")
    if sdk.android_jar is None:
        raise ChError("CH8007", what="an Android platform (android.jar)",
                      hint="install one with the SDK Manager, or "
                           "`charpente toolchain install android-platform --accept-android-license`")
    return sdk


def shared_stl(toolchain: Toolchain) -> Optional[Path]:
    """The NDK's `libc++_shared.so` for the toolchain's ABI (shipped in the APK when `stl="shared"`)."""
    extras = dict(toolchain.extras)
    if "ndk_root" not in extras or toolchain.target not in ABIS:
        return None
    triple = ABIS[toolchain.target][1]
    lib = Path(extras["ndk_root"]) / "toolchains" / "llvm" / "prebuilt" / host_tag() / "sysroot" / "usr" / "lib" / triple / "libc++_shared.so"
    return lib if lib.is_file() else None


def apk_steps(sdk: Sdk, app: AppSettings, staging: Path, libs: Mapping[str, Sequence[Path]], signing: Signing,
              output: Path,
              *, which: Callable[[str], Optional[str]] = shutil.which) -> List[ApkStep]:
    """The commands that turn the manifest, the libraries and the resources into a signed APK.

    Returned in order; the library insertion between `aapt2 link` and `zipalign` is a Python step
    (`add_libraries`) because no SDK tool inserts *uncompressed, page-aligned* native libraries."""
    sdk = require_tools(sdk)
    assert sdk.build_tools is not None and sdk.android_jar is not None
    aapt2, zipalign = str(sdk.tool("aapt2")), str(sdk.tool("zipalign"))
    manifest = staging / "AndroidManifest.xml"
    base = staging / "base.apk"
    aligned = staging / "aligned.apk"
    link = [aapt2, "link", "-o", str(base), "-I", str(sdk.android_jar), "--manifest", str(manifest),
            "--min-sdk-version", str(app.min_sdk), "--target-sdk-version", str(app.target_sdk),
            "--version-code", str(app.version_code), "--version-name", app.version_name, "--auto-add-overlay"]
    steps: List[ApkStep] = []
    if app.resources:
        compiled = staging / "resources.zip"
        steps.append(ApkStep("Compiling resources", (aapt2, "compile", "--dir", app.resources, "-o", str(compiled))))
        link += [str(compiled)]
    if app.assets:
        link += ["-A", app.assets]
    steps.append(ApkStep("Linking the manifest and resources", tuple(link)))
    steps.append(ApkStep("Adding native libraries", ("python:add_libraries", str(base),
                                                    *[f"{abi}={path}" for abi, files in sorted(libs.items()) for path in files])))
    page = _numeric(sdk.build_tools.name)[:1] >= (35,)
    steps.append(ApkStep("Aligning", (zipalign, "-f", *(("-P", "16") if page else ("-p",)), "4", str(base), str(aligned))))
    sign = [*_java_apksigner(sdk, which), "sign", "--ks", str(signing.keystore), "--ks-key-alias", signing.alias,
            "--ks-pass", signing.store_pass, "--key-pass", signing.key_pass, "--v4-signing-enabled", "false",
            "--out", str(output), str(aligned)]
    steps.append(ApkStep("Signing", tuple(sign)))
    return steps


def add_libraries(apk: Path, entries: Sequence[str]) -> None:
    """Append `lib/<abi>/<file>` (from `abi=path` entries) to the APK, **stored** (uncompressed): Android
    maps native libraries straight from the file, which requires it (and `zipalign` then aligns them)."""
    with zipfile.ZipFile(apk, "a") as zf:
        for entry in sorted(entries):
            abi, _, path = entry.partition("=")
            info = zipfile.ZipInfo(f"lib/{abi}/{Path(path).name}", date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            zf.writestr(info, Path(path).read_bytes())


def build_apk(sdk: Sdk, app: AppSettings, libs: Mapping[str, Sequence[Path]], signing: Signing, output: Path, staging: Path, *,
              runner: Optional[process.Runner] = None, which: Callable[[str], Optional[str]] = shutil.which,
              say: Callable[[str], None] = lambda text: None) -> Path:
    """Run every step; raises CH8008 naming the step that failed, with the tool's own output."""
    staging.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    (staging / "AndroidManifest.xml").write_text(manifest_xml(app), encoding="utf-8")
    if output.exists():
        output.unlink()
    for step in apk_steps(sdk, app, staging, libs, signing, output, which=which):
        say(step.label)
        if step.argv[0] == "python:add_libraries":
            add_libraries(Path(step.argv[1]), step.argv[2:])
            continue
        result = process.run(list(step.argv), runner=runner, timeout=600)
        if result.returncode != 0:
            raise ChError("CH8008", step=step.label, detail=result.output.strip()[-1200:] or "(no output)")
    return output


def verify_apk(sdk: Sdk, apk: Path, *, runner: Optional[process.Runner] = None,
               which: Callable[[str], Optional[str]] = shutil.which) -> str:
    """`apksigner verify`: returns its report; raises CH8008 if the signature is not valid."""
    argv = [*_java_apksigner(sdk, which), "verify", "--verbose", "--print-certs", str(apk)]
    result = process.run(argv, runner=runner, timeout=120)
    if result.returncode != 0:
        raise ChError("CH8008", step="Verifying the signature", detail=result.output.strip()[-800:])
    return result.output


def badging(sdk: Sdk, apk: Path, *, runner: Optional[process.Runner] = None) -> Dict[str, str]:
    """A few facts `aapt2 dump badging` reports (package, versions, native ABIs)."""
    aapt2 = sdk.tool("aapt2")
    if aapt2 is None:
        raise ChError("CH8007", what="aapt2", hint="install Android SDK build-tools")
    result = process.run([str(aapt2), "dump", "badging", str(apk)], runner=runner, timeout=120)
    if result.returncode != 0:
        raise ChError("CH8008", step="Reading the APK", detail=result.output.strip()[-800:])
    facts: Dict[str, str] = {}
    for line in result.output.splitlines():
        if line.startswith("package:"):
            for key in ("name", "versionCode", "versionName"):
                match = re.search(rf"{key}='([^']*)'", line)
                if match:
                    facts[key] = match.group(1)
        elif line.startswith("native-code:"):
            facts["native-code"] = line.split(":", 1)[1].strip().replace("'", "")
        elif line.startswith("sdkVersion:"):
            facts["minSdk"] = line.split("'")[1]
    return facts


# ------------------------------------------------------------------ adb
def adb_path(sdk: Optional[Sdk], which: Callable[[str], Optional[str]] = shutil.which) -> str:
    found = which("adb") or (str(sdk.tool("adb")) if sdk and sdk.tool("adb") else None)
    if not found:
        raise ChError("CH8007", what="adb (platform-tools)", hint="install the SDK's platform-tools")
    return found


def parse_devices(text: str) -> List[Tuple[str, str]]:
    """`adb devices` output -> [(serial, state)]."""
    devices: List[Tuple[str, str]] = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and not line.startswith("*"):
            devices.append((parts[0], parts[1]))
    return devices


def install_and_launch(adb: str, apk: Path, package: str, *, serial: Optional[str] = None, launch: bool = True,
                       runner: Optional[process.Runner] = None,
                       say: Callable[[str], None] = lambda text: None) -> None:
    """`adb install -r`, then start the app's launcher activity (`monkey` finds it without needing its name)."""
    base = [adb] + (["-s", serial] if serial else [])
    say(f"Installing {apk.name}")
    result = process.run([*base, "install", "-r", str(apk)], runner=runner, timeout=600)
    if result.returncode != 0 or "Failure" in result.output:
        raise ChError("CH8008", step="adb install", detail=result.output.strip()[-800:])
    if launch:
        say(f"Starting {package}")
        result = process.run([*base, "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
                             runner=runner, timeout=120)
        if result.returncode != 0 or "No activities found" in result.output:
            raise ChError("CH8008", step="starting the app", detail=result.output.strip()[-800:])


def select_device(devices: Sequence[Tuple[str, str]], wanted: Optional[str]) -> str:
    ready = [serial for serial, state in devices if state == "device"]
    if wanted:
        if wanted not in ready:
            raise ChError("CH8009", detail=f"{wanted!r} is not connected and ready (ready: {', '.join(ready) or 'none'})")
        return wanted
    if len(ready) == 1:
        return ready[0]
    if not ready:
        raise ChError("CH8009", detail="no device or emulator is connected and ready (start an emulator, or plug in "
                                       "a device with USB debugging on; `adb devices` lists them)")
    raise ChError("CH8009", detail=f"several devices are connected ({', '.join(ready)}): choose one with --device")
