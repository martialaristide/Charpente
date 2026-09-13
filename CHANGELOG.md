# Changelog

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
