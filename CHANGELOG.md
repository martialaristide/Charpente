# Changelog

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
