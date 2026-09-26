# Platforms and cross-compilation

A **platform** is `os-arch`: `windows-x64`, `linux-arm64`, `wasm32-wasi`... `charpente platforms`
lists them all. Building for one:

```
charpente toolchain install zig          # once; no admin rights, nothing added to PATH
charpente build --platform linux-arm64
charpente run   --platform wasm32-wasi --target app
```

Without `--platform` nothing changes: the first detected native toolchain builds for this machine,
exactly as before.

## Support tiers

| Tier | Meaning |
|---|---|
| **1** | Built **and tested** in CI at every commit; official packages; blocks a release when it fails. |
| **2** | The build is verified (cross-compiled or under an emulator); running on real hardware is occasional. |
| **3** | Supported through a module; should compile; no CI guarantee. Charpente warns when you use it. |

The tier describes what the *project* checks, not what your machine can do: `charpente platforms`
also says whether your machine can build each platform right now.

## What is verified (on the development machine, Windows 10 x64)

| Platform | Toolchain | Verified |
|---|---|---|
| windows-x64 | MinGW GCC | build + run |
| linux-x64, linux-arm64, linux-riscv64 | zig 0.16.0 | build; ELF machine type checked (62 / 183 / 243). **Not executed.** |
| windows-arm64 | zig | build; PE machine type 0xAA64. **Not executed.** |
| macos-x64, macos-arm64 | zig | build; Mach-O cpu type checked. **Not executed** (no Apple SDK is involved: no frameworks) |
| freebsd-x64 | zig | build; ELF x86-64. **Not executed**; OS-ABI byte is left generic by zig |
| wasm32-wasi | zig | build **and run** (through Node's WASI: `hello from wasi`) |
| wasm32-emscripten | emsdk 6.0.10 | build **and run** under Node; `.js` + `.wasm` both restored from the cache |
| assembly (`.S`) | zig, MinGW | build, header dependency tracking, run natively |
| android-x64 | NDK 28.2 | build, signed APK, **installed and launched on an x86_64 emulator** (API 30), the app's log line read back |
| android-arm64 | NDK 28.2 | build and APK (ELF machine 183, `zipalign -P 16` verified). **Not run**: no arm64 device or emulator here |

The Linux and macOS CI jobs run the same builds natively; until those run on real runners, their
results are not claimed here. Android is described in [android.md](android.md); HarmonyOS, iOS and embedded targets are Phases P4c-P4d.

## How it works

- `--platform` picks a toolchain that *declares* it can target the platform (`Toolchain.targets`)
  and **specialises** it: for zig, `zig c++ -target aarch64-linux-gnu`. If none is installed the
  error (CH8002) says what to install; nothing falls back silently to a native build.
- Each platform has its own build directory and its own action records, so switching between
  platforms rebuilds nothing, and the content cache is shared (identical inputs and command line
  are compiled once).
- Overlays (`t.on_platform("linux-arm64")`) are resolved for the **target** platform.
- Output names follow the target OS: `.exe` (Windows), `.wasm` (WASI), `.js` + `.wasm` (Emscripten),
  `lib*.so` / `*.dylib` / `*.dll`. WebAssembly has no shared libraries (CH3007).
- `charpente run --platform ...` runs the program directly when the machine can (same OS and CPU,
  or x64 on an arm64 Windows/macOS machine), through `wasmtime` or Node 20+ for WASI, Node for
  Emscripten output, and otherwise refuses (CH8004) instead of failing obscurely.
- `charpente package --platform ...` produces a zip; installers are built on their own platform.

## Languages

C, C++, assembly (`.s`, `.S`) and Objective-C/C++ (`.m`, `.mm`) sources are compiled through the
GNU-style driver, which picks the language from the suffix. MSVC-style toolchains refuse them
(CH3007). Objective-C needs a toolchain that ships the Objective-C runtime headers (Apple's).
The zig and MinGW paths are verified for assembly; Objective-C is unit-tested only here.

## Limits (honest)

- Cross-compiled binaries are not executed here except WebAssembly. Their correctness beyond the
  binary format relies on zig/clang.
- `linux-*` targets use glibc's ABI as bundled by zig (`-gnu`); musl (`-musl`) is available as a
  triple but there is no option to select it yet.
- macOS targets link against zig's bundled libSystem stubs: enough for the C/C++ standard
  library, not for Apple frameworks (needs Xcode on a Mac).
- C++20 modules and shader compilation are not part of this phase.
- Windows MSVC cross-arch builds (x64 host to arm64 target) are not implemented; zig covers them.
