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
