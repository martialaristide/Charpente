# Architecture

For anyone reading the code or extending it. Matches `charpente/`'s actual
module layout, not an aspirational one. Decisions and their trade-offs are
recorded in [`adr/`](adr/).

```
charpente/
  errors.py            # ChError: stable CHxxxx codes, localised message + fix
  i18n/                # en.py / fr.py: the message catalogue (plain Python dicts)
  dsl/
    model.py           # plain dataclasses: Workspace, Target, Overlay, Rule, Kind, Language, OS
    api.py             # the public DSL: Workspace/Target/Rule context managers over module state
    resolve.py         # per (config, platform, toolchain): overlays + `uses` -> an ordinary Target (ADR 0009)
    toml_loader.py     # charpente.toml: the data-only form
    trust.py           # consent before exec()'ing a .charpente file
    loader.py          # trust check -> exec() -> hand back a Workspace
  lint.py, migrate.py  # static analysis of a .charpente file; v0.1.0 -> v2 rewrites
  pkg/                 # Charpente Pkg: recipes, resolver, lock, install, materialize, vendor, mirror, audit, sbom
  platform.py          # host OS detection
  toolchains.py        # PATH-based compiler discovery, per host OS
  flags.py             # pure: Toolchain + Target -> compile/link argv
  installer.py         # pure: platform installer script/staging generation
  builder.py           # build_workspace(): plan -> (fast path | engine) -> per-target results
  core/                # the engine
    process.py         # the ONLY place a process is started (ADR 0001)
    hashing.py         # BLAKE3 (blake2b fallback), algorithm-prefixed digests (ADR 0004)
    actions.py         # Action: command + inputs + outputs + env + tool (pure data)
    graph.py           # ActionGraph: edges, topological order, critical path
    planner.py         # Workspace -> ActionGraph
    depscan.py         # header discovery: -MMD depfiles, /showIncludes
    diagnostics.py     # compiler output -> structured diagnostics
    state.py           # SQLite: last-success record per action, file-digest memo
    statcache.py       # cheap file metadata (scandir batches on Windows)
    globber.py         # sources(["src/**/*.cpp"]) on os.scandir
    toolid.py          # identity of a tool: path + version + binary digest
    cache.py           # content-addressed local cache with header manifests
    engine.py          # freshness -> cache -> execute, parallel scheduler
    fastpath.py        # "nothing changed" answered from metadata alone (ADR 0007)
    history.py         # SQLite build history (an event subscriber)
    compdb.py          # compile_commands.json
  events/              # EventBus, the event table, JSON Schema generation (ADR 0005)
  output/              # subscribers: plain/rich terminal, JSON Lines, session log, GitHub annotations
  hooks.py             # @ws.on(Event.X), notify(), .charpente/hooks/ scripts
  semver.py            # versions and constraints (^, ~, ranges)
  modules/             # the module system (ADR 0008)
    api.py             # module API 2.0: manifest, capabilities, extension interfaces
    manifest.py        # charpente-module.toml parsing/validation
    registry.py        # ExtensionRegistry: what loaded modules registered
    capabilities.py    # guarded ctx.process / ctx.fs / ctx.net
    store.py           # ~/.charpente/modules: installed modules, approvals, registries
    installer.py       # add/update/remove from folder, zip, URL, registry
    signing.py         # tree digest, Ed25519 (RFC 8032), trust store
    loader.py, runtime.py   # defensive loading; the process-wide registry
    builtin.py         # the six built-in toolchains, registered like any module's
    conformance.py     # `charpente module check`
    official/          # bundled modules (charpente-notify), off until enabled
  ai/                  # provider interface + diagnose
  commands/            # one file per command; _common.py, _session.py shared
  cli.py               # `charpente <command>` dispatch
```

## The load path: `.charpente` file to `Workspace`

1. `commands/_common.py::load()` calls `workspace_finder.find_workspace_file()`
   (explicit `--file`, or auto-discovery upward from cwd).
2. `dsl/loader.py::load_workspace()`:
   - `dsl/trust.py::ensure_trusted()` — may prompt, may raise `CH1006`/`CH1007`.
   - Builds an exec namespace from `dsl/api.py.__all__`.
   - `exec()`s the file's source, then reads back `last_loaded_workspace()`
     (`current_workspace()` is `None` again once the `with` block has exited).
3. Returns a `dsl/model.py::Workspace` — the DSL layer's job is done.

## The engine

`builder.build_workspace()` is the stable entry point (its v0.1.0 signature
and semantics are unchanged). Inside:

1. **Fast path** (`core/fastpath.py`). Compute a context digest (config,
   toolchain identity, target definitions, the list of source files) and compare
   the recorded (mtime, size) of every file read or written by the last
   successful build. Identical: done, without planning anything (≈ 0.25 s for
   10 000 files). Anything else, including a mere `touch`: continue.
2. **Plan** (`core/planner.py`). Each source becomes a *compile* action; each
   target a *link* or *archive* action that depends on its objects and, through
   `depends_on`, on the final action of its dependencies; a library named in
   `links()` is also an *input* of the link, so a changed library relinks the
   executable. Objects mirror the source tree (`obj/src/x/util.cpp.o`), so two
   `util.cpp` never collide. Commands run with the workspace directory as cwd, so
   `include_dirs(["include"])` means what it says whatever your shell's cwd is.
3. **Run** (`core/engine.py`), in parallel with the longest chain first:
   - *freshness*: compare the action to its record (command, tool identity,
     input contents, discovered headers, outputs on disk);
   - *cache*: on a miss, ask the cache under the content-derived key;
   - *execute*: run, parse the depfile, store in the cache and the state DB.
   Freshness runs inline on the scheduler thread (cheap); only real work goes
   to worker threads.
4. **Fold** the per-action results into per-target results.

Every step emits events; nothing in `core/` prints.

### Keys and the cache in one paragraph

`key1 = H(kind, argv, cwd, keyed env, tool identity, input digests, output names)`.
A compilation's full key adds the *contents* of the headers it read:
`key2 = H(key1, [(header, digest)…])`. The cache stores, per `key1`, the header
sets seen so far (a *manifest*); a lookup re-hashes the current contents of
each set and asks for that `key2`. Change a header and `key2` changes: a miss,
never a stale hit. Details and limits: [ADR 0006](adr/0006-cles-daction-et-cache.md).

## Errors and languages

Every user-facing error is a `ChError(code, **params)`. The text lives in
`i18n/en.py` and `i18n/fr.py` (same codes, same placeholders — a test enforces
it). `charpente explain CHxxxx` prints cause, fix and explanation;
`docs/errors.md` is generated from the catalogue and checked for freshness by a
test. `CHARPENTE_LANG` (else the system locale) picks the language.

## Events

The engine and commands emit typed events; the terminal, `--output jsonl`, the
session log, the history database (and later Studio, hooks, notifiers) are
subscribers. The table in `events/types.py` is the single source of truth for
`docs/events/` (JSON Schemas + reference), also checked for freshness. See
[ADR 0005](adr/0005-bus-evenements.md).

## Why things are split the way they are

- **`flags.py`, `installer.py`, `core/graph.py`, `core/planner.py`,
  `core/depscan.py`, `core/diagnostics.py` are pure**: they compute, they do not
  run anything. Tests assert on returned values with no compiler.
- **Processes start in exactly one place** (`core/process.py`); a test fails if
  another module imports `subprocess` or enables a shell. Tests inject a fake
  `runner` with the `subprocess.run` call shape (`tests/helpers.py::FakeToolchain`).
- **`dsl/` doesn't know about builders, and `builder.py` doesn't know about the
  DSL's exec/trust machinery.** `Workspace`/`Target` are plain data.
- **`commands/_common.py` and `commands/_session.py` exist so commands stay
  small**: locate/load/pick a target/toolchain, and open the event bus with its
  standard subscribers.

## Testing philosophy

Two layers, both exercised for real:

- **Pure and fake-runner unit tests**: fast, precise about exactly what is
  computed and which commands reach the (fake) compiler.
- **Real end-to-end tests** (`tests/test_cli_integration.py`,
  `tests/test_cli_engine_real.py`): actually invoke the host compiler, build and
  run a binary. Automatically skipped if none is found — but on a machine that
  has one, these catch what a mock cannot: an invalid glob, a template colliding
  with literal braces, `argparse.REMAINDER` swallowing `--`, a header edit that
  must recompile exactly two files.

If you add a feature that touches process invocation, path construction or
anything platform-specific: add a real end-to-end test alongside the unit test.
It will very likely find something the unit test didn't.

`tests/conftest.py` pins the language to English and redirects
`CHARPENTE_HOME` and the cache to a temporary folder for every test: the suite
never touches a developer's real `~/.charpente`.

## Benchmarks

`python bench/noop_build.py --files 10000` measures clean, no-op, one-source
and one-header builds on a synthetic project with an in-process fake compiler
(so it measures Charpente, not gcc). Results and the resulting decision on a
native core: [ADR 0010](adr/0010-coeur-python-ou-rust.md).
