# Charpente

A cross-platform C/C++ build system driven by a Python DSL. Work in progress —
the DSL core (workspace/target loading, dependency resolution) is implemented
and tested; the compiler-invoking build engine, CLI, and AI features are
being built next. See `CHANGELOG.md` (once it exists) for what actually
works today rather than what's planned.

## Status

This project is a from-scratch rewrite: it does not share code with, and is
not a fork of, any prior build tool. See `docs/` for design notes as they're
written.

## License

Apache-2.0. See `LICENSE`.
