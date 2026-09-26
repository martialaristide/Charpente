# DSL reference

A `.charpente` file is plain Python (see [`security.md`](security.md) for
what that means in practice). `from charpente import *` brings in
everything below — nothing else needs importing to write a workspace.

## `Workspace`

```python
with Workspace(name: str) as ws:
    ...
```

Opens a new workspace named `name`. Everything declared inside the `with`
block (via `Target(...)`) belongs to this workspace. Workspaces cannot be
nested — opening a second `Workspace(...)` while one is already open raises
`RuntimeError`.

| Method | Signature | Effect |
|---|---|---|
| `.configurations(names)` | `Iterable[str] -> Workspace` | Sets the list of build configurations (default: `["Debug", "Release"]` if never called) |

`ws.configurations(...)` returns `ws` itself, so it chains:
`Workspace("X").configurations([...])` — though since `Workspace` is used
as a context manager, you'll usually call it as a statement inside the
`with` block instead.

The workspace's `name` is validated when the object is constructed (see
[Name validation](#name-validation) below) — an invalid name raises
`ValueError` immediately, before anything else in the file runs.

## `Target`

```python
with Workspace("W") as ws:
    with Target(name: str) as t:
        ...
```

Declares one buildable unit inside the *currently open* workspace.
Declaring a `Target` outside any `Workspace` block raises `RuntimeError`.
On `__exit__`, the target is added to the enclosing workspace — declaring
two targets with the same name in one workspace raises `ValueError`
("already defined").

Every method below returns `self`, so calls chain:

```python
t.kind(Kind.EXECUTABLE).language(Language.CPP).standard("c++20")
```

| Method | Signature | Effect |
|---|---|---|
| `.kind(value)` | `Kind -> Target` | What this target builds (default `Kind.EXECUTABLE`) |
| `.language(value)` | `Language -> Target` | `Language.C` or `Language.CPP` (default `Language.CPP`) — determines which compiler (`c_compiler`/`cxx_compiler`) is used |
| `.standard(value)` | `str -> Target` | Passed as `-std=<value>` (GNU-style toolchains) or `/std:<value>` (MSVC-style) — e.g. `"c++17"`, `"c++20"`, `"c11"` (default `"c++17"`) |
| `.sources(patterns)` | `Iterable[str] -> Target` | Glob patterns, resolved relative to the workspace file's directory (accumulates across multiple calls) |
| `.exclude(patterns)` | `Iterable[str] -> Target` | Glob patterns to remove from the matched source set |
| `.include_dirs(dirs)` | `Iterable[str] -> Target` | Added as `-I<dir>` / `/I<dir>` |
| `.defines(macros)` | `Iterable[str] -> Target` | Added as `-D<macro>` / `/D<macro>` — e.g. `"DEBUG=1"` or just `"DEBUG"` |
| `.links(libraries)` | `Iterable[str] -> Target` | Library names to link — `-l<name>` (GNU) or `<name>.lib` (MSVC). If `<name>` is another target in the same workspace, its build directory is automatically added as a search path (see [Dependencies](#dependencies-and-linking)) |
| `.depends_on(targets)` | `Iterable[str] -> Target` | Target names to build *before* this one, in workspace-wide dependency order. Does **not** by itself add a linker flag — pair with `.links([...])` for a library dependency |
| `.compile_flags(flags)` | `Iterable[str] -> Target` | Passed to the compiler verbatim, after everything else |
| `.link_flags(flags)` | `Iterable[str] -> Target` | Passed to the linker verbatim, after everything else |

### `Kind`

```python
Kind.EXECUTABLE       # a runnable program
Kind.STATIC_LIBRARY    # lib<name>.a (GNU) / <name>.lib (MSVC)
Kind.SHARED_LIBRARY    # lib<name>.so/.dylib (GNU) / <name>.dll (MSVC)
Kind.TEST              # like EXECUTABLE, but picked up by `charpente test`
```

### `Language`

```python
Language.CPP   # default
Language.C
```

### `OS`

```python
OS.WINDOWS
OS.LINUX
OS.MACOS
```

Not usually needed directly in a `.charpente` file — `charpente.platform.host_os()`
returns the host's `OS` value, which the build engine uses internally to
pick toolchains and output filename conventions. Exposed via
`from charpente import *` for the rare case a workspace wants to branch on
host OS itself (plain Python — an `if`, not a DSL construct):

```python
from charpente import *
from charpente.platform import host_os

with Workspace("W") as ws:
    with Target("app") as t:
        if host_os() == OS.WINDOWS:
            t.defines(["PLATFORM_WINDOWS"])
```

## DSL v2 (additive: every v0.1.0 file works unchanged)

### `uses`: order, link and shared settings in one line

```python
with Target("engine") as t:
    t.kind(Kind.STATIC_LIBRARY)
    t.sources(["engine/**/*.cpp"])
    t.public_include_dirs(["engine/include"])     # used here AND by whoever uses engine
    t.include_dirs(["engine/private"])            # only here
    t.public_defines(["ENGINE_API=1"])
    t.interface_include_dirs(["engine/shims"])    # only for users, not for engine itself
    t.public_links(["dl"])                        # system libraries users must also link

with Target("app") as t:
    t.sources(["app/**/*.cpp"])
    t.uses("engine", "fmt")                       # build order + link + engine's public settings
```

`uses` replaces the v0.1.0 pair `depends_on` + `links`, and fixes its classic trap (a
`depends_on` without `links` orders the build but never links). `uses_public("x")` also
re-exports `x`'s public settings to whatever uses *this* target. Static libraries' own
libraries are linked transitively (`app` uses `mid` uses `base`: `-lmid -lbase`), but include
directories only travel as far as `public`/`interface`/`uses_public` say. Names are targets of
the workspace or packages from `ws.requires(...)` ([`packages.md`](packages.md)).

New kinds: `HEADER_ONLY` (no build actions, only settings), `PLUGIN` (a shared library meant to be
loaded at run time). `SHADERS`, `XR_APP`, `MOBILE_APP`, `WEB_APP`, `FIRMWARE` are accepted by the
DSL and refused when planning (`CH3007`) until their platform support lands: never silently built
as something else.

### Conditions

```python
with t.on_config("Release") as c:                 # Debug / Release / any configuration name
    c.defines(["NDEBUG"])
    c.compile_flags(["-fno-rtti"])
with t.on_platform("linux-*") as p:               # windows-x64, linux-arm64, macos-arm64...
    p.links(["pthread"])
with t.on_toolchain("msvc") as c:                 # gcc, clang, msvc, clang-cl, mingw...
    c.compile_flags(["/permissive-"])
with t.when(config="Release", platform="windows-*") as c: ...
with t.on_platform("android-*") as p:
    p.android(package="cm.nka.app", min_sdk=29)   # recorded for the Android/HarmonyOS modules
t.platforms(["harmonyos-*"])                      # build this target only for matching platforms
```

Conditions are resolved *per (configuration, platform, toolchain) when planning*, not when the file
is loaded, so one workspace serves every configuration and the same graph can be inspected by tools.
Patterns are `fnmatch` (case-insensitive). Inside a block you may set sources, excludes, include
dirs, defines, links, flags, `uses` and `depends_on`.

### Options

```python
fast = ws.option("fast_math", default=False, help="Enable -ffast-math")
mode = ws.option("mode", choices=["fast", "safe"], default="safe")
level = ws.option("level", default=2)               # typed from the default: bool, int, string, enum
```

`ws.option` returns the value (the default, or the one from `charpente build --opt fast_math=true`),
so ordinary Python `if` works. `charpente options` lists them; a wrong value is `CH1021`, an unknown
name `CH1022`. Studio lists the same declarations.

### Rules: your own build steps, cached

```python
with Rule("version") as r:
    r.command(["python", "tools/gen_version.py", "VERSION", "gen/version.h"])   # a list, never a shell string
    r.inputs(["VERSION", "tools/gen_version.py"])
    r.outputs(["gen/version.h"])
    r.description("Generating version.h")

with Target("app") as t:
    t.sources(["src/**/*.cpp"])
    t.rules(["version"])                 # its outputs feed this target's compilations
```

Declared inputs and outputs are what make a rule cacheable: it runs again exactly when an input
changes, and its result is served from the cache otherwise. Outputs that are C/C++ files are
compiled as part of the target.

### `ws.requires`, `ws.platforms`, `ws.version`, single strings

`Workspace("Name", version="1.0.0")`, `ws.platforms(["windows-x64", "linux-x64"])`,
`ws.requires("fmt@^10")`. Setters accept a single string as well as a list: `t.sources("*.cpp")`
is one pattern (it used to be split into characters).

### `charpente.toml`: the declarative form

For simple projects and for repositories you do not trust. TOML is *data*: loading it runs no code
and needs no approval. See the header of `charpente/dsl/toml_loader.py` for the full schema;
unknown keys are errors.

```toml
[workspace]
name = "Demo"
requires = ["fmt@^10"]

[[target]]
name = "app"
sources = ["src/**/*.cpp"]
uses = ["fmt"]

  [[target.when]]
  config = "Release"
  defines = ["NDEBUG"]
```

`charpente lint` checks a `.charpente` file **without running it** (typos in method names, invalid
patterns, unknown targets, cycles, the `depends_on`-without-`links` trap); it also runs
automatically, quietly, before a file is loaded (`CHARPENTE_LINT=0` turns that off).
`charpente migrate` rewrites v0.1.0 idioms as v2 (a diff first, `--write` to apply).

## Reacting to events: `ws.on(...)` and `notify()`

The build emits events (see [`events/README.md`](events/README.md)). A function
decorated with `@ws.on(Event.X)` is called when one happens, on the event bus's
own thread, so it can never slow down or fail the build (an exception in a hook is
printed to stderr):

```python
from charpente import *

with Workspace("Demo") as ws:
    ...

    @ws.on(Event.BUILD_FINISHED)
    def summary(ev):
        notify(f"{ev.targets_built} targets built in {ev.duration:.1f}s", ok=ev.ok)
```

| `Event.` | Bus event | Useful fields |
|---|---|---|
| `BUILD_STARTED` / `BUILD_FINISHED` | `session.started` / `session.finished` | on finish: `ok`, `duration`, `targets_built`, `targets_failed`, `actions_run`, `cache_hits`, `warnings`, `errors` |
| `TARGET_STARTED` / `TARGET_FINISHED` / `TARGET_FAILED` | `target.*` | `target`, `executed`, `cached`, `up_to_date`, `error` |
| `ACTION_FAILED` | `action.failed` | `action`, `returncode`, `output` |
| `DIAGNOSTIC` | `diagnostic.emitted` | `file`, `line`, `column`, `severity`, `message` |
| `TEST_PASSED` / `TEST_FAILED` | `test.*` | `target`, `exit_code` |
| `HINT` | `hint.emitted` | `code`, `message` |
| `ANY` | every event | `type`, `payload` |

`notify(message, ok=True)` always prints `[notify] message` to stderr; if the
`charpente-notify` module is enabled it also sends the message to every notifier
whose configuration lists `events = ["notify"]`.

Scripts can react too: files in `.charpente/hooks/` named after an event type
(`session.finished.py`) get the event as JSON on standard input. They need your
approval — see [`security.md`](security.md).

## Dependencies and linking

```python
with Workspace("Game") as ws:
    with Target("engine") as t:
        t.kind(Kind.STATIC_LIBRARY)
        t.sources(["engine/**/*.cpp"])

    with Target("game") as t:
        t.kind(Kind.EXECUTABLE)
        t.depends_on(["engine"])   # build order: engine before game
        t.links(["engine"])       # actually link against libengine.a/engine.lib
        t.sources(["game/**/*.cpp"])
```

`depends_on` and `links` are separate on purpose: a target can depend on
another purely for build ordering (e.g. a code generator that must run
first) without linking against it, or link against a system library that
isn't a workspace target at all (`t.links(["m"])` for libm, no matching
`depends_on`). When the name in `.links([...])` *is* another target in the
workspace, the builder automatically adds that target's own build
directory as a linker search path — the `.charpente` file never needs to
know where Charpente puts build output.

`charpente build` computes the full build order via topological sort. Two
failure modes are caught explicitly with the target name in the message:

- **Unknown dependency**: `depends_on(["ghost"])` where `ghost` isn't a
  target in the workspace.
- **Dependency cycle**: `a` depends on `b` which depends on `a` (directly
  or through a longer chain) — the error names the full cycle, e.g.
  `"Dependency cycle detected: a -> b -> a"`.

## Name validation

Both `Workspace(name)` and `Target(name)` validate `name` at construction
time (`charpente.safe_name.validate`), because a target's name becomes
part of real output file paths (`build/<config>/<name>/...`). A name is
rejected — `ValueError`, immediately, naming the exact problem — if it:

- is empty or all whitespace,
- contains `..` (could make a generated path escape the output directory),
- contains a path separator (`/` or `\`) or a control character.

Accented letters, spaces, and parentheses are all fine:
`Target("Mon Appli Été (v2)")` is a valid name.

## What's *not* in the DSL (yet)

Honest gaps, tracked rather than silently missing:

- No precompiled header support.
- No C++20 module support.
- No per-target Windows resource files (`.rc`) / icons.
- No conditional compilation *within* a target based on `Workspace.configurations`
  beyond what you write yourself in plain Python (`if config == "Release": ...` —
  there's no `with filter(...)` construct).
- No `include()`/multi-file workspace composition — one `.charpente` file
  is one workspace, in full, today.
