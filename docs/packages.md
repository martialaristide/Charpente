# Packages (Charpente Pkg)

External libraries, with a lock file, checksums, offline builds and no surprise
downloads.

```python
from charpente import *

with Workspace("Game", version="0.3.0") as ws:
    ws.requires("fmt@^10", "spdlog", "glm", "nlohmann_json")

    with Target("app") as t:
        t.sources(["src/**/*.cpp"])
        t.uses("spdlog", "glm", "nlohmann_json", "fmt")
```

```bash
charpente pkg install      # resolve, download, verify SHA-256, write charpente.lock  (needs the network once)
charpente build            # never downloads anything: it uses what `pkg install` put there
```

**A build never touches the network.** If a required package is not installed,
`charpente build` stops with `CH6005` and tells you to run `charpente pkg install`.
That is deliberate: the only time Charpente contacts a server is when you ask it to.

## How it works

1. `ws.requires("fmt@^10")` records a wish (name and version constraint:
   `^1.2`, `~1.2.3`, `>=1,<2`, `*`).
2. `charpente pkg install` resolves the wishes with the **recipes** it can see, picking the
   highest version that satisfies everything (with backtracking, so a newer package whose
   dependencies clash does not block an older one that fits). It downloads each source
   archive, refuses it unless its SHA-256 equals the one in the recipe, unpacks it safely
   (no path escapes, no links), applies the recipe's patches, and writes
   **`charpente.lock`**: exact versions, the exact recipe bytes (digest) and the exact
   archive (digest). Commit the lock file.
3. Every later load of the workspace adds one ordinary **target per locked package**
   (header-only or a static library), compiled by Charpente's own engine with *your*
   toolchain, cached like your own code. `t.uses("fmt")` gives you its include directories,
   defines and link flags — exactly like a target of your own.
4. A dependency of a package is used publicly by it, so its settings travel to you.
   Packages you require but never `uses(...)` are not built.

With a lock file every machine gets the same versions and checks the same digests;
`charpente pkg install` keeps the locked versions and only moves them with `--update`.

## Where recipes come from

In order: `vendor/recipes/` next to the workspace, folders listed in `CHARPENTE_RECIPES`
(and `~/.charpente/pkg/recipes-local/`), the recipes **bundled with Charpente**, then
registries (`charpente pkg registry add URL`).

Bundled today, each pinned to the SHA-256 of a release archive:

| Package | Version | Licence | Build |
|---|---|---|---|
| fmt | 10.2.1 | MIT | static library |
| spdlog | 1.13.0 | MIT | static library (uses fmt) |
| nlohmann_json | 3.11.3 | MIT | header-only |
| glm | 1.0.1 | MIT | header-only |
| CLI11 | 2.4.1 | BSD-3-Clause | header-only |
| entt | 3.13.2 | MIT | header-only |
| doctest | 2.4.11 | MIT | header-only |
| tomlplusplus | 3.4.0 | MIT | header-only |
| magic_enum | 0.9.5 | MIT | header-only |
| vulkan-headers | 1.3.283 | Apache-2.0 OR MIT | header-only |

All ten were downloaded, verified, compiled with a real compiler (MinGW GCC 16) and linked into
one program, then built again from `vendor/` with an empty package store and
`CHARPENTE_OFFLINE=1` (see the phase 3 report). Hosting archives on GitHub means their
bytes are outside Charpente's control: if a host re-generates an archive the checksum
fails *loudly* (`CH6002`), and a mirror or a vendor folder is the fix.

## Writing a recipe

A recipe is TOML: **data, never code**. Reading or installing one executes nothing.

```toml
[package]
name = "fmt"
version = "10.2.1"
license = "MIT"
description = "A modern formatting library"
homepage = "https://fmt.dev"
purl = "pkg:github/fmtlib/fmt"          # used by `pkg audit` and the SBOM

[source]
url = "https://github.com/fmtlib/fmt/archive/refs/tags/10.2.1.tar.gz"
sha256 = "1250e4cc58bf06ee631567523f48848dc4596133e163f02615c97f78bab6c811"   # required
strip_prefix = "fmt-10.2.1"             # the archive's top-level folder

[build]
type = "sources"                        # header_only | sources
language = "cpp"                        # cpp | c
standard = "c++11"
sources = ["src/format.cc", "src/os.cc"]
include_dirs = ["include"]              # public: your targets get them
private_include_dirs = []
defines = []                            # public
private_defines = []
compile_flags = []                      # public
links = []                              # system libraries users must link
keep = []                               # files a *vendored* copy must keep (see below)

[build.platform."windows-*"]            # merged in when the platform matches
links = ["ws2_32"]

[dependencies]
requires = ["other@^1.2"]

[[patch]]                               # optional unified diff, relative to the recipe file
file = "fix.patch"
sha256 = "..."
```

Unknown keys are errors. `charpente pkg info NAME` shows what a recipe says.
Only `header_only` and `sources` builds exist; a library whose build needs a
generator (autotools, CMake configuration steps) needs a recipe that lists the
sources directly, or a future build type.

## Offline and low-bandwidth work

* **`charpente pkg vendor`** copies what building needs (include directories, listed sources,
  the recipe's `keep` globs and licence files — not tests, docs or examples) into `vendor/`,
  with a manifest of digests (`charpente pkg vendor --verify`). Commit it: the project then
  builds with **no** package store, registry or network.
* **`charpente pkg mirror populate DIR`** and **`charpente pkg mirror serve DIR`** turn one
  connected machine into a registry for a classroom, incubator or company network. The server
  supports HTTP `Range`, binds to this machine only unless you pass `--host`, and has no
  authentication (it says so when it starts). Clients:
  `charpente pkg registry add http://HOST:8765/index.json`. They still verify every archive
  against the recipe's SHA-256, so a mirror cannot substitute different code.
* Downloads are **resumable**, verified, and can be capped: `charpente pkg install
  --max-download 200MB`. `CHARPENTE_OFFLINE=1` forbids the network entirely.

## Security and supply chain

* Every archive is verified against a SHA-256 in the recipe before it is unpacked; a mismatch
  discards the file (`CH6002`).
* Archives are unpacked with every path checked (no `..`, no absolute paths, links never
  created), and Windows long paths are handled.
* `charpente.lock` pins recipe bytes and archive digests; a recipe edited afterwards is refused
  (`CH6009`).
* **`charpente pkg audit`** asks the OSV database about each locked package (only its `purl` and
  version are sent). OSV's coverage of C/C++ libraries is partial: *no finding is not proof of
  no vulnerability*, and a package whose recipe has no `purl` cannot be checked.
* **`charpente sbom`** writes SPDX 2.3 and CycloneDX 1.5 JSON from the real dependency graph
  (both validated against the official JSON Schemas in the test suite). It describes what
  Charpente resolved and verified; libraries you copied into your own sources are outside it.

## What is not done yet

Stated so the documentation never promises more than exists:

* **Prebuilt binary packages** downloaded from a registry (indexed by version, options,
  platform, toolchain, ABI): not implemented. Compiled packages *are* built once and reused
  through the content cache, but nothing downloads a prebuilt `.lib`/`.a`.
* **Bridges** to vcpkg, Conan, pkg-config and existing CMake projects: not implemented.
* **Recipe options** (`--pkg-opt fmt:shared=true`): recipes have no options yet.
* **Signed recipes / registries**: registry indexes are checked by SHA-256 only; recipe
  signatures reuse the module signing machinery but are not wired in yet.
* **LAN cache discovery** (mDNS): planned for phase 9; a mirror is the manual equivalent.
