# Troubleshooting

Organized by the actual message you'd see, so you can search this page
for it.

## `No C/C++ compiler found for <os>`

`charpente.toolchains.pick_default()` couldn't find any known compiler on
`PATH`. Install one:

- **Windows**: Visual Studio Build Tools (`cl.exe`), or LLVM (`clang-cl.exe`),
  or MSYS2/MinGW (`gcc.exe`+`g++.exe`) — any one, and make sure its `bin`
  directory is actually on `PATH` (a fresh MSYS2 install often isn't, by
  default).
- **Linux**: `sudo apt install build-essential` (Debian/Ubuntu) or the
  equivalent for your distro, or `clang`+`clang++`.
- **macOS**: `xcode-select --install`.

Then open a *new* terminal (PATH changes don't apply to already-running
shells) and retry.

## `Refusing to run this Charpente workspace file without confirmation`

Non-interactive session (no attached terminal — a CI job, typically), and
this exact file's content has never been approved. Either:

- Run the same command once interactively on a machine where you can
  answer the `y/N` prompt, so the approval gets recorded in
  `~/.charpente/trusted_files.json` — then re-run non-interactively, or
- Set `CHARPENTE_TRUST_ALL=1` in that environment, if you trust the
  source of this repository (this is what Charpente's own CI does).

See [`security.md`](security.md) for why this check exists at all.

## `Target 'X' has no source files (check its sources()/exclude() patterns)`

`Target.resolved_sources()` matched nothing. Common causes:

- A pattern that doesn't actually match anything from the workspace file's
  directory — patterns in `.sources([...])` are resolved relative to
  where the `.charpente` file lives, not your current shell directory.
- `**/*.cpp` vs `**.cpp`: Python's `pathlib.Path.glob()` requires `**` to
  be its own path component (`src/**/*.cpp`, not `src/**.cpp`) — the
  latter raises a `ValueError` from `pathlib` itself, not this message,
  but it's the same class of mistake.
- An `.exclude([...])` pattern that happens to remove everything
  `.sources([...])` matched.

## A link error mentioning "undefined reference" / "unresolved external symbol"

Almost always one of:

- Missing `.links([...])` for a target you `.depends_on()` — `depends_on`
  only controls *build order*, it does not by itself add a linker flag.
  See [`dsl-reference.md`](dsl-reference.md#dependencies-and-linking).
- Missing `.links([...])` for a system library your code actually calls
  into (`.links(["m"])` for `<cmath>` functions on some GNU-style setups,
  `.links(["ws2_32"])` for Windows sockets, etc.) — this is inherent to
  the underlying compiler/linker, not specific to Charpente.
- A genuine typo in a function/class name, same as with any build tool.

Try `charpente build --ai-diagnose` (with a provider configured — see
[`cli-reference.md`](cli-reference.md#ai-features)) for a suggested cause
specific to your actual error text.

## A build looks stale after editing a header (`.h`/`.hpp`)

Expected, for now: incremental builds are timestamp-based only (an object
file newer than its `.cpp` source is skipped) — there's no per-header
dependency tracking yet, so Charpente doesn't know that `foo.cpp` needs
recompiling just because `foo.h` (which it `#include`s) changed. Run
`charpente clean` and rebuild. See `charpente/builder.py`'s module
docstring for the plan to fix this properly (`-MMD`/`-showIncludes`-based
dependency files).

## `iscc`/`dpkg-deb`/`pkgbuild` not found on PATH

`charpente package --format installer` still writes the installer
script/staging tree to `dist/` even without the platform tool — the
message names the exact command to finish the job once you have it
installed. See [`cli-reference.md`](cli-reference.md#building-a-real-installer)
for what each platform needs.

## `AI features are not configured`

Set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `CHARPENTE_AI_URL` (a local
OpenAI-compatible server). See [`cli-reference.md`](cli-reference.md#ai-features)
for the full table, including which need `pip install "charpente[ai]"`.

## Still stuck

Open an issue at
[github.com/martialaristide/Charpente/issues](https://github.com/martialaristide/Charpente/issues)
with the exact command and output — this project is young enough that
"the error message wasn't clear enough" is itself useful information, not
just the underlying problem.
