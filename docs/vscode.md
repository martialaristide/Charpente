# VS Code extension

The extension lives in [`vscode-charpente/`](../vscode-charpente/). It is a thin client of [`charpente serve`](serve.md): it starts the server for the open
folder, shows what the server says, and asks it to build, run, test and check.

## What it gives you

- **Charpente view** (activity bar): the targets of the workspace, with inline *Build* and *Run* buttons (Run only for executables and tests).
- **Problems panel**: compiler errors and warnings at the right line and column (`build/publishDiagnostics`), cleared by the next successful build.
- **Status bar**: workspace name, configuration, spinner while building, red on failure; click to build.
- **Tasks**: `charpente` task type (`build`, `test`, `check`, with `target` and `config`) and the `$charpente-cpp` problem matcher. Tasks run the command as
  an argument list — never through a shell.
- **clangd**: `compile_commands.json` is written to the workspace root when the workspace loads (setting `charpente.generateCompileCommandsOnLoad`) and via
  *Charpente: Generate compile_commands.json*. It contains the exact arguments used to build, so IntelliSense and the build agree.
- **Explain**: *Charpente: Explain an error code*; error messages with a `CHxxxx` code offer an *Explain* button.
- **`.charpente` files** are highlighted as Python with the Charpente names emphasised.
- **Debugging**: a `charpente` debug type (`launch.json`: `target`, `config`, `args`, or `program`) driven by `charpente debug-adapter` — it builds the target, then gdb or lldb-dap. See [debugging.md](debugging.md).
- Saving a `.charpente` file reloads the workspace; `charpente.buildOnSave` builds when a C/C++ file is saved.

## Install (from source, nothing is published)

```
cd vscode-charpente
npm install
npm test                      # compile + 26 tests
npm run package               # writes charpente-0.12.0.vsix
code --install-extension charpente-0.12.0.vsix
```

`code --install-extension` is a normal, reversible install that **you** run; nothing in this repository installs the extension for you or publishes it
to the Marketplace (`publisher` in `package.json` is a placeholder until an account exists).

## Trust and safety

The extension declares `untrustedWorkspaces: { supported: false }`: a `.charpente` file is code. The server also refuses unapproved workspace files (it cannot
ask you a question over its protocol), so the first time you must run a `charpente` command in a terminal in that folder and approve it.

## How it is tested

| Layer | How | Automatic |
|---|---|---|
| Wire protocol (`rpc.ts`), URI helpers, settings → arguments, diagnostics conversion, status text | `node --test` unit tests | yes |
| `ServerClient` against a real `charpente serve` (spawn, initialize, requests, notifications, errors, stop, missing command) | `test/client.test.ts` | yes |
| The whole `extension.ts` (activation, commands, tree, status bar, diagnostics appear/clear, tasks, `compile_commands.json`, run output, gate, reload on save) | `test/extension.test.ts`: the real extension code against a **fake `vscode` module** and a real server | yes |
| Rendering inside a real VS Code (tree icons, status bar look, Problems panel) | — | **no**: it needs a VS Code test host (`@vscode/test-electron`), not available offline |

The fake `vscode` module implements only what the extension calls, so it proves our logic, not that the real API behaves identically. The extension has
not been loaded in a live VS Code by the author.

## Not there yet

Remote debugging, a WebSocket mode for remote workspaces, testing-API integration (the Test Explorer), and a Marketplace release.
