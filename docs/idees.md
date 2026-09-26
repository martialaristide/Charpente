# Ideas and known gaps

Things Charpente does not do yet, in the spirit of "say so rather than pretend". Each is either planned or waiting for someone who has the
hardware, licence or time. Nothing here is promised by the documentation elsewhere.

## Kits and packages

- SDL3, nativefiledialog-extended, shaderc, Jolt Physics, libcurl and TLS libraries, the OpenXR loader and Monado: they need system libraries,
  generators or toolchains a source recipe cannot supply (see docs/kits.md).
- Binary package cache (precompiled packages downloaded per platform/toolchain), vcpkg/Conan/pkg-config/CMake bridges, recipe options, signed recipes.
- Sensors and permissions in `charpente-mobile`; a JNI helper layer for Android; XComponent helpers for HarmonyOS.

## Platforms

- `ar-mobile` (ARCore, AR Engine, ARKit), `jeu-harmonyos`, Android AAB/Gradle/Kotlin, HarmonyOS HAP signing and `hilog` streaming as events, iOS/visionOS
  verified on a real Mac, ESP-IDF and Zephyr delegation, RISC-V microcontrollers, running foreign binaries under QEMU/Wine.
- musl selection, MSVC cross-architecture builds, C++20 modules, shader compilation (`Kind.SHADERS`).

## Workflow

- Branch coverage and HTML reports, MSVC support in the warnings/sanitizer/coverage checks, more release artifacts (installers, AAB/IPA), a token vault via `charpente auth`.

## Engine and interoperability (P9)

- **Remote execution (REAPI) and hybrid local/remote execution**: needs gRPC/protobuf, an executor to test against, and *hermetic* actions (every input declared; today the compiler discovers headers at run time). See ADR 0019.
- **Xcode project generation** (needs a Mac to check); **opening the generated Visual Studio projects in Visual Studio** to verify them.
- **TLS in the shared-cache server** (today: behind a TLS proxy), per-entry expiry, an admin listing, and a load test with many clients.
- **MSVC reproducible builds** (`/Brepro`, `/PATHMAP`), macOS linker determinism, and a verification on Linux and macOS.
- **`charpente import cmake`**: custom commands and generated sources, per-configuration settings, CTest tests; a larger set of real projects.
- **Hot reload**: Linux/macOS verification, state migration helpers, hot reload for mobile apps.
- **`charpente docs`**: a real C++ parser for the built-in extractor, cross references between pages.
- **Devices**: `--device all` on several real phones; HarmonyOS (`hdc`) and iOS devices; multi-device debugging.
- **Resources**: macOS battery and memory probes; Linux verification of the thermal and battery probes.
- **Packaging**: publishing to PyPI (a maintainer decision), Windows/macOS/Linux installers for the CLI, a compiled Studio desktop app.
- **Continuous integration** on Windows, Linux and macOS: the condition for calling anything stable and for a 1.0.

