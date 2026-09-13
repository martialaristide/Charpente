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
  keep-going mode.
- CLI: `init`, `build`, `run`, `clean`, `test`, `package` (zip archive of
  build output), `ask`.
- AI: pluggable provider (Anthropic, OpenAI, a local OpenAI-compatible
  endpoint, or none) selected by environment variable, with zero AI
  dependency required for the rest of the tool to work.
  `charpente build --ai-diagnose` asks the configured provider to
  diagnose a compile/link failure; `charpente ask` is a general assistant
  with workspace context.
- Path-traversal-safe target/workspace names, validated at declaration
  time rather than wherever a path happens to be built later.

Known limitations, tracked rather than hidden: no per-header dependency
tracking (timestamp-only incremental builds), `package` produces a zip
rather than a platform installer, Linux/macOS builds are unit-tested but
not yet exercised against a real compiler in this project's own CI,
desktop targets only (no mobile/web/console).
