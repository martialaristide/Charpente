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

## Status

This is a young, from-scratch project — not a fork or a rename of any
prior build tool, no code shared with one. What's implemented today,
honestly:

| Area | State |
|---|---|
| DSL (Workspace/Target, dependency resolution, `.charpente` loading) | ✅ Working, tested |
| Windows build (MSVC, clang-cl, or MinGW) | ✅ Working, tested with a real compiler |
| Linux build (GCC or Clang) | ✅ Implemented, unit-tested; not yet run against a real Linux compiler in this environment |
| macOS build (Apple Clang) | ✅ Implemented, unit-tested; not yet run against a real macOS compiler in this environment |
| Incremental builds | ✅ Timestamp-based only (object newer than source ⇒ skip). **No per-header dependency tracking yet** — editing a header won't trigger a rebuild of the `.cpp` files that include it. Run `charpente clean` if a build looks stale. |
| `charpente init/build/run/clean/test/package` | ✅ Working |
| `package` | ✅ `.zip` by default. `--format installer` generates a real Inno Setup `.iss`/.deb staging/.pkg staging and builds it if `iscc`/`dpkg-deb`/`pkgbuild` is on PATH (otherwise leaves the script/staging with the exact command to finish by hand). Generation logic is unit-tested on all three platforms; actual `iscc`/`dpkg-deb`/`pkgbuild` invocation has only been exercised where the tool happens to be installed |
| `charpente ask` / `--ai-diagnose` | ✅ Working, fully optional (see [AI features](#ai-features)) |
| Precompiled headers, C++20 modules, shared library exports on Windows (`__declspec`), cross-compilation | ❌ Not yet |
| Mobile/web/console targets (Android, iOS, WASM, ...) | ❌ Not yet — desktop only for now |

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
path today.)

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

## Development

```bash
pip install -e ".[dev]"
pytest
```

The test suite includes end-to-end tests that invoke the real host
compiler (skipped automatically if none is found on `PATH`) alongside
fully mocked unit tests — see `tests/test_cli_integration.py`.

## License

Apache-2.0. See `LICENSE`.
