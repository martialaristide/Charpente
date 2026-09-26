# Charpente for VS Code

Build, run, test and check C/C++ projects that use [Charpente](https://github.com/martialaristide/Charpente) without leaving the editor.

- **Targets view** in the activity bar: every target of the workspace, with Build and Run buttons.
- **Diagnostics**: compiler errors and warnings appear in the Problems panel, on the right line, and are cleared when you fix them.
- **Status bar**: workspace name, configuration and the result of the last build.
- **Tasks**: `charpente` tasks (`build`, `test`, `check`) with a problem matcher, usable from `tasks.json`.
- **Debugging**: a `charpente` debug type that builds a target and drives gdb or lldb-dap.
- **clangd**: writes `compile_commands.json` with the exact flags Charpente compiles with, so IntelliSense matches the build.
- **`.charpente` files** get syntax highlighting (they are Python).

It talks to `charpente serve` (Build Server Protocol 2.1 over stdio). Nothing is installed or uploaded by the extension.

## Requirements

Charpente 0.12 or later on your machine (`pip install charpente`). If the `charpente` script is not on your PATH, set
`charpente.command` to `["python", "-m", "charpente"]`.

## Trust

A `.charpente` file is a Python program that Charpente runs to learn what to build, so the extension only works in
**trusted** workspaces. The first time, run any `charpente` command in a terminal in the project and answer the trust question
(or set `CHARPENTE_TRUST_ALL=1` in an environment you control, such as CI).

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `charpente.command` | `["charpente"]` | How to start Charpente, as a list (never run through a shell). |
| `charpente.configuration` | `Debug` | `Debug` or `Release`. |
| `charpente.platform` | *(empty)* | Target platform, e.g. `wasm32-wasi`; empty builds for this machine. |
| `charpente.buildOnSave` | `false` | Build when a C/C++ file is saved. |
| `charpente.generateCompileCommandsOnLoad` | `true` | Write `compile_commands.json` when the workspace loads. |

## Develop

```
npm install
npm test          # compiles, then unit tests + a real conversation with `charpente serve`
npm run package   # builds charpente-x.y.z.vsix (not published anywhere)
```

What is tested automatically: the wire protocol, the pure helpers, and a full client session against a real server process. What is **not**
tested automatically: the parts that need a running VS Code (the tree view, status bar, diagnostics collection). See `docs/vscode.md`.
