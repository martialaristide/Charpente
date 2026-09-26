# Debugging

Charpente does not implement a debugger. It builds your target, then drives one that already speaks the [Debug Adapter Protocol](https://microsoft.github.io/debug-adapter-protocol/): **gdb 14 or newer** (`gdb --interpreter=dap`) or **lldb-dap** (LLVM). Microsoft's proprietary C++ debug adapter is not used (its licence restricts it to Microsoft products).

```
charpente debug --list                 # which debuggers were found
charpente debug [TARGET] [-- ARGS]     # build, then debug interactively in gdb (or lldb)
charpente debug-adapter [--root DIR] [--debugger gdb|lldb-dap]   # DAP over stdio, for editors and Studio
```

`charpente doctor` lists the debugger too. Without one, `CH8023` says what to install (MSYS2: `pacman -S mingw-w64-ucrt-x86_64-gdb`).

## The adapter

`charpente debug-adapter` sits between an editor and the debugger and forwards every message unchanged, except one: a `launch` request that names a **target** —

```json
{ "type": "charpente", "request": "launch", "target": "app", "config": "Debug", "args": ["--fast"] }
```

— is turned into a launch of that target's freshly built program (`program`, `args`, `cwd`), and the build's progress and compiler errors come back as DAP `output` events. If the build fails the launch is answered with an error and the session ends (`terminated`). A launch that already has a `program` is passed through, so any executable can be debugged. With one program in the workspace `target` can be left out. Other fields (`env`, `cwd`, `stopAtBeginningOfMainSubprogram`) go straight to the debugger.

Only programs that run on this machine can be debugged: a `platform` other than this one is refused with a message (remote debugging — Android through `adb`, SSH targets — is not implemented). Debug builds (`--config Debug`, the default) have symbols; a Release build is debuggable but poorly.

## Where it is used

- **VS Code extension**: a `charpente` debug type (`launch.json` snippet, F5). The extension starts `charpente debug-adapter --root <folder>`.
- **Charpente Studio**: the *Debug* panel and breakpoints in the editor gutter; Studio relays DAP over its WebSocket (`charpente/debug/*`, notifications `charpente/dap`).
- Any DAP client, with the command above as its adapter.

## Verified and not verified

Verified for real with gdb 17.2 on Windows/MinGW: the full conversation through `charpente debug-adapter` (build, launch, breakpoints, stop, stack, scopes and variables, `evaluate`, `next`, `continue`, program output, `terminated`), a failed build ending the session with the compiler output, debugging an existing `.exe`, the same through Studio's relay, and in a real browser (`tests/test_studio_e2e.py`). The launch rewriting and the proxy are also unit-tested with a fake debugger.

Not verified: **lldb-dap** (not installed here; the adapter passes messages through, but it was not run against it), Linux and macOS, the VS Code debug integration in a live VS Code (only its wiring is tested against a fake `vscode` module), remote debugging.
