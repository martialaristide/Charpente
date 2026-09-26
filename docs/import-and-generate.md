# Coming from, and going to, other build systems

## `charpente import cmake` -- start from an existing CMake project

```bash
charpente import cmake path/to/project          # writes path/to/project/<name>.charpente
charpente import cmake . --print                # just show the result
charpente import cmake . --cmake-arg -DWITH_X=ON --build-dir /tmp/cmake-config
```

Charpente does **not** parse `CMakeLists.txt` (that is a programming language: `if`, `foreach`, functions, generator expressions). It asks CMake itself, through CMake's
[File API](https://cmake.org/cmake/help/latest/manual/cmake-file-api.7.html): CMake configures the project, and Charpente reads the answer (targets, sources, include directories, definitions,
compile options, link libraries, C++ standard). So whatever CMake understands, the import understands -- and CMake must be installed.

| Option | Meaning |
|---|---|
| `folder` | The folder containing `CMakeLists.txt` (default: here). |
| `--out FILE` | Where to write (default `<folder>/<name>.charpente`). An existing file is never overwritten without `--force`. |
| `--build-dir DIR` | Keep CMake's configuration here (default: a temporary folder). |
| `--cmake PATH` | The `cmake` to use. |
| `--cmake-arg ARG` | Pass an argument to the configuration, e.g. `-DWITH_X=ON` (repeatable). |
| `--print` | Print instead of writing. |

What is translated: executables, static/shared/object/module libraries (module libraries become plugins, interface libraries header-only targets), sources, include directories, definitions, the recognised compile options,
link libraries and dependencies between targets, and the C or C++ standard. **What is not** is listed in a report printed after the import (and never dropped silently): custom commands, generated sources, external
libraries found by absolute path, compile and link flags Charpente does not recognise, per-configuration settings, and tests (`add_test`). The File API does not tell public from private include directories, so a library's
include directories are all exported to what uses it (a superset of CMake's PUBLIC); the report says so. If CMake set no C++ standard, the import assumes one and says so. The CMake project's own folder is never written to
(configuration happens in a scratch folder, or in `--build-dir`). The result is a starting point to review and edit, not a guarantee of an identical build.

Verified: a real CMake 3.22.1 project (an executable using a static library) imported, built by Charpente and run, printing the expected result. Not verified: large real-world projects, other CMake versions.

## `charpente generate` -- give other tools something they understand

```bash
charpente generate --list                 # the formats, and what each has been verified against
charpente generate compile-commands       # compile_commands.json (default)
charpente generate ninja                  # build.ninja
charpente generate cmake                  # CMakeLists.txt
charpente generate vs                     # Visual Studio solution + one project per target
charpente generate ninja --out build-ninja --config Release --platform linux-arm64
```

Generation loads the project and *plans* the build with the same engine and the same flags a real `charpente build` uses; it compiles nothing. Every generated file starts with a marker comment, and
**a file Charpente did not write is never overwritten** without `--force`.

| Format | Files | What it is | Verified against |
|---|---|---|---|
| `compile-commands` | `compile_commands.json` | The exact compiler arguments, for clangd, clang-tidy and editors. | clangd 22 |
| `ninja` | `build.ninja` | The engine's action plan as Ninja rules, with header dependency tracking (`depfile`/`deps`). Running `ninja` needs no Charpente. | Ninja 1.10.2: built the project and rebuilt on a header change |
| `cmake` | `CMakeLists.txt` | Targets, sources (globs expanded when generated), public/private includes, definitions, flags, links, the standard and tests (`add_test`) from the model. What is not translated (configuration/platform overlays, rules, Android/HarmonyOS/iOS settings, assets, hooks, and `ws.requires` packages, whose names are listed) is listed at the top of the file. | CMake 3.22.1: configured, built and ran `ctest` |
| `vs` | `<name>.sln`, one `.vcxproj` per target | Makefile-type projects whose Build/Rebuild/Clean commands run `charpente`, with sources, headers, include directories and definitions for IntelliSense. | **Not opened in Visual Studio**: well-formedness and stability only |
| `xcode` | -- | **Not implemented.** An Xcode project can only be checked on a Mac. | -- |

Notes:

* The Ninja and CMake outputs are written for *this machine's* toolchain and paths (Ninja) or for the model (CMake). Regenerate after changing the `.charpente` file; generated Ninja files are not portable between machines.
* Generated Visual Studio projects delegate to `charpente` for building; the project GUIDs are stable, so regenerating keeps the solution's history.
* The same `--config`, `--platform`, `--opt`, `--toolchain`, `--sanitize`, `--coverage` and `--reproducible` options as `build` apply.
