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
