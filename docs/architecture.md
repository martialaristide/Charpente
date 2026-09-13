# Architecture

For anyone reading the code or extending it. Matches `charpente/`'s actual
module layout, not an aspirational one.

```
charpente/
  dsl/
    model.py       # plain dataclasses: Workspace, Target, Kind, Language, OS. No behavior.
    api.py          # the public DSL: Workspace/Target context managers over module state
    trust.py        # consent before exec()'ing a .charpente file
    loader.py       # wires the above together: trust check -> exec() -> hand back a Workspace
  platform.py        # host OS detection (one function)
  toolchains.py       # PATH-based compiler discovery, per host OS
  flags.py            # pure functions: Toolchain + Target -> compile/link argv (no subprocess call)
  builder.py           # orchestrates a build: resolve sources, incremental check, run compile/link
  installer.py          # pure functions: platform installer script/staging generation (no subprocess call)
  safe_name.py           # path-traversal-safe name validation, enforced in Target/Workspace.__post_init__
  ai/
    provider.py         # AIProvider interface + Anthropic/OpenAI/Local/Null implementations
    diagnose.py          # ai.diagnose(): build-error-specific prompt, used by `build --ai-diagnose`
  commands/
    _common.py           # shared find-workspace/load/resolve-target/pick-toolchain plumbing
    init.py, build.py, run.py, clean.py, test.py, package.py, ask.py
  cli.py                  # `charpente <command>` dispatch
  workspace_finder.py       # locates the .charpente file a command should use
```

## The load path: `.charpente` file to `Workspace`

1. `commands/_common.py::load()` calls `workspace_finder.find_workspace_file()`
   (explicit `--file`, or auto-discovery upward from cwd).
2. `dsl/loader.py::load_workspace()`:
   - `dsl/trust.py::ensure_trusted()` — may prompt, may raise
     `TrustRequiredError`/`TrustDeniedError`.
   - Builds an exec namespace from `dsl/api.py.__all__` (`Workspace`,
     `Target`, `Kind`, `Language`, `OS`, `current_workspace`).
   - `exec()`s the file's source against that namespace.
   - Reads back `dsl/api.py::last_loaded_workspace()` — deliberately
     *not* `current_workspace()`, which is `None` again by the time
     `exec()` returns (`Workspace.__exit__` clears it; `last_loaded_workspace()`
     is set by that same `__exit__`, one step earlier, specifically so the
     loader has something to read after the `with` block has already closed).
3. Returns a `dsl/model.py::Workspace` dataclass — the DSL layer's job is
   done; nothing below this point imports from `dsl/`.

## The build path: `Workspace` to a compiled binary

1. `commands/build.py` calls `builder.py::build_workspace()`, which:
   - Computes build order via `Workspace.build_order()` (topological sort,
     raises on an unknown dependency or a cycle, naming it).
   - For each target, calls `build_target()`.
2. `build_target()`, per source file:
   - `Target.resolved_sources()` (glob + exclude, pure — no filesystem
     writes).
   - Timestamp check (`_needs_rebuild`): object newer than source ⇒ skip.
     This is the *only* incremental strategy — no per-header dependency
     tracking (a known, documented gap, not an oversight).
   - `flags.py::compile_args()` computes the argv (MSVC-style vs
     GNU-style, chosen by `flags.family(toolchain)`); `_run()` invokes it
     via the injectable `run` parameter (defaults to `subprocess.run`,
     always `shell=False`).
3. Linking: `flags.py::link_args()`, with `library_dirs` set to each
   `depends_on` target's own `build_dir()` — this is what lets
   `t.links(["some_other_target"])` resolve without the `.charpente` file
   knowing where Charpente puts build output.
4. `commands/run.py`/`package.py`/`test.py` build a *single* target rather
   than the whole workspace, but still need that target's dependencies
   built first for the requested config — `builder.py::dependency_closure()`
   computes that subset, passed to `build_workspace(..., only=closure)`
   rather than calling `build_target()` directly (a real bug, fixed after
   being caught by `docs/tutorial.md`'s worked example: a config that had
   never been through a full `build_workspace()` call before would
   otherwise fail to link against a dependency that was never built for
   it).

## Why things are split the way they are

- **`flags.py`/`installer.py` never call `subprocess` themselves.** Both
  are pure functions: `(Toolchain, Target, paths) -> argv` /
  `(paths, Target) -> script text`. This is what makes them trivially unit
  testable (assert on the returned list/string) without mocking anything,
  and it's also what makes `builder.py`'s own tests possible: `build_target()`
  takes an injectable `run` callable, so a test can hand it a fake that
  creates the files a real compiler would (see `tests/test_builder.py`'s
  `_fake_compiler()`) and assert on exactly which argv reached it, in
  which order.
- **`dsl/` doesn't know about builders, and `builder.py` doesn't know
  about the DSL's exec/trust machinery.** The `Workspace`/`Target`
  dataclasses in `dsl/model.py` are the only thing that crosses that
  boundary — plain data, no methods that reach into either side.
- **`commands/_common.py` exists so commands stay small.** Every command
  needs "find the workspace file, load it, pick a toolchain, resolve
  which target" — written once, not seven times.

## Testing philosophy

Two layers, both exercised for real, not just one or the other:

- **Pure unit tests** (`test_model.py`, `test_flags.py`, `test_toolchains.py`,
  `test_installer.py`, ...): no subprocess, no real compiler, fast,
  precise about exactly what argv/text is produced.
- **Real end-to-end tests** (`test_cli_integration.py`, the dependency-closure
  tests in `test_builder.py`/`test_cli_integration.py`): actually invoke
  the host compiler, actually build and run a binary. Automatically
  skipped (`@requires_compiler`) if none is found on `PATH` — but on a
  machine that has one, these are what catch the bugs a mock can't: an
  invalid `pathlib` glob pattern, a template string colliding with
  literal braces, `argparse.REMAINDER` swallowing a `--` separator, a
  dependency that links in unit tests (mocked) but not for real (the
  library search path wasn't actually where the mock assumed). Every one
  of those was found this way, not by code review.

If you're adding a feature that touches subprocess invocation, path
construction, or anything platform-specific: add a real end-to-end test
alongside the unit test, even if it'll only run on your own machine's CI
leg. It will very likely find something the unit test didn't.
