# Charpente Studio

`charpente studio` opens Studio: a workspace UI for the project in the current folder. It is a local web application — Charpente serves its pages on `127.0.0.1` and you use it in your browser; there is nothing to install besides Charpente itself, and no network access is needed. Studio talks to the same server as the editors ([serve.md](serve.md)), so what it shows is what the command line does.

```
charpente studio [--root DIR] [--file F.charpente] [--port N] [--no-browser] [--json]
```

It prints an address such as `http://127.0.0.1:53211/?token=…` and opens it. **The address contains a private token**: anyone who has it can build and run code in your project, so do not share it. The page removes the token from the address bar after loading. Stop Studio with Ctrl+C.

## What is in it

| Area | What it does |
|---|---|
| **Explorer** | *Files* (lazy tree, new file), *Targets* (build/run buttons, dependencies, last result), *Options* (`ws.option(...)` as check boxes/lists; saved in `.charpente/options.toml`, which every command reads — `--opt` still wins), *Packages* (search recipes, add/remove `ws.requires(...)` in your file, install). |
| **Editor** | Tabs with unsaved-change marks; syntax highlighting (C/C++, Python, `.charpente` with the DSL's names emphasised, JSON, TOML, Markdown, CMake, shell, YAML, GLSL); line numbers; error/warning underlines and hover text; **completion** — the DSL's methods and enums from the server's schema for `.charpente`, **clangd** for C/C++ (with words of the document as a fallback); F12 go to definition and rename through clangd; format on save with `clang-format` when the project has a `.clang-format`; save conflict detection (a file changed on disk is never overwritten silently); original line endings (CRLF/LF) preserved. |
| **Build** | Live progress from the engine's events, the compiler output with `file:line` links, hints, **Explain** for `CHxxxx` codes. |
| **Problems** | Compiler diagnostics and clangd's, grouped by file, click to jump; cleared as you fix them. |
| **Graph** | The target dependency graph; the **critical path** of the last build (the chain that bounds its time) is highlighted. |
| **Profile** | Time per target, the slowest actions, the headers that are most expensive to touch. |
| **Git** | Status, per-file and **per-block** staging, diff, a commit that runs the quality gate first (skipping it is a visible choice), history. |
| **Devices** | Android (`adb`) and HarmonyOS (`hdc`) devices, **Deploy**, live device logs (`logcat`, `hilog`). |
| **Debug** | Breakpoints (click a line number, F9), start a target under gdb / lldb-dap, continue, step, call stack, variables, watch expressions, program output. See [debugging.md](debugging.md). |
| **Terminal** | Several tabs; commands run in the project's environment (toolchain on PATH, `CC/CXX/AR`, see `charpente shell`), output with clickable `file:line`. |
| **Assistant** | Opt-in AI: you see exactly what would be sent (secrets already replaced) and press *Send*; a proposed fix is a diff you review and apply. See [ai.md](ai.md). |

Interface in **French and English** (follows your browser, switchable), light/dark/system theme, keyboard access: `Ctrl+Shift+P` command palette, `F7` build, `F5` run (or continue when debugging), `Ctrl+F5` debug, `F9` breakpoint, `F10/F11` step, `Ctrl+S` save, ``Ctrl+` `` terminal, `Alt+1…9` panels.

## Security

Studio can build and run code, so it defends itself: loopback only; a random per-run token required by the WebSocket (constant-time comparison); the browser `Origin` and the `Host` header are checked (blocks other sites and DNS rebinding); the pages are served with a strict Content-Security-Policy (only its own scripts, connections only to this server, no inline scripts, no `eval`); files outside the project are unreachable (`..`, absolute paths and symbolic links out are refused; `.git` is never written directly); commands run as argument lists, never through a shell; nothing is sent to an AI provider without you pressing *Send*; nothing is published or pushed.

## Limits — said plainly

- **The editor is not Monaco.** It is a small textarea-based editor (≈300 lines) so Studio needs no build step and ships no multi-megabyte dependency. It has no multi-cursor, code folding, minimap or find/replace; use the VS Code extension for a full editor. See [ADR 0018](adr/0018-studio-pile-technique.md).
- **The terminal has no pty.** It runs one command at a time as an argument list (no pipes, redirections or interactive programs like `vim`). A real terminal (xterm.js + a native pty) needs the desktop wrapper.
- **No desktop installers.** The Tauri wrapper in [`studio-desktop/`](../studio-desktop/) is a documented skeleton that was **not compiled** (no Rust toolchain here); signed MSI/dmg/AppImage installers do not exist.
- **The profile is a ranking, not a timeline**: the history database keeps each action's duration, not when it started.
- Breakpoints do not move when you edit lines above them. Debugging works for programs that run on this machine (Android/`adb` remote debugging is not implemented).
- Studio was checked in **Microsoft Edge (Chromium) only**; Firefox and Safari were not tried.
- Cancelling a running build is not possible yet.

## How it is tested

| Layer | How |
|---|---|
| The pure front-end code (highlighting, completion, diff parsing, graph layout, command-line splitting, RPC client, translations) | 33 `node --test` unit tests (`tests/studio_js/`), run by `tests/test_studio_web.py`. Both languages must have exactly the same keys, and every key used must exist. |
| Every server method Studio calls | `tests/test_studio_api.py` (55 tests: files, conflicts, symlinks, Git incl. single-hunk staging, packages, options, terminal streams, formatting, a real clangd session, the debug relay with a real gdb, the assistant with a fake provider). |
| The web server (headers, traversal, Host and token checks) | `tests/test_studio_web.py`. |
| **The whole application in a real headless Edge**, driven through the DevTools protocol, against a real `charpente studio` process and a real project | `tests/test_studio_e2e.py` (23 tests): loading, language and theme, build, run, graph, profile, compile errors appearing and clearing, Explain, typing/indentation/completion, save conflicts, new files, command palette, terminal (run and stop), Git hunk staging and commit, options and packages, devices, connection loss, **clangd diagnostics and go-to-definition**, **debugging with gdb (breakpoint, stack, variables, evaluate, step, continue)**, and the assistant (a fake OpenAI-compatible server checks that a secret in the code is **never** sent). Skipped when no Chromium-family browser is installed. Set `STUDIO_SCREENSHOTS=<folder>` to keep screenshots. |
