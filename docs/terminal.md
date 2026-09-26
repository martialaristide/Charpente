# `charpente shell` and `charpente tui`

## `charpente shell`

```
charpente shell [--platform P] [--toolchain T] [--config Debug|Release] [--print-env [--format sh|powershell|cmd|json]] [-- COMMAND ...]
```

Starts a shell — or runs one command after `--` — where the project's toolchain is the one on `PATH`, and `CC`, `CXX` and `AR` point at it. That is the
same compiler Charpente builds with, including a cross toolchain (`--platform wasm32-wasi` gives `CXX="…/zig c++ -target wasm32-wasi"`) or a toolchain
Charpente installed that is not on your system PATH. Use it to run `make`, `cmake`, a Python `setup.py` or a vendor script against the same compiler.

Variables set: `PATH` (toolchain folders first), `CC`, `CXX`, `AR`, `CHARPENTE_ROOT`, `CHARPENTE_CONFIG`, `CHARPENTE_TOOLCHAIN`, `CHARPENTE_PLATFORM`, `CHARPENTE_SHELL=1`,
and the toolchain's own environment (for example `EMSDK`). `--print-env` prints them for `eval`/`Invoke-Expression` instead of starting anything:

```
eval "$(charpente shell --print-env --format sh)"
charpente shell --print-env --format powershell | Invoke-Expression
```

The command runs as an argument list (never through a shell of ours); its exit code is returned. The program is looked up on the *shell's* PATH (Windows resolves
executables with the parent's PATH, so this is done explicitly). Interactive shell: `$SHELL` (else `bash`/`sh`); on Windows `pwsh`, then `powershell`, then `%COMSPEC%`.
Error `CH8017` when no shell or program is found.

## `charpente tui`

```
charpente tui [--root DIR] [--file F] [--config Debug|Release]
```

A terminal interface built on [Textual](https://textual.textualize.io/) (`pip install "charpente[tui]"`; without it, `CH8018` — every command still works).
Left: the targets with their last result. Right: a live log of the engine (compiler output, diagnostics with file and line). Keys:

| Key | Action |
|---|---|
| `b` | build the selected target (and what it needs) |
| `a` | build everything |
| `r` | run the selected target |
| `t` | run the tests |
| `c` | run the quality gate |
| `l` | reload the workspace (also the way out of a broken `.charpente` file: the error is shown, you fix the file, press `l`) |
| `q` | quit |

One task at a time; a second request says so in the log instead of queuing silently. It uses the same `ServerState` as `charpente serve`, so it behaves like the
editor integrations.

**Tested** (`tests/test_shell_tui.py`, with Textual's headless `run_test`): target list, broken workspace and reload, a real build (both targets `ok`), a real compile
error (target `FAILED`, the compiler message in the log), the one-task-at-a-time rule, the missing-Textual error. **Not tested**: visual appearance in a real terminal.
