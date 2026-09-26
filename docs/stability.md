# Stability: what each part of Charpente can be relied on for

Charpente is at **version 0.13 (alpha)**. Nothing is called *stable*, and the version will stay `0.x` until every announced platform has continuous integration behind it: a CI workflow exists (`.github/workflows/tests.yml`: Windows, Linux, macOS, Python 3.9 and 3.12) but it has **never run on this work**, which was not pushed. Everything
below was verified by hand on **one machine (Windows 10 x64, MinGW-w64 GCC, plus the toolchains named in each row)**. Nothing was run on Linux or macOS, and only Python 3.12 was used (the code declares 3.9+ and a syntax check for 3.9 passes, but no 3.9 interpreter was available).

## The tiers used in this page

| Tier | Meaning |
|---|---|
| **Verified** | Automated tests exist and pass, *and* the feature was exercised for real (a real compiler, a real tool, a real device or browser), on the machine above. |
| **Tested** | Automated tests pass, but a real counterpart was not involved (a stand-in tool, a canned answer, a generated file that no real program opened). |
| **Experimental** | Works in the situations described, may change shape without notice, known gaps listed. |
| **Skeleton** | Files exist but were never built or run. |
| **Not done** | Announced, not implemented. Said so here rather than hidden. |

The *platform* support tiers (1, 2, 3) are a separate thing and are described in [platforms.md](platforms.md).

## Feature by feature

| Area | Feature | Tier | Verified with / gap |
|---|---|---|---|
| Engine | Build, exact incremental rebuilds, content cache, event stream, `why`, `history`, `replay` | Verified | MinGW GCC; zig for cross builds |
| Engine | Reproducible builds, `verify-reproducible` | Verified | MinGW: two folders, byte-identical. GNU-style toolchains only; **MSVC refused** (`/Brepro` not driven) |
| Engine | Budgets (size, build time) | Verified | real builds |
| Engine | Resource-aware jobs, eco mode, resume after interruption | Verified on Windows | probes read the real machine; **Linux thermal/battery probes and macOS never run** |
| Engine | Shared cache (`cache serve`, `CHARPENTE_REMOTE_CACHE`) | Verified over plain HTTP on loopback | **no TLS in the server**; `https://` clients and TLS proxies not tried; no load test |
| Engine | Remote *execution* (REAPI), hybrid local/remote execution | **Not done** | see [ADR 0019](adr/0019-reproductibilite-cache-partage.md) |
| Interop | `import cmake` | Verified on one small project | CMake 3.22.1; big projects unknown |
| Interop | `generate compile-commands`, `ninja`, `cmake` | Verified | clangd 22, Ninja 1.10.2, CMake 3.22.1 |
| Interop | `generate vs` | **Tested** | never opened in Visual Studio or built with MSBuild |
| Interop | `generate xcode` | **Not done** | needs a Mac to check |
| Dev loop | `charpente dev`, hot reload (`charpente_hot.h`) | Experimental, verified on Windows | real host process swapped plugins 3 times; Linux/macOS `dlopen` paths unverified |
| Dev loop | `charpente docs` | Tested | built-in extractor is a text scanner, not a C++ parser; Doxygen path only generates its config and errors cleanly when Doxygen is missing |
| Devices | `deploy` (one device) | Verified | real x86_64 emulator (API 30) |
| Devices | `deploy --device all`, merged logs | Verified with one real emulator; **Tested** with several | one real x86_64 emulator end to end; several devices are simulated (real APK, fake `adb`); no real arm64 device |
| Platforms | Windows/Linux/macOS/wasm/Android/HarmonyOS/firmware builds | See [platforms.md](platforms.md) | most cross builds are built, not executed |
| Studio | `charpente studio` (browser), LSP (clangd), DAP (gdb) | Verified | headless Edge, clangd 22, gdb 17.2; **only Edge**; lldb-dap never run |
| Studio | Desktop app (`studio-desktop/`, Tauri) | **Skeleton** | never compiled; no installer exists |
| Studio | VS Code extension | Tested | 26 automated tests against a fake `vscode`; never loaded in a live VS Code; not published |
| AI | `fix`, `ai tests`, `ai migrate` | Tested | scripted fake provider; **no real provider was ever called**. Off unless you ask |
| Kits | Recipes and templates | Verified | each recipe compiled; see [kits.md](kits.md) |
| Packaging | PyPI package | Built, `twine check` passes | **never uploaded** |
| Setup | `charpente setup`, `self uninstall` | Verified on Windows | junction/symlink handling checked on Windows |
| Console style | Banner and styled build lines ([console.md](console.md)) | Verified in real `cmd.exe` and PowerShell 5.1 windows | Windows Terminal, PowerShell 7, Linux, macOS not run; plain/jsonl output pinned by tests |
| Console | `charpente` alone / `charpente menu` ([console.md](console.md)) | Verified on Windows (ConPTY) | arrow-key input in a real Windows pseudo-console; the POSIX key reader was never run on Linux/macOS |

## What "not stable" means for you

* Command names and documented options are unlikely to change but may; the JSON event schema (`docs/events/`) is versioned (`schema_version`) and only grows.
* `.charpente` files written for v0.1.0 still load: backward compatibility is a rule of the project and is tested.
* Error codes `CHxxxx` are never reused for a different meaning; `charpente explain CHxxxx` describes them in English and French.
* Experimental features are marked in their own page and in `--help`.

## What is needed to reach 1.0

The CI workflow run, green, on Windows, Linux and macOS with Python 3.9 and 3.12 (push the branch and read the result); the "not executed" rows of [platforms.md](platforms.md) executed; the *Tested* rows above turned into *Verified*;
a real run of Studio in Chrome and Firefox as well as Edge; and someone other than the author using it on projects that are not the ones in this repository.
