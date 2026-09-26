# Changelog

## Unreleased -- the console interface, and Ctrl+C

- **Fixed: Ctrl+C did not stop `charpente studio` on Windows** (nor `serve --ws`, nor `deploy --logs`). They waited on a single `Event.wait()`, which Windows cannot interrupt; they now
  wait in short slices (`wait_until_interrupted`). `serve --ws` also no longer ends with a fatal "could not acquire lock ... at interpreter shutdown" error after Ctrl+C. Checked by delivering a
  real Ctrl+C console event to the real commands (Studio with and without a browser connected, `serve --ws`, `cache serve`, `dev`) and by `tests/test_ctrl_c.py`, which fails on the old code.
  Not checked on Linux or macOS (where `Event.wait()` is interruptible anyway).

- **`charpente` alone in a terminal opens a guided menu** (`charpente menu` opens it explicitly): create a project from a template, open one, build, run, test, rebuild on change, choose a target platform, package, quality check, explain an error, Git, cache and cleaning, Studio, language. Every choice shows the command it runs. Arrow keys, shortcuts and Esc on a terminal; numbers and Enter everywhere else (pipes, `CHARPENTE_CONSOLE=plain`). English and French. Scripts and pipes keep the plain help; `CHARPENTE_CONSOLE=off` restores it in a terminal. See [docs/console.md](docs/console.md).
- Tested with 96 automated tests, a real project created/built/run through the menu, and a **real Windows pseudo-console (ConPTY)**, which found and fixed one defect (Ctrl+C at a text question was reported as end of input on Windows and closed the program). The POSIX key reader was **not run** on Linux or macOS.
- The dashboard honours `CHARPENTE_TRUST_ALL` and never runs an unapproved project file. Dev extras: `pywinpty` and `pyte` (for the terminal test).

## v0.13.0 -- Phase P9: reproducible builds, shared cache, interoperability, dev loop, first run

- **Reproducible builds**: `--reproducible` (own build folder; paths mapped to `/src`, fixed clock, no linker timestamp/build-id, deterministic archives; GNU-style toolchains, MSVC is refused) and
  `charpente verify-reproducible` (two folders, byte-for-byte comparison, likely causes when they differ).
- **Shared cache**: `charpente cache serve` and `CHARPENTE_REMOTE_CACHE` (HTTP, content-addressed; loopback by default, token from the environment, HMAC-signed entries, digests re-checked on both sides, fail-open,
  unsafe set-ups refused with CH8028); cache keys are relocatable with the reproducible flavour. `charpente cache remote` shows the state. **No TLS in the server**: put it behind a TLS proxy ([docs/shared-cache.md](docs/shared-cache.md)).
- **Budgets**: `ws.budget(build_time=, total_size=)`, `t.budget(size=)`; an exceeded budget fails the build (CH8024); `--no-budget`; a size budget that cannot be measured is reported, not skipped silently.
- **Interoperability**: `charpente import cmake` (through CMake's File API; untranslatable parts are reported), `charpente generate compile-commands|ninja|cmake|vs` (verified with clangd, Ninja, CMake; the Visual Studio
  output is **not** verified in Visual Studio; Xcode is not implemented).
- **Dev loop**: `charpente dev` (rebuild on change) and **hot reload** for `Kind.PLUGIN` targets with the header-only `charpente_hot.h` (`charpente-hot` recipe, shipped inside Charpente); experimental.
  `charpente docs` (Markdown API pages from doc comments, Mermaid/SVG target graph, optional Doxygen).
- **Resources**: memory and disk are watched (`resource.low_memory`, `resource.low_disk`), `--eco` / `CHARPENTE_ECO` for battery and heat; an interrupted build resumes without redoing finished work (verified by killing a real build).
- **Devices**: `charpente deploy --device all` builds one APK for every connected device's ABIs, installs in parallel (one failure does not stop the others), `--logs` merges every device's log into one tagged stream. Verified on one real x86_64 emulator; the several-device cases are simulated in the tests (real APK, fake `adb`).
- **First run and removal**: `charpente setup` (guided; asks before every download; never accepts a licence for you), remembered language (`~/.charpente/settings.json`, `CHARPENTE_LANG` still wins),
  `charpente self uninstall` (dry run unless `--yes`; signing keys only with `--keys`; links are never followed). The package builds and passes `twine check` and installs in a clean virtual environment; **nothing was uploaded to PyPI**.
- New error codes CH1026, CH8024-CH8028; new events `budget.*`, `resource.*`, `dev.*`, `deploy.device_found/installing/launched/log`; ADR 0019; guides in English and French; [docs/stability.md](docs/stability.md) lists what is verified.
- **Fixed (found by these tests)**: a change saved while `charpente dev`'s first build ran was lost; `dev` output was not flushed when piped; the engine tests depended on the machine's free memory (now pinned in `tests/conftest.py`);
  `verify-reproducible` could not find outputs from `target.finished` (now read from the action events).
- **Not done**: remote execution (REAPI) and hybrid execution ([ADR 0019](docs/adr/0019-reproductibilite-cache-partage.md) says why), an Xcode project, a run of `--device all` on several real devices at once, TLS in the cache server, MSVC reproducibility (`/Brepro`),
  and anything on Linux or macOS. The version stays 0.x: the CI workflow exists but has never run on this work (not pushed), and only Python 3.12 was used.

## v0.12.0 -- Phase P8: Studio, debugging, AI assistance

- **`charpente studio`**: a workspace UI served locally (French/English, light/dark): file explorer, targets, options (saved in `.charpente/options.toml`), package search/add/remove, an editor
  with highlighting, DSL completion and **clangd** (completion, diagnostics, go to definition, rename), format on save, save-conflict detection; live build panel, problems, dependency graph with the
  **critical path**, build profile, Git (per-block staging, gate-guarded commit), devices (deploy, `logcat`/`hilog`), terminal tabs, command palette. Loopback only; token, Origin and Host checks, strict CSP.
- **Debugging**: `charpente debug`, `charpente debug-adapter` (a DAP adapter that builds the target, then drives **gdb 14+** or **lldb-dap**), a Debug panel in Studio (breakpoints, stack, variables, watch,
  stepping) and a `charpente` debug type in the VS Code extension. Verified with a real gdb 17.2, not with lldb-dap.
- **AI, opt-in**: `charpente fix` (a diff you approve; rebuilt and reverted if it does not build; the gate runs after), `charpente ai tests` (proposed only if it compiles and passes), `charpente ai migrate`,
  `charpente ai status`. Every request shows what it sends first (`--show-context`, `--dry-run`), probable secrets are replaced, secret files are never sent. **No real provider was called.**
- New error codes CH8019-CH8023; `charpente doctor` lists clangd, clang-format, clang-tidy and the debugger.
- Studio was checked end to end in a real headless Edge (23 tests) plus 33 front-end unit tests; `studio-desktop/` (Tauri) is an **uncompiled skeleton** and no installers exist.
- **Fixed (found by these tests)**: `clang-cl` was picked as the default Windows compiler when merely on PATH (it cannot compile without MSVC's headers): it is now offered only if it compiles a test file;
  builds started by a server were not recorded in the history (empty profile); compiler errors were missing from the server's build log; `charpente/format` reformatted everything in LLVM style (now only with a `.clang-format`);
  a captured child process no longer inherits stdin (`core/process.py`).
- Not done: a compiled desktop wrapper and installers, a terminal with a pty, Monaco, build cancellation, remote debugging, an action timeline, lldb-dap and non-Windows verification.

## v0.11.0 -- Phase P7: server, VS Code extension, terminal

- **`charpente serve`**: the engine as a JSON-RPC 2.0 server. Build Server Protocol 2.1 (with the C/C++ `cppOptions` extension) over stdio, plus `charpente/*` methods
  (workspace, graph, toolchains, build, compile database, quality gate, explain, why, history, event subscription). `--ws` serves the same over a loopback WebSocket with a random
  token and an Origin check; `--bsp-install` writes `.bsp/charpente.json`. Compiler errors are published as located diagnostics and cleared when fixed.
- **VS Code extension** (`vscode-charpente/`): targets view, Problems, status bar, tasks with a problem matcher, `compile_commands.json` for clangd, `.charpente` highlighting.
  23 automated tests (real server + a fake `vscode` module); packaged as a local `.vsix`; **not** loaded in a live VS Code, not published.
- **`charpente shell`**: a shell/command with the project's toolchain on PATH and `CC/CXX/AR` set (`--print-env` for sh/PowerShell/cmd/JSON).
- **`charpente tui`**: a Textual terminal interface (targets, live log, build/run/test/check keys); optional `charpente[tui]`.
- New error codes CH8017 (shell), CH8018 (terminal interface not installed).
- **Fixed (found by exercising the extension): a captured child process inherited the parent's stdin.** From a server that speaks over stdin/stdout, `charpente run`/`check` could
  hang or swallow protocol bytes; `core/process.py` now gives captured children no stdin (unless `input=` is given). Also fixed: an invalid `Content-Length` produced two errors;
  workspace-load errors lacked their `CHxxxx` code in the message; `buildTarget/run` split `--config Debug` into a flag and a program argument.
- Not done: build cancellation, debugging (DAP), remote serving, a third-party BSP client check, a live VS Code check.

## v0.10.0 -- Phase P6: kits and project templates

- **Kits**: `kit-core`, `kit-app`, `kit-graphics`, `kit-xr`, `kit-game`, `kit-net`, `kit-embedded`, `kit-mobile`, `kit-android`, `kit-ohos`: curated recipe sets with a stated
  verification (`charpente kit list|show|add`, `ws.kit()`, `t.uses("kit-x")`). Twenty new recipes (simdjson, stb, miniaudio, cgltf, volk, vma, meshoptimizer, asio, websocketpp,
  tracy, imgui, glfw, ImGui backends, freertos, printf, cmsis, openxr-headers, pybind11), all compiled for real.
- **Kits shipped inside Charpente** (`charpente://` sources, digest-pinned): `tinylibc` (freestanding libc bits for zig) and `charpente-mobile` (lifecycle, logging, files, assets on
  Android/HarmonyOS/iOS/desktop; Android verified on an emulator).
- **16 project templates**: `charpente init NAME --template T` (console, bibliotheque, app-gui, jeu-2d, jeu-3d-vulkan, vr-openxr, app-android, app-harmonyos, app-mobile, web-wasm,
  wasi-plugin, plugin-python, firmware-stm32, firmware-esp32, linux-embarque-rpi, module-charpente); each states what was verified. `charpente init NAME` is unchanged.
- DSL: `ws.package_settings()`, `t.output_prefix()/output_extension()`, `platform_settings(..., name=...)` allowed.
- **Fixed: the wheel never contained the recipes** (nor, now, kits, kit sources or templates): `package-data` was not declared. A test compares the declaration with the files (including
  dot-files, which packaging tools skip).
- Also fixed: zig firmware lost compiler-rt (`-nostdlib`); `uses_public` did not expand kits; the linter did not know kit names.
- Not done: `ar-mobile`, `jeu-harmonyos`, SDL3/libcurl/TLS/shaderc/Jolt/OpenXR loader in kits, ESP-IDF delegation, a shared binary cache.

## v0.9.0 -- Phase P5: quality gate, Git and GitHub, releases

- **`charpente check`**: a configurable quality gate (`.charpente/quality.toml`) with three levels. Checks: build, clang-format, DSL lint, **secrets**,
  file size, warnings-as-errors on changed code, clang-tidy, cppcheck, tests (**flaky** detection), sanitizers, **coverage** (gcov), other platforms, dependency
  **audit**, **licenses**, SBOM. A check whose tool is missing is *skipped visibly* (`fail_on_skipped` makes CI strict); every problem is a located diagnostic event.
  `--changed`, `--fix` (then re-verify), `--only/--skip`, `--json`; modules can add checks.
- **Build flavours**: `--sanitize address,undefined` and `--coverage` on build/test, probed rather than assumed (MinGW correctly refused).
- **Git integration**: `charpente hooks install`, `status`, `commit` (Conventional Commits, drafted message you review, optional AI draft), `push` (standard gate,
  typed confirmation for forced pushes), `pr` (summary, gate result, **warning for commits that skipped the gate**, SBOM section; `gh` or GitHub API), `ci init`.
- **Releases**: `charpente release` (version from commits, changelog, zip packages, SBOM, `SHA256SUMS`, Ed25519 signature, **SLSA v1 provenance in a signed DSSE
  envelope**, commit and tag; publishes only with `--publish`); `charpente sign` with an encrypted local key vault.
- Also added: `charpente deploy` now covers iOS simulators/devices and HarmonyOS; new error codes CH8011-CH8016.
- Verified for real: strict gate on a C++ project (coverage, three cross builds, SBOM), and a full release in a temporary Git repository. Not verified: GitHub itself.
- Fixed: `*.charpente` matched the `.charpente/` directory in the release reader (again); an operator-precedence slip made a gate error message always truthy.

## v0.8.0 -- Phases P4c and P4d: HarmonyOS, microcontrollers, Apple, XR

- **HarmonyOS/OpenHarmony**: the native SDK's clang with the flags of its own `ohos.toolchain.cmake` (drift reported by `doctor`), `toolchain install ohos` (public SDK, SHA-256 verified),
  hvigor delegation for `.hap/.har/.hsp`, hdc deployment, Node-API skeleton. Built for real for arm64/arm/x64 with SDK 5.0.0.71; hvigor/hdc/device **not** available.
- **Microcontrollers**: `Kind.FIRMWARE` for Cortex-M0/M3/M4/M7/M33 and AVR with zig or the vendor GCC, `.bin`/`.hex`/`.uf2`, `charpente size`, `charpente flash`. Built for real with zig; nothing run on hardware.
- **iOS/visionOS**: Xcode toolchain, `.app`/`.ipa`, codesign, simulator and device deployment -- **written without a Mac, not run**.
- **XR**: Quest/Pico/OpenXR manifest profiles on Android (`xr=`), verified with aapt2.
- Fixed: zig has no linker-map option; the NDK-style flags for 32-bit OpenHarmony ARM were wrong (corrected from the SDK's own file).

## v0.7.0 -- Phase P4b: Android

- **Native Android apps without Gradle**: `Kind.MOBILE_APP` + `platform_settings("android", ...)`,
  the NDK as a cross toolchain (`--platform android-arm64|android-arm|android-x64`), `native_app_glue`, libc++
  static or shared.
- **`charpente package --format apk`**: manifest, libraries (stored, aligned), `zipalign`, `apksigner`, then a
  verification of the signature; debug key or your own (`--keystore`, password only from the environment).
- **`charpente deploy`**: installs on the connected device/emulator and starts the app.
- **`charpente toolchain install ndk|build-tools|platform|platform-tools`** into `~/.charpente/toolchains/android-sdk`,
  only after `--accept-android-license` (the license is shown, never accepted for you); SHA-1 checked.
- Verified for real with the NDK 28.2, build-tools 36.1 and an x86_64 emulator: built, packaged, signed, installed,
  launched, log read back. arm64 was built and inspected, **not run**. Not done: Java/Kotlin, Gradle, AAB, shaders.
- Fixed: shared objects lacked `-fPIC` (non-Windows); a C file inside a C++ target can now be compiled as C where
  needed; `download()` accepts a SHA-1; zip extraction creates in-archive symlinks safely (POSIX only).
- New error codes CH8006-CH8010.

## v0.6.0 -- Phase P4a: platforms and cross-compilation

Native builds are unchanged.

- **`--platform OS-ARCH`** on `build`, `run`, `test`, `package`, and **`--toolchain NAME`**. Twenty-three
  platforms are described with support tiers; `charpente platforms` shows the tier and whether this machine
  can build each one; `charpente doctor` reports the environment and what is missing.
- **Cross-compilation through zig** (`charpente toolchain install zig`, SHA-256 verified, no admin rights):
  Linux (x64/arm64/riscv64), Windows arm64, macOS (x64/arm64), FreeBSD, NetBSD, WASI. **Emscripten**
  (`toolchain install emsdk`) for browser WebAssembly. Each platform has its own build directory and action
  records; the content cache is shared.
- `charpente run` runs WASI programs through wasmtime or Node, Emscripten output through Node, and refuses
  binaries it cannot run (CH8004).
- Assembly (`.s`/`.S`) and Objective-C (`.m`/`.mm`) sources; output names for every target OS.
- Fixed: MinGW shared libraries were named `libX.so` on Windows (now `X.dll`); a tool failing silently now says
  which tool and which exit code instead of "build failed".
- New error codes CH8001-CH8005. Not done (documented): C++20 modules, shaders, musl selection, MSVC
  cross-arch, running foreign binaries under emulators; cross-built binaries other than WebAssembly were
  format-checked, not executed.
## v0.5.0 -- Phase P3: DSL v2 and packages

Every v0.1.0 workspace builds identically (the original tests pass unchanged).

- **DSL v2.** `t.uses("engine", "fmt")` (order + link + shared settings), `public_*` /
  `interface_*` include dirs, defines, flags, `uses_public`, `HEADER_ONLY` and `PLUGIN` kinds,
  conditions `on_config` / `on_platform` / `on_toolchain` / `when` (resolved per build context),
  typed options (`ws.option`, `--opt`, `charpente options`), `Rule` (your own cached build steps),
  `ws.requires`, `ws.platforms`, `Workspace(..., version=)`. Single strings are now one item, not a
  list of characters.
- **`charpente.toml`**: a data-only workspace form; no code runs, no approval needed; unknown keys
  are errors.
- **`charpente lint`** (static, never runs the file; also quietly before every load) and
  **`charpente migrate`** (v0.1.0 idioms to v2, diff first).
- **Charpente Pkg.** `ws.requires("fmt@^10")`, `charpente pkg install` (resolve with backtracking,
  verified downloads, `charpente.lock`), packages become ordinary targets built by the engine.
  **A build never downloads.** `pkg vendor` (builds with no store and no network), `pkg mirror`
  (HTTP with `Range`), `pkg audit` (OSV), `charpente sbom` (SPDX 2.3 + CycloneDX 1.5, validated
  against the official schemas). Ten bundled recipes (fmt, spdlog, nlohmann_json, glm, CLI11, entt,
  doctest, tomlplusplus, magic_enum, vulkan-headers), all built with a real compiler and rebuilt
  offline from `vendor/`.
- Fixed while verifying with real packages: archive extraction on Windows paths over 260
  characters, unexpected exceptions now reported as `CH9002` instead of a raw traceback,
  `charpente run` no longer confused by package targets.
- Not done (documented): downloadable prebuilt binaries, vcpkg/Conan/pkg-config bridges, recipe
  options, signed recipes.

## v0.4.0 -- Phase P2: events and modules

- **Modules.** Everything that is not the core is a module, through one API
  (module API 2.0): a `charpente-module.toml` manifest, declared `[provides]`, declared
  `[capabilities]` shown and approved at installation, guarded `ctx.process` /
  `ctx.fs` / `ctx.net`, defensive loading, `charpente module add|list|info|remove|
  enable|disable|approve|update|check|new|keygen|sign|trust-key|registry`. Install
  from a folder, a `.zip`, a URL or a registry. **Capabilities are a contract, not a
  sandbox** -- see `docs/modules.md` and `docs/security.md`.
- **Signatures** (Ed25519, checked against the RFC 8032 vectors). No official key is
  published yet; third-party modules need `--allow-unsigned`.
- The six built-in **toolchains are now modules**, in the v0.1.0 preference order.
  `charpente toolchain list`.
- **`charpente-notify`** (bundled, off until enabled): desktop notification,
  webhook, Discord, Slack, Telegram, e-mail; secrets only by environment-variable
  name.
- **Hooks**: `@ws.on(Event.BUILD_FINISHED)` and `notify()` in `.charpente` files;
  scripts in `.charpente/hooks/` (approved by content hash, never through a shell).
- **Output**: `--output auto|plain|rich|jsonl`; GitHub Actions annotations
  automatically inside Actions; resumable, verified, budgeted downloads
  (`CHARPENTE_OFFLINE=1` forbids the network).
- **Events**: a JSON Schema for every event under `docs/events/`, generated from
  one table and checked by a test.
- Fixed: a project's own `.charpente/` *directory* was mistaken for a second
  workspace file (`CH1003`) as soon as one existed.

## v0.3.0 -- Phase P1: the engine

Every v0.1.0 `.charpente` file still builds. What changed is what happens
underneath, and a set of new commands.

- **Exact incremental builds.** Editing a header now recompiles precisely the
  files that include it (`-MMD -MF` for GCC/Clang, `/showIncludes` for MSVC and
  clang-cl). Freshness is decided by file *content* (BLAKE3, blake2b fallback),
  not timestamps: `touch` rebuilds nothing.
- **Content-addressed cache** (`~/.charpente/cache`): reverting an edit, switching
  branches or cleaning `build/` replays results instead of recompiling.
  `charpente cache stats|gc|clear|dir`.
- **Parallel builds**, longest chain first (`-j N`, default one per CPU).
- **A build that has nothing to do takes ~0.25 s for 10 000 files** (was 18.7 s in
  the first engine draft) thanks to a metadata-only fast path, directory-batched
  file metadata and a `scandir`-based glob. See ADR 0007 and ADR 0010 (which
  states plainly that a *single-file edit* in such a project still costs ~6 s).
- **`charpente why <target|file>`**: what would rebuild and why (`header changed:`,
  `command line changed: added -DX`, `tool changed`, `output missing`...);
  `--last` explains the previous build.
- **`charpente history`, `charpente diff-build`**: sessions, and how two builds
  differ (time, binary sizes, new/fixed warnings). **`charpente headers`** ranks
  headers by rebuild cost; builds print a hint when one header change recompiled
  20+ files.
- **Events.** The build emits typed events; `--output jsonl` prints them (schemas
  in `docs/events/`), every session is logged to `build/.charpente/events/` and can
  be replayed with `charpente replay`.
- **`build/compile_commands.json`** is written for clangd, clang-tidy, CLion, VS Code.
- `charpente test --retries N` reports `[FLAKY]` for a test that fails then passes
  with no change in between; all test targets build together.
- Compiler warnings from successful compilations are now shown.

Fixed while redesigning (each was a real defect of v0.1.0):

- two `util.cpp` in different folders shared one object file (one silently
  overwrote the other);
- `include_dirs(["include"])` was relative to the shell's current directory, not the
  workspace;
- changing a library did not relink an executable that links it;
- an archive kept members of deleted sources.

Known limits: see ADR 0006 (a header that newly shadows another on the include path
is not detected) and ADR 0010.

## v0.2.0 -- Phase P0: foundations

Nothing about how a `.charpente` file is written changes: every valid
v0.1.0 workspace still loads and builds.

- **Stable error codes.** Every user-facing error now carries a code
  (`CH1001`...), a cause and a fix, in French and English
  (`CHARPENTE_LANG=fr|en`, else the system locale). `charpente explain
  CH3001` (or `explain --list`) prints the long form; `docs/errors.md`
  is generated from the catalogue and checked by a test.
- **One process layer.** All process launches go through
  `charpente.core.process`; a test fails if any other module imports
  `subprocess` or enables the shell. A missing program is now `CH2002`
  instead of a traceback.
- `ChError` takes its code as a positional-only argument, so an error
  parameter named `code` (e.g. a tool's exit code) can never collide with it.
  (Strict typing caught this in the migration itself, before release.)
- **Tooling.** `ruff`, `mypy --strict` (whole package), coverage gate at
  75 %, CI matrix on Windows/Linux/macOS x Python 3.9/3.12, an sdist+wheel
  check, and a release workflow that publishes to PyPI only from a pushed
  `v*` tag through trusted publishing (no token stored). **Nothing has been
  published to PyPI.**
- `Workspace.root` replaces scattered `workspace.location / ...` (which
  was `Optional`).

## v0.1.0 — initial release

First working version. From-scratch project: no code shared with, and not
a fork of, any prior build tool.

- DSL: `Workspace`/`Target` context managers, `.charpente` file loading,
  glob-based source resolution, topological dependency ordering with
  named cycle/unknown-dependency errors.
- Trust-on-first-use consent before executing a `.charpente` file
  (content-hash-keyed, `CHARPENTE_TRUST_ALL=1` for CI).
- Build engine: compiler discovery for MSVC/clang-cl/MinGW (Windows),
  GCC/Clang (Linux), Apple Clang (macOS); timestamp-based incremental
  builds; dependency-ordered multi-target builds with an optional
  keep-going mode; automatic linker search paths for `.links([...])`
  against another workspace target.
- CLI: `init`, `build`, `run`, `clean`, `test`, `package`, `ask`.
- Packaging: `.zip` by default; `--format installer` builds a real
  platform installer (Inno Setup `.exe` on Windows, `.deb` on Linux,
  `.pkg` on macOS) when the platform tool is available, and otherwise
  writes the installer script/staging tree with the exact command to
  finish the job by hand.
- AI: pluggable provider (Anthropic, OpenAI, a local OpenAI-compatible
  endpoint, or none) selected by environment variable, with zero AI
  dependency required for the rest of the tool to work.
  `charpente build --ai-diagnose` asks the configured provider to
  diagnose a compile/link failure; `charpente ask` is a general assistant
  with workspace context.
- Path-traversal-safe target/workspace names, validated at declaration
  time rather than wherever a path happens to be built later.
- Full documentation: `docs/tutorial.md`, `docs/dsl-reference.md`,
  `docs/cli-reference.md`, `docs/security.md`, `docs/architecture.md`,
  `docs/troubleshooting.md`.

Bugs found and fixed during development by actually running the tool end
to end against a real compiler, not just by code review — kept here
because each one shaped a design rule that's now stated explicitly in the
docs:

- `run`/`package`/`test` built a single target directly, skipping its
  dependencies — the first time a config was requested other than through
  `charpente build`, linking failed against a dependency that had never
  been built for that config. Fixed with `builder.dependency_closure()`.
- `argparse.REMAINDER` kept a leading `--` as a literal forwarded
  argument (`charpente run -- --foo` passed `"--"` itself to the program),
  and separately made `charpente ask` crash on a question starting with a
  dash instead of asking it.
- A build-error capture that took stderr *or* stdout, never both, could
  silently drop the useful half of a compiler/linker failure.
- `.charpente` template generation had an invalid `pathlib` glob pattern
  and a `str.format()` call that collided with literal `{ }` in C++ source.
- `depends_on()` controlled build order but not linking — a target had to
  also declare `.links([...])`, and the linker had no search path for a
  sibling target's library until the builder started adding one
  automatically.

Known limitations, tracked rather than hidden: no per-header dependency
tracking (timestamp-only incremental builds), Linux/macOS builds are
unit-tested but not yet exercised against a real compiler outside this
project's own CI, desktop targets only (no mobile/web/console), no
precompiled headers or C++20 modules.
