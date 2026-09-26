# CLI reference

Every command accepts `--file PATH` to point at a specific `.charpente`
file. Without it, Charpente looks for the single `.charpente` file in the
current directory, then each parent directory in turn, until it finds
exactly one (an error names the directory if there's more than one, or if
there's none at all the way up).

The first time any command loads a `.charpente` file whose exact content
hasn't been approved before, you're asked to confirm — see
[`security.md`](security.md).

## `charpente` alone, and `charpente menu`

In a terminal, `charpente` with no command opens a guided menu: create a project from a template, build, run, test, package, choose another platform, explain an error, Git, cache, all by choosing
from lists, with the equivalent command shown before it runs. `charpente menu` opens it explicitly (also with piped input, by typing numbers). When the output is not a terminal, or with
`CHARPENTE_CONSOLE=off`, a bare `charpente` prints the plain help as before. See [console.md](console.md).

## `charpente init NAME [--dir DIR]`

Scaffolds `NAME.charpente` and `src/main.cpp` (a minimal "Hello, world"
executable target) in `DIR` (default: the current directory). Fails if
`NAME.charpente` already exists there — it never overwrites.

```bash
charpente init MyApp
cd MyApp  # if you used --dir MyApp; otherwise you're already there
charpente build
```

## `charpente build`

```
charpente build [--config Debug|Release] [--keep-going] [--ai-diagnose]
                [-j N] [--no-cache] [-v] [--output plain|jsonl]
```

Compiles every target in the workspace, in dependency order. Independent
work (every source file, independent targets) runs in parallel.

- `-j N` / `--jobs N`: at most N actions at once (default: one per CPU).
- `--platform OS-ARCH`: build for another platform (`linux-arm64`, `wasm32-wasi`...). Objects go to
  `build/<Config>-<platform>/`, so platforms never overwrite each other. Also accepted by `run`,
  `test` and `package`. See [platforms.md](platforms.md).
- `--toolchain NAME`: use that detected toolchain instead of the first one.
- `--sanitize KINDS` (`address,undefined`) and `--coverage`: instrumented flavours with their own build directory; refused (CH8011) when the
  toolchain cannot really build them.
- `--no-cache`: neither read nor write the [content cache](#charpente-cache).
- `--reproducible`: build so the output does not depend on the folder or the time of the build (own build directory `build/<Config>-repro`); see
  [reproducible-and-budgets.md](reproducible-and-budgets.md) and `charpente verify-reproducible`.
- `--eco`: build gently (halve the parallel jobs; `CHARPENTE_ECO=auto` does it only on battery or a hot machine). Memory and disk are always
  checked. See [resources.md](resources.md).
- `--no-budget`: skip the budgets declared with `ws.budget()` / `t.budget()`; an exceeded budget otherwise fails the build (CH8024).
- `-v` / `--verbose`: show every command that runs and *why* it runs
  (`because: header changed: include/a.h`).
- `--output auto|plain|rich|jsonl`: `auto` (default) shows a live progress bar on
  an interactive terminal when the optional `rich` package is installed
  (`pip install "charpente[rich]"`), plain text otherwise; `jsonl` prints one JSON
  event per line for scripts, editors and CI
  ([`events/README.md`](events/README.md)). Inside GitHub Actions, compiler
  diagnostics are also emitted as `::error file=…,line=…::` annotations.

- `--config` (default `Debug`): which configuration to build. Affects
  optimization/debug-symbol flags (`-O0 -g` / `/Od /Zi` for Debug,
  `-O2` / `/O2` for Release) and the output directory (`build/<config>/...`).
- `--keep-going`: without it, a target failure stops the whole build
  immediately. With it, unrelated targets still get built — only the
  failed target and anything that (directly or transitively) depends on
  it are skipped.
- `--ai-diagnose`: on a target failure, sends the compiler/linker's error
  output to the configured AI provider and prints its suggested cause and
  fix. Never automatic — see [AI features](#ai-features-1) below.

Builds are **exactly incremental**. Charpente records, for every
compilation, the headers the compiler actually read (`-MMD` for
GCC/Clang, `/showIncludes` for MSVC and clang-cl). Editing a header
recompiles precisely the files that include it — no more, no less.
Freshness is decided by file *content*, not timestamps: `touch`ing a file
rebuilds nothing, and reverting an edit is served from the cache. If
nothing changed since the last successful build, the answer comes from
file metadata alone, in about a quarter of a second for 10 000 files.
See [architecture](architecture.md#the-engine) and
[ADR 0006](adr/0006-cles-daction-et-cache.md) for how, and its stated limits.

Warnings printed by the compiler during a successful compilation are
shown (they used to be discarded).

Output per target, then a one-line summary:

```
  [ok]         app -> build/Debug/app/app
  [up to date] otherlib
  [FAILED]     broken: <compiler/linker error output>
Done in 2.1s: 3 run, 12 from cache, 40 up to date.
```

`build/compile_commands.json` is (re)written on every build that plans
work, so `clangd`, `clang-tidy`, CLion and VS Code understand your project
with no extra step.

## `charpente run`

```
charpente run [--target NAME] [--config Debug|Release] [--no-build] [-- program args...]
```

Builds (unless `--no-build`) then executes the target.

- `--target`: which target to run. Optional if the workspace has exactly
  one target; required (with a clear error listing the known names)
  otherwise.
- `--no-build`: skip the build step and run whatever's already in
  `build/<config>/<target>/` — fails clearly if nothing's there yet.
- Arguments after `--` are forwarded to the program's own `argv`, and the
  `--` separator itself is stripped (not passed as a literal argument):

  ```bash
  charpente run -- --verbose input.txt
  # the program sees argv = ["--verbose", "input.txt"], not ["--", "--verbose", "input.txt"]
  ```

## `charpente test`

```
charpente test [--config Debug|Release] [--retries N] [-j N] [--no-cache] [-v]
```

Builds and runs every target declared with `.kind(Kind.TEST)`. A test
"passes" if the program exits with code 0. Prints a `[PASS]`/`[FAIL]` line
per test target and a summary (`N/M test target(s) passed.`); exits 0 only
if every test passed. All test targets are built together (in parallel),
and one that fails to build does not hide the others.

`--retries N` re-runs a failing test up to N times. A test that fails and
then passes with **no change in between** is reported `[FLAKY]` (and still
counts as passed): it means something in it is nondeterministic, and the
summary says so. A workspace with no `Kind.TEST` targets prints a
note and exits 0 (not an error — most workspaces don't have tests yet).

## `charpente package`

```
charpente package [--target NAME] [--config Release] [--format zip|installer]
                  [--version X.Y.Z] [--maintainer "Name <email>"] [--output PATH]
```

Builds the target, then packages the result.

- `--format zip` (default): a `.zip` of the build output directory
  (object files excluded), written to `dist/<target>-<config>.zip`. Needs
  no external tool, works identically on every platform.
- `--format installer`: a real platform installer — see
  [Building a real installer](#building-a-real-installer) below.
- `--version`: embedded in the installer's metadata (Inno Setup
  `AppVersion`, `.deb` `Version`, `.pkg` version). Default `1.0.0`.
- `--maintainer`: the `.deb` control file's `Maintainer` field
  (`--format installer` on Linux only). Default `unknown <unknown@example.com>`
  — set this for a real package.
- `--output`: override the output path (zip format only).

### Building a real installer

```bash
charpente package --format installer --config Release --version 1.2.3
```

| Platform | Tool needed | Produces | If the tool is missing |
|---|---|---|---|
| Windows | [Inno Setup](https://jrsoftware.org/isinfo.php) (`iscc` on `PATH`) | `dist/<target>-setup.exe` | The `.iss` script is still written to `dist/`; install Inno Setup, then run the printed `iscc ...` command |
| Linux | `dpkg-deb` (usually preinstalled on Debian/Ubuntu) | `dist/<target>.deb` | The staging tree (`DEBIAN/control` + binary) is still written to `dist/`; run the printed `dpkg-deb ...` command on a Debian/Ubuntu machine |
| macOS | `pkgbuild` (via Xcode Command Line Tools) | `dist/<target>.pkg` | The staging tree is still written to `dist/`; run the printed `pkgbuild ...` command on macOS |

Charpente never silently falls back to a zip when the installer tool is
missing, and never claims an installer was built when only its input was
prepared — the fallback message always names the exact command to finish
the job yourself.

## `charpente clean`

```
charpente clean
```

Removes the whole `build/` directory (every config, every target).
Prints what it removed, or says there was nothing to clean.

## `charpente why`

```
charpente why <target | file> [--config Debug|Release] [--last]
```

Explains why something would be (or was) rebuilt, without building
anything. Give a target name, or any source, header or output file:

```
$ charpente why include/b.h
compile:app:src/two.cpp  (Compiling two.cpp)
  would be rebuilt:
    - header changed: include/b.h
```

Reasons include: a changed input or header, a changed command line (with
the flags added or removed), a different compiler version, a changed
environment variable, a missing or hand-modified output. `--last` explains
the previous build from the history instead of predicting the next one.

## `charpente history` / `charpente diff-build`

```
charpente history [--limit N]
charpente diff-build [A [B]]        # default: previous vs latest
```

`history` lists recent build sessions (result, duration, how many actions
ran, came from cache, or were up to date, warning count). `diff-build`
compares two of them: total time, actions run, **binary size changes**,
the slowest actions that got slower, and **warnings that appeared or
disappeared**. `A` and `B` are a session id (prefix), a number from
`history`, `latest` or `previous`.

## `charpente cache`

```
charpente cache stats | dir | clear | gc [--max-size 5GB]
charpente cache serve [--dir D] [--host H] [--port P] [--token-env VAR] [--readonly] [--max-blob SIZE]
charpente cache remote
```

The content cache lives in `~/.charpente/cache` (override with
`CHARPENTE_CACHE_DIR`) and is shared by every workspace. `gc` deletes the
least recently used files until it fits. Entries are found only by the hash
of everything that determines their content, so a stale entry can never be
returned.

`serve` runs a **shared cache** for a team or CI over HTTP and `remote` shows the one this machine uses (`CHARPENTE_REMOTE_CACHE`); see
[shared-cache.md](shared-cache.md) for the setup and the threat model.

## `charpente replay`

```
charpente replay [SESSION | path/to/log.jsonl] [--output plain|jsonl]
```

Replays a past build from its event log (`build/.charpente/events/`, the
20 most recent sessions are kept).

## `charpente headers`

```
charpente headers [--top N]
```

Ranks the project's headers by *rebuild cost*: how many compilations read each
one and how long they took last time. Fixing the top of this list (forward
declarations, splitting a widely included header, a precompiled header) is the
cheapest way to speed up incremental builds. Builds also print a hint when a
single header change recompiled 20 or more files.

## `charpente toolchain`

```
charpente toolchain list
charpente toolchain install zig[@VERSION] | emsdk[@VERSION]
charpente toolchain install ndk[@VERSION] | build-tools[@VERSION] | platform[@API] | platform-tools
                            --accept-android-license
charpente toolchain remove NAME[@VERSION]
```

`list` shows every compiler Charpente can see, its version, which module provided its
detector and, for cross compilers, the platforms it can build. The first is the default for
native builds (cross-only toolchains such as Emscripten are never chosen without `--platform`).

`install` downloads into `~/.charpente/toolchains/` and changes nothing else (no PATH, no
registry). It only runs when you ask; a build never downloads.

- **zig**: the archive's SHA-256 (published by ziglang.org next to the link) is checked before
  unpacking. One binary that builds Windows, Linux, macOS, FreeBSD, NetBSD and WASI programs.
- **emsdk**: needs `git` and `python`; Emscripten's own installer downloads LLVM/Binaryen/Node
  (about 1.5 GB). Charpente relies on emsdk's own integrity checks here, not its own.

- **ndk, build-tools, platform, platform-tools**: from Google's SDK repository into
  `~/.charpente/toolchains/android-sdk/` (the layout Android Studio uses). They are under Google's
  **Android SDK License Agreement**: Charpente shows it and refuses (CH8010) until you pass
  `--accept-android-license`; it never accepts for you. Downloads are checked against the SHA-1 Google
  publishes (the only digest the repository offers). An SDK you already have (Android Studio,
  `ANDROID_HOME`) is used as it is; nothing needs installing then.

`remove` deletes that directory (and nothing outside it).

### Android: `package --format apk` and `deploy`

```
charpente package --format apk --platform android-arm64,android-x64 [--config Debug|Release]
                   [--keystore FILE --key-alias NAME]
charpente deploy   [--platform android-x64] [--device SERIAL|all] [--no-launch] [--logs [--log-seconds N] [--log-filter TEXT]]
```

`package --format apk` builds a `Kind.MOBILE_APP` target for each listed ABI, then links the manifest
(`aapt2`), adds the libraries, aligns (`zipalign`), signs (`apksigner`) and **verifies** the signature.
Debug builds use the standard Android debug key; a release build without `--keystore` warns that the
APK is debug-signed. The release key's password is read from `$CHARPENTE_KEYSTORE_PASSWORD`, never from
the command line. `deploy` does the same, then `adb install -r` and starts the app on the one connected
device or emulator. `--device all` builds one APK for every connected device's ABIs and installs it on all of them in parallel, and
`--logs` merges their logs into one tagged stream ([multi-device.md](multi-device.md)). See [android.md](android.md).

## `charpente check`, `hooks`, `status`, `commit`, `push`, `pr`

See [quality.md](quality.md) and [git.md](git.md). In short: `charpente check --level rapide|standard|strict [--changed] [--fix]`
runs the quality gate; `charpente hooks install` wires it into Git; `charpente commit`, `push` and `pr` put it in front of Git and GitHub.

## `charpente ci init`, `release`, `sign`

`charpente ci init` writes a GitHub Actions workflow; `charpente release [--dry-run|--publish]` prepares a signed release with checksums and
SLSA provenance; `charpente sign init` creates the Ed25519 release key. See [git.md](git.md).

## `charpente size`, `flash` (firmware)

`charpente size --platform cortexm4-arm` prints flash/RAM use; `charpente flash --platform ... [--tool openocd] [--dry-run]` programs the
board. See [embedded.md](embedded.md).

## `charpente platforms`

```
charpente platforms [--family desktop|mobile|xr|web|embedded|server] [--json]
```

Lists every target platform with its support tier, and whether *this* machine can build it now
(natively, or through which toolchain) or what is missing. See [platforms.md](platforms.md).

## `charpente init`, `charpente kit`

`charpente init NAME` creates `NAME.charpente` and `src/main.cpp` as before. `charpente init NAME --template T [--dir D] [--install]` creates a project
folder from a template (`charpente init --list`); `charpente kit list|show|add` browses the curated library sets. See [templates.md](templates.md) and
[kits.md](kits.md).

## `charpente serve`, `charpente shell`, `charpente tui`

`charpente serve [--stdio|--ws] [--root D]` runs the engine as a Build Server Protocol / JSON-RPC server for editors and Studio ([serve.md](serve.md)).
`charpente shell [--platform P] [-- CMD]` opens a shell with the project's toolchain on PATH and `CC/CXX/AR` set; `--print-env` prints the variables.
`charpente tui` is the Textual terminal interface (`pip install "charpente[tui]"`). See [terminal.md](terminal.md); the VS Code extension is in [vscode.md](vscode.md).

## `charpente studio`, `debug`, `debug-adapter`, `fix`, `ai`

`charpente studio` opens the workspace UI in your browser ([studio.md](studio.md)). `charpente debug [TARGET] [-- ARGS]` builds a target and debugs it in gdb/lldb; `charpente debug-adapter` is the DAP server editors use; `charpente debug --list` shows the debuggers found ([debugging.md](debugging.md)). `charpente fix` proposes a fix for a failing build as a diff you approve; `charpente ai tests|migrate|status` write tests (only if they pass), draft a `.charpente` from CMake, and explain the rules ([ai.md](ai.md)). All AI commands show what they send first (`--show-context`, `--dry-run`, `--yes`).

## `charpente verify-reproducible`, `import cmake`, `generate`

`charpente verify-reproducible [--config C] [--platform P] [--keep] [--json]` builds the project twice in different folders and compares the outputs byte for byte ([reproducible-and-budgets.md](reproducible-and-budgets.md)).
`charpente import cmake [FOLDER] [--out F] [--force] [--build-dir D] [--cmake PATH] [--cmake-arg ARG] [--print]` writes a `.charpente` from a CMake project, asking CMake itself.
`charpente generate [compile-commands|ninja|cmake|vs|xcode] [--out D] [--force] [--list]` writes project files for other tools; `xcode` is not implemented ([import-and-generate.md](import-and-generate.md)).

## `charpente dev`, `docs`

`charpente dev [--target T] [--hot-dir D] [--poll S] [--cycles N] [--no-initial-build]` rebuilds when files change and publishes plugin builds for hot reload (experimental, [hot-reload.md](hot-reload.md)).
`charpente docs [--out D] [--doxygen]` writes Markdown API pages from doc comments and the target graph ([api-docs.md](api-docs.md)).

## `charpente setup`, `self`

`charpente setup [--yes] [--lang en|fr]` is the guided first run; `charpente self uninstall [--only GROUP] [--keys] [--yes]` removes what Charpente stores on the machine (a dry run without `--yes`).
See [setup-and-uninstall.md](setup-and-uninstall.md).

## `charpente doctor`

```
charpente doctor [--json]
```

Reports the host, the compilers found, useful tools (git, node, wasmtime...), the platforms
buildable right now and, for each other platform, what to install. Exit code 1 when nothing can
be built.

## `charpente module`

```
charpente module list | info NAME | add SOURCE | remove NAME | enable NAME | disable NAME | approve NAME
charpente module update [NAME] | check PATH | new NAME | keygen | sign PATH --key FILE | trust-key HEX
charpente module registry add|list|remove URL
```

Everything that is not the core is a module, and modules use one API. See
[`modules.md`](modules.md) for writing, signing and publishing them and for what
the capability system does and does not guarantee. `SOURCE` is a folder, a `.zip`,
an `https://…/m.zip#sha256=…` URL, or a registry name (`name` or `name@^1.2`).
Adding a module shows what it asks for and needs your confirmation; a module not
signed by a trusted key also needs `--allow-unsigned`; `--yes` approves the
capabilities non-interactively.

## `charpente pkg` and `charpente sbom`

```
charpente pkg install [--update] [--max-download SIZE] [--registry URL]
charpente pkg list | check | info NAME | search [TEXT] | audit
charpente pkg vendor [--dir DIR] [--verify]
charpente pkg registry add|list|remove URL
charpente pkg mirror populate DIR | serve DIR [--host H] [--port N]
charpente sbom [--format spdx|cyclonedx|both] [--output DIR|-]
```

See [`packages.md`](packages.md). `pkg check` exits 1 unless `charpente.lock` is up to date and
every package is installed (for CI).

## `charpente lint`, `charpente migrate`, `charpente options`

`lint` analyses a `.charpente` file without running it; `--strict` also fails on warnings.
`migrate` shows a diff turning v0.1.0 idioms into DSL v2 and applies it with `--write` (keeping a
`.bak`). `options` lists the workspace's `ws.option(...)` declarations with their current values.
Every build-like command accepts `--opt NAME=VALUE` (repeatable).

## `charpente explain`

```
charpente explain CH3001 [--lang fr|en]
charpente explain --list
```

Every error carries a stable code (`[CH3001]`); `explain` prints its cause,
its fix and any extra explanation. The language follows `CHARPENTE_LANG`
(`fr` or `en`), then the system locale. The full catalogue is in
[`errors.md`](errors.md).

## `charpente ask`

```
charpente ask [--file PATH] <question, free text, any words including ones starting with '->
```

Asks the configured AI provider a question. If a `.charpente` workspace
can be found (same discovery rules as every other command), its name and
target list are included as context. Prints `(using <provider>)` then the
answer.

Without any provider configured, prints a plain explanation of how to
configure one instead of an error — see [AI features](#ai-features-1).

`ask`'s question is deliberately *not* parsed by the same mechanism as
other commands' flags: a natural-language question can legitimately start
with a dash (`charpente ask "--verbose isn't printing anything"`), so
everything after an optional `--file PATH` is treated as literal question
text, dashes included. `charpente ask --help` / `-h` still shows usage,
as a special case.

## AI features

Charpente works completely without any AI provider configured — installing
it with just `pip install charpente` (no `[ai]` extra) pulls in zero AI
dependency, and every command above works fully. Configuring a provider
unlocks `charpente ask` and `--ai-diagnose`.

Set one of these environment variables — the first match, in this order,
wins:

| Provider | Environment variable | Extra dependency |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY=sk-ant-...` | `pip install "charpente[ai]"` |
| OpenAI | `OPENAI_API_KEY=sk-...` | `pip install "charpente[ai]"` |
| Local (Ollama, llama.cpp server, LM Studio, any OpenAI-compatible server) | `CHARPENTE_AI_URL=http://localhost:11434/v1` | none — stdlib `urllib` only |

`CHARPENTE_AI_PROVIDER=anthropic\|openai\|local\|none` forces a specific
choice regardless of what else is set (`none` explicitly disables AI even
if a key is present). `CHARPENTE_AI_MODEL` overrides the default model for
whichever provider ends up active.

`--ai-diagnose` is opt-in on every single `build` invocation where you
want it — there's no "always diagnose" setting — because every call costs
a request and sends the compiler/linker's error output (which can include
snippets of your source) to whichever provider you've configured.
