# Android

Charpente builds native Android apps (C/C++ loaded by `NativeActivity`) without Gradle, and packages, signs,
installs and starts them. Java/Kotlin code, Gradle projects and AARs are **not** handled (see Limits).

## What you need

An Android SDK with an NDK, the build-tools (`aapt2`, `zipalign`, `apksigner`), one platform (`android.jar`)
and, to deploy, platform-tools (`adb`); plus a JDK 17+ (`apksigner` and `keytool` are Java programs).
Charpente looks in `ANDROID_HOME`, `ANDROID_SDK_ROOT`, Android Studio's default folder, then its own
`~/.charpente/toolchains/android-sdk` (`ANDROID_NDK_HOME` selects a specific NDK). `charpente doctor` says
what is found. If you have none: `charpente toolchain install ndk --accept-android-license` (and
`build-tools`, `platform`, `platform-tools`), after reading the license it prints.

## A minimal app

```python
from charpente import *

with Workspace("game") as ws:
    with Target("game") as t:
        t.kind(Kind.MOBILE_APP)
        t.sources(["src/main.cpp"])
        t.platform_settings("android", package="com.example.game", label="My Game",
                            min_sdk=24, native_app_glue=True)
```

```
charpente build   --platform android-arm64        # build/Debug-android-arm64/game/libgame.so
charpente package --format apk --platform android-arm64,android-x64
charpente deploy  --platform android-x64          # install + start on the connected device/emulator
```

## Settings (`platform_settings("android", ...)`)

| Key | Meaning | Default |
|---|---|---|
| `package` | Application id (`com.example.app`). **Required** for an APK | |
| `label` | Name shown by the launcher | target name |
| `min_sdk` / `target_sdk` | minSdkVersion / targetSdkVersion. The highest `min_sdk` of the workspace is also the API level everything is compiled against | 24 / 34 |
| `version_code` / `version_name` | | 1 / "1.0" |
| `permissions` | `["INTERNET", "com.vendor.PERMISSION"]` (short names get `android.permission.`) | none |
| `gles_version` | `"0x00030000"` requires OpenGL ES 3.0 | none |
| `orientation` | portrait, landscape, sensor, user, unspecified | none |
| `native_app_glue` | Compile the NDK's `android_native_app_glue` (as C) and link `android`, `log` | off |
| `stl` | `"static"`: libc++ inside your library; `"shared"`: `libc++_shared.so` added to the APK | static |
| `resources`, `assets` | Folders passed to `aapt2` | none |
| `debuggable` | | true for Debug builds |

Unknown keys, an invalid application id or a non-integer level are errors (CH8006), not guesses.

## How the APK is made

`aapt2 link` (manifest, resources) -> the libraries are appended **stored (uncompressed)** as
`lib/<abi>/lib<name>.so` (Android maps them straight from the file) -> `zipalign -P 16` (16 KB pages, build-tools
35+; `-p` before) -> `apksigner sign` -> `apksigner verify` and, in tests, `aapt2 dump badging`. Every step is an
argument list run without a shell; a failing step is reported with its name and the tool's own output (CH8008).
No `.idsig` (APK Signature Scheme v4) file is produced.

## Verified for real (Windows 10 host, NDK 28.2, build-tools 36.1, JDK 21, x86_64 emulator API 30)

- `android-arm64` and `android-x64` builds; ELF machine types 183 and 62.
- A NativeActivity app built by Charpente was packaged, `zipalign -c -P 16` and `apksigner verify` passed,
  `aapt2 dump badging` reports the right package, SDK levels and native ABIs; it was installed with
  `charpente deploy`, started, and its `android_main` log lines were read from `logcat`. With `stl="shared"` too.
- Real bugs found this way and fixed: the NDK's clang++ links `libc++_shared.so` by default, which crashed the app
  at load (`stl="static"` is now the default); shared objects were built without `-fPIC`.

## Limits (honest)

- **No arm64 run**: the arm64 build and APK are verified structurally, not executed (no arm64 device here).
- **No Java/Kotlin, no Gradle, no AAR, no Android App Bundle (.aab), no Play upload.** `hasCode="false"`: apps
  are pure native. Integrating with a Gradle project is not done.
- No shaders (`glslc`), no `compile_commands` tweaks for the NDK, no multi-library apps with several static libc++.
- The Android SDK component download (`toolchain install ndk`, ...) is tested against a local fake repository
  only: running it for real means accepting Google's license, which was not done on your behalf. The SDK already
  on the development machine (Android Studio) was used for every real verification.
- Release signing: the key and password are yours; Charpente only passes the password through the environment.
