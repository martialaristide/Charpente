# Kits

A **kit** is a tested selection of open-source libraries (permissive licenses), each packaged as an ordinary Charpente recipe
(checksummed source, license, purl). A kit adds no new mechanism: `ws.kit("kit-core")` requires all its packages and
`t.uses("kit-core")` uses all of them. What sets a kit apart is the curation and the **statement of what was verified** in its file.

```
charpente kit list
charpente kit show kit-embedded         # members, licenses, what was and was not verified
charpente kit add kit-core              # inserts ws.kit("kit-core") into the workspace file
charpente pkg install                   # downloads and pins the sources (charpente.lock)
```

```python
with Workspace("app") as ws:
    ws.kit("kit-core")
    with Target("app") as t:
        t.kind(Kind.EXECUTABLE)
        t.sources(["src/*.cpp"])
        t.uses("kit-core")              # fmt, spdlog, nlohmann_json, simdjson, CLI11, doctest
```

A project can define its own kits in `.charpente/kits/NAME.toml` (`[kit] name = "kit-mine"`, `requires = [...]`, optional `uses`).

## The kits

| Kit | Members | Verified here (Windows/MinGW unless said) |
|---|---|---|
| **kit-core** | fmt, spdlog, nlohmann_json, simdjson, CLI11, doctest | all built and used by one program |
| **kit-app** | imgui (core), stb; GLFW + ImGui backends via `imgui-glfw-opengl3` | a real OpenGL window rendered ImGui frames |
| **kit-graphics** | vulkan-headers, volk, vma, glm, meshoptimizer, cgltf | compiled and linked; a Vulkan program listed the Intel GPU |
| **kit-xr** | openxr-headers | included and compiled; runtime probing in the `vr-openxr` template |
| **kit-game** | entt, miniaudio, tracy | built and linked; no audio device or profiler used |
| **kit-net** | asio (standalone), websocketpp | headers compiled, an `io_context` created; no connection made |
| **kit-embedded** | tinylibc, printf, cmsis, freertos | FreeRTOS + printf + tinylibc linked for Cortex-M3 with zig |
| **kit-mobile** | charpente-mobile | desktop; **Android: an APK ran on an API 30 emulator** (lifecycle, logcat, asset from the APK); HarmonyOS: compiles and links with the real SDK |
| **kit-android** / **kit-ohos** | charpente-mobile | as kit-mobile |

Each kit file's `verified` / `unverified` / `notes` say more; `charpente kit show` prints them. Notably **not** packaged: SDL3,
nativefiledialog-extended, shaderc, the OpenXR loader/Monado, Jolt Physics, libcurl and TLS, hand-tracking helpers, a JNI helper layer.
Their build needs system libraries or tooling a source recipe cannot supply; they are listed in `docs/idees.md`.

## Packages outside a kit

`glfw` (Windows verified; the Linux/X11 and macOS/Cocoa source lists follow GLFW's CMake files and were **not** built), `imgui-glfw-opengl3`,
`pybind11`, `openxr-headers`, `cmsis`. See `charpente pkg search`.

## `charpente-mobile` and `tinylibc`: kits written for Charpente

These two ship **inside** Charpente (`charpente/kit_sources/`) instead of being downloaded. Their recipes use `url = "charpente://NAME"` and
`sha256` = the digest of the folder's content, so `charpente.lock` pins them exactly like a downloaded archive and a modified copy is
refused (CH6002). After editing them, run `python tools/sync_kit_digests.py` (a test fails if you forget). Line endings are normalised in
the digest so a Windows checkout matches the wheel.

- **tinylibc**: `string.h`, `stdlib.h` (no allocator), `assert.h` for toolchains with no C library (zig's freestanding targets); use
  newlib with `arm-none-eabi-gcc`.
- **charpente-mobile**: `#include <charpente/mobile.hpp>`: lifecycle events, logging, `data_dir()`, `read_asset()`. Backends: desktop
  (stderr), Android (logcat, `ANativeActivity` assets/files; `android_attach`, `android_command`), HarmonyOS (hilog, rawfile;
  `harmony_attach`), iOS (NSLog, bundle; **written without a Mac**). There is no sensors or permissions API yet.

## Tuning a package for one workspace: `ws.package_settings`

Some packages need something from *your* project: FreeRTOS needs your `FreeRTOSConfig.h` on its include path, and needs `tinylibc` under
zig.

```python
ws.package_settings("freertos", include_dirs=["config"], uses=["tinylibc"])
```

Keys: `include_dirs` (relative to the workspace), `defines`, `compile_flags`, `uses`, `link_libraries`. The recipe and the lock file are untouched;
settings for a package the workspace does not use are an error (CH6017).

## Limits (honest)

- Sources are pinned by SHA-256 but were **verified only on Windows/MinGW** (plus zig/NDK/OpenHarmony where the table says so). A recipe listing
  sources per platform (GLFW) is only as good as the platforms it was built for.
- FreeRTOS's Cortex-M4F/M7 ports use GCC-syntax assembly that zig's clang assembler rejects: use `arm-none-eabi-gcc` for them.
- Recipes cannot run code (no generators, no autotools): a library that needs one is out of scope (or a job for a module).
- There is no shared binary cache for these packages yet (compiled once per machine, cached by content).
