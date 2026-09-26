# Charpente

A cross-platform C/C++ build system driven by a Python DSL. Write a
`.charpente` file, get a real compile + link on Windows, Linux, or macOS —
no CMake, no Makefiles, no generated intermediate project files.

```python
from charpente import *

with Workspace("HelloWorld") as ws:
    ws.configurations(["Debug", "Release"])

    with Target("hello") as t:
        t.kind(Kind.EXECUTABLE)
        t.language(Language.CPP)
        t.standard("c++17")
        t.sources(["src/**/*.cpp"])
```

```
$ charpente build && charpente run
Building HelloWorld (Debug, gcc)...
  [ok]         hello -> build/Debug/hello/hello
Running build/Debug/hello/hello...
Hello, world!
```

## Quality and releases

`charpente check` runs a configurable quality gate (build, format, secrets, warnings, tests, sanitizers, coverage, licenses, SBOM...) that
Git hooks, `charpente commit`/`push`/`pr` and CI all share; `charpente release` prepares a signed release with checksums and provenance.
See [docs/quality.md](docs/quality.md) and [docs/git.md](docs/git.md).

## Cross-compilation

`charpente toolchain install zig` then `charpente build --platform linux-arm64` (or `windows-arm64`,
`macos-arm64`, `wasm32-wasi`, ...). `charpente platforms` lists what can be built and how well it is
verified; see [docs/platforms.md](docs/platforms.md).

## Status

Charpente is a young, from-scratch project (version **0.13, alpha**) — not a fork or a rename of any prior build tool, no code shared with one. It is a build **engine**
(exact incremental builds, a content-addressed cache that can be shared by a team, reproducible builds), a **package manager** and curated **kits**, and a **studio** (a local web app, a VS Code extension,
a build server, debugging). What is verified and what is not is written per feature in [docs/stability.md](docs/stability.md); in short:

- **Verified for real, on one machine (Windows 10, MinGW-w64)**: builds and cache, reproducible builds, budgets, cross builds with zig (mostly *built*, not *executed*), Android (a real emulator), the Studio in a real
  browser (Edge), clangd and gdb, CMake import, Ninja/CMake generation, hot reload, the shared cache.
- **Tested but not against the real thing**: Visual Studio projects, multi-device deploy with several devices (simulated; one real emulator was tried), the AI assistant (no real provider was ever called), the VS Code extension (not loaded in a live VS Code).
- **Not done**: remote execution, an Xcode project, a compiled desktop app and installers, precompiled headers and C++20 modules.
- **Never verified on Linux or macOS**, and the CI workflow (`.github/workflows/tests.yml`: Windows, Linux, macOS, Python 3.9 and 3.12) has **never run on this work** (it was not pushed; only Python 3.12 was used here): that is why the version is `0.x` and nothing is called stable.

## Where to start

`charpente setup` checks your machine and offers what is missing; then `charpente init hello --template console`, `cd hello`, `charpente build`, `charpente run --target hello`. The
[guide](docs/guide.md) ([en français](docs/guide.fr.md)) walks through everything else.

## Installation

Requires Python 3.9+ and a C/C++ compiler for your target platform:

- **Windows**: Visual Studio Build Tools (`cl.exe`), or LLVM (`clang-cl.exe`), or MSYS2/MinGW (`gcc`/`g++`) — any one of these, on `PATH`.
- **Linux**: `gcc`/`g++` (e.g. `apt install build-essential`) or `clang`/`clang++`.
- **macOS**: Xcode Command Line Tools (`xcode-select --install`), which provides Apple Clang.

```bash
git clone https://github.com/martialaristide/Charpente.git
cd Charpente
pip install -e .

charpente --version
```

(Not yet published to PyPI — `pip install charpente` isn't available until
it is. Installing from a clone with `pip install -e .` is the supported
path today. The package itself builds and passes `twine check`; see
[docs/setup-and-uninstall.md](docs/setup-and-uninstall.md), which also covers `charpente setup` and `charpente self uninstall`.)

## Quickstart

```bash
charpente init MyApp          # scaffolds MyApp.charpente + src/main.cpp
charpente build                # compiles it
charpente run                  # runs the result
charpente test                 # builds and runs any Kind.TEST targets
charpente package --config Release   # zips the build output
charpente clean                # removes build/
```

The first time you run a command against a `.charpente` file you haven't
approved before, Charpente asks for confirmation — see
[The trust model](#the-trust-model) for why, and how to skip the prompt in
CI.

## The DSL

A `.charpente` file is plain Python, executed as-is (see
[The trust model](#the-trust-model)) — `Workspace` and `Target` are context
managers over a small model; there's no separate parser or grammar to learn.

### `Workspace`

```python
with Workspace("Name") as ws:
    ws.configurations(["Debug", "Release"])   # default if omitted
```

### `Target`

```python
with Target("name") as t:
    t.kind(Kind.EXECUTABLE)          # or STATIC_LIBRARY, SHARED_LIBRARY, TEST
    t.language(Language.CPP)         # or Language.C
    t.standard("c++17")              # passed as -std=c++17 / /std:c++17
    t.sources(["src/**/*.cpp"])      # glob patterns, relative to the workspace file
    t.exclude(["src/experimental/**/*.cpp"])
    t.include_dirs(["include"])
    t.defines(["MY_MACRO=1"])
    t.links(["m"])                   # -lm / m.lib depending on toolchain
    t.depends_on(["other_target"])   # built first, in workspace-wide dependency order
    t.compile_flags(["-Wall"])       # passed through verbatim
    t.link_flags(["-static"])
```

Every `Target` method returns `self`, so calls can be chained:
`t.kind(Kind.EXECUTABLE).language(Language.CPP).sources([...])`.

A target's name becomes part of output file paths (`build/<config>/<name>/...`),
so it's validated at declaration time — no path separators, no `..`, no
control characters. A name that fails validation raises immediately, with
the exact problem named, rather than silently producing a broken path
later.

### Multiple targets and dependencies

```python
with Workspace("Game") as ws:
    with Target("engine") as t:
        t.kind(Kind.STATIC_LIBRARY)
        t.sources(["engine/**/*.cpp"])

    with Target("game") as t:
        t.kind(Kind.EXECUTABLE)
        t.depends_on(["engine"])
        t.sources(["game/**/*.cpp"])
        t.links(["engine"])
```

`charpente build` builds targets in dependency order automatically
(`engine` before `game` here), and detects cycles or references to unknown
targets at build time with a message naming the exact problem.

## CLI reference

| Command | What it does |
|---|---|
| `charpente init NAME [--dir DIR]` | Scaffolds `NAME.charpente` + `src/main.cpp` |
| `charpente build [--config Debug\|Release] [--keep-going] [--ai-diagnose]` | Compiles every target, in dependency order |
| `charpente run [--target NAME] [--config ...] [--no-build] [-- program args]` | Builds (unless `--no-build`) then executes the target |
| `charpente test [--config ...]` | Builds and runs every `Kind.TEST` target, reports pass/fail |
| `charpente package [--target NAME] [--config Release] [--format zip\|installer] [--version X.Y.Z] [--output PATH]` | Zips the build output, or builds a real platform installer |
| `charpente clean` | Removes `build/` |
| `charpente ask "question"` | Asks the configured AI provider a question, with workspace context if one is found |

Every command accepts `--file PATH` to point at a specific `.charpente`
file instead of relying on auto-discovery (the single `.charpente` file in
the current directory or the nearest parent that has one).

### Building a real installer

```bash
charpente package --format installer --config Release --version 1.2.3
```

Per platform, this needs the platform's own packaging tool on `PATH`:

| Platform | Tool | Output | If the tool is missing |
|---|---|---|---|
| Windows | [Inno Setup](https://jrsoftware.org/isinfo.php) (`iscc`) | `dist/<target>-setup.exe` | The `.iss` script is still written to `dist/`; install Inno Setup and run the printed `iscc ...` command yourself |
| Linux | `dpkg-deb` (usually preinstalled) | `dist/<target>.deb` | The staging tree (`DEBIAN/control` + binary) is still written to `dist/`; run the printed `dpkg-deb ...` command on a Debian/Ubuntu machine |
| macOS | `pkgbuild` (via Xcode Command Line Tools) | `dist/<target>.pkg` | The staging tree is still written to `dist/`; run the printed `pkgbuild ...` command on macOS |

`--format zip` (the default) needs no external tool on any platform.

## AI features

Charpente works completely without any AI provider configured — `pip
install -e .` alone installs zero AI dependency. Configure one and two
things unlock:

- `charpente ask "why does my build fail?"` — a conversational assistant, given the current workspace as context when one is found.
- `charpente build --ai-diagnose` — on a target failure, sends the compiler/linker's error output to the provider and prints its suggested cause and fix. **Never automatic**: it only runs when this flag is passed, because every call costs a request and sends error output (which can include source snippets) to a third party.

Pick a provider with environment variables — the first match wins:

| Provider | How to enable | Extra dependency |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY=sk-ant-...` | `pip install -e ".[ai]"` |
| OpenAI | `OPENAI_API_KEY=sk-...` | `pip install -e ".[ai]"` |
| Local (Ollama, llama.cpp server, LM Studio, ...) | `CHARPENTE_AI_URL=http://localhost:11434/v1` | none — stdlib only |
| None (default) | nothing set | — |

`CHARPENTE_AI_PROVIDER=anthropic\|openai\|local\|none` forces a specific
choice regardless of what else is set. `CHARPENTE_AI_MODEL` overrides the
default model for whichever provider is active.

## The trust model

**A `.charpente` file executes as unrestricted Python — this is not a
sandbox.** `import os`, `subprocess`, disk and network access are all just
as valid inside a `.charpente` file as in any script you'd run by hand.
That's a deliberate design choice (a native DSL, in the spirit of a
`SConstruct` or `setup.py`), not an oversight, and it means running someone
else's `.charpente` file carries exactly the same trust implications as
running a script you downloaded and didn't read.

To make that explicit rather than silent, Charpente asks for confirmation
the first time it's about to execute a `.charpente` file whose exact
content it hasn't seen approved before (tracked by content hash — editing
an approved file asks again). Your answer is remembered locally in
`~/.charpente/trusted_files.json`; nothing is sent anywhere.

- Interactive session, first time seeing a file: you're asked `y/N`.
- Interactive session, previously approved (unchanged) file: no prompt.
- Non-interactive session (CI) with no prior approval and no bypass: **fails
  closed** with a clear message, rather than hanging on a prompt nobody can
  answer or silently proceeding.
- `CHARPENTE_TRUST_ALL=1` skips the check entirely — set this in CI for a
  repository you trust.

## Documentation

This README is the overview. For more depth:

- [`docs/tutorial.md`](docs/tutorial.md) — a hands-on walkthrough: a
  library target, a dependency, a test, packaging, in about 15 minutes.
- [`docs/dsl-reference.md`](docs/dsl-reference.md) — every `Workspace`/`Target`
  method, `Kind`/`Language`/`OS`, name validation rules.
- [`docs/cli-reference.md`](docs/cli-reference.md) — every command and flag,
  including `--format installer` and the AI provider table.
- [`docs/security.md`](docs/security.md) — the trust model in full, and
  every other security-relevant design choice (no `shell=True`, path-safe
  names, AI calls always opt-in).
- [`docs/architecture.md`](docs/architecture.md) — internals, module by
  module, for anyone reading the code or contributing.
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — common error
  messages, organized so you can search this page for the exact text you're seeing.
- [`docs/guide.md`](docs/guide.md) / [`docs/guide.fr.md`](docs/guide.fr.md) — the complete guide, in English and French.
- [`docs/stability.md`](docs/stability.md) — what is verified, tested, experimental or not done.
- Engine: [shared cache](docs/shared-cache.md), [reproducible builds and budgets](docs/reproducible-and-budgets.md), [resources and eco mode](docs/resources.md),
  [import and generate](docs/import-and-generate.md), [hot reload](docs/hot-reload.md), [API docs](docs/api-docs.md), [multi-device deploy](docs/multi-device.md).
- Platforms and tools: [platforms](docs/platforms.md), [Android](docs/android.md), [packages](docs/packages.md), [kits](docs/kits.md), [templates](docs/templates.md),
  [quality gate](docs/quality.md), [Git and releases](docs/git.md), [server](docs/serve.md), [Studio](docs/studio.md), [VS Code](docs/vscode.md), [debugging](docs/debugging.md), [AI](docs/ai.md).
- Errors: [`docs/errors.md`](docs/errors.md) (generated from the catalogue; `charpente explain CHxxxx`).

## Development

```bash
pip install -e ".[dev]"
pytest
```

The test suite includes end-to-end tests that invoke the real host
compiler (skipped automatically if none is found on `PATH`) alongside
fully mocked unit tests — see `tests/test_cli_integration.py`. Every bug
fixed in this project's history so far (see `CHANGELOG.md`) was caught by
one of these real-compiler tests, not by code review or a mock — if
you're adding anything that touches subprocess invocation or path
construction, add one alongside the unit test.

## License

Apache-2.0. See `LICENSE`.
