# `charpente serve` — the engine as a server

`charpente serve` runs the build engine as a long-lived process that editors, IDEs and Charpente Studio talk to. It is the only thing they
need: the VS Code extension ([vscode.md](vscode.md)), the terminal interface (`charpente tui`, [terminal.md](terminal.md)) and any client of the
[Build Server Protocol](https://build-server-protocol.github.io/) (BSP 2.1) use the same code paths as the command line.

```
charpente serve [--stdio | --ws [--port N]] [--root DIR] [--file F.charpente]
charpente serve --bsp-install        # writes .bsp/charpente.json so BSP clients discover the server
```

## Two transports, one dispatcher

| | `--stdio` (default) | `--ws` |
|---|---|---|
| Wire | JSON-RPC 2.0, `Content-Length` framing (LSP/BSP) | JSON-RPC 2.0, one message per WebSocket text frame |
| For | editors, IDEs, `.bsp/charpente.json` | Studio, browsers, anything that prefers sockets |
| Lifetime | ends at `build/exit` or when stdin closes | ends when its stdin closes (a dead parent takes it along) |

`--ws` listens on **127.0.0.1 only** and prints one JSON line on stdout:

```json
{"charpente-server": {"url": "ws://127.0.0.1:53211/?token=…", "host": "127.0.0.1", "port": 53211, "token": "…", "pid": 4242, "root": "…"}}
```

**Security.** Loopback traffic is not TLS, so the server defends itself instead: a random per-run token is required in the URL (compared in constant time,
`401` otherwise), the browser `Origin` is checked (`403` unless it is localhost, `vscode-webview`, `tauri`…), messages above 16 MiB and malformed frames
close the connection, and the server can run code (`buildTarget/run`), so it never listens on another interface. Requests run on worker threads; only one
build runs at a time (`-32000` "a build is already running" for the second).

## BSP methods

`build/initialize`, `build/initialized`, `build/shutdown`, `build/exit`, `workspace/buildTargets`, `workspace/reload`, `buildTarget/sources`,
`buildTarget/inverseSources`, `buildTarget/dependencySources`, `buildTarget/resources`, `buildTarget/cppOptions` (the BSP C/C++ extension: `-I`, `-D`,
`-std`), `buildTarget/compile`, `buildTarget/test`, `buildTarget/run`, `buildTarget/cleanCache`.

Notifications sent to the client: `build/taskStart`, `build/taskProgress`, `build/taskFinish`, `build/logMessage`, `build/publishDiagnostics`
(compiler errors and warnings with their real file, line and column; **cleared** when a later build no longer reports them).

Deliberate choices:

- `buildTarget/compile` takes build options in `arguments`: `--config Debug|Release`, `--platform P`, `--toolchain T`, `-j N`, `--no-cache`.
- `buildTarget/run`: `arguments` are **the program's own arguments** (as BSP says); how to build it goes in `data`
  (`dataKind: "charpente/run"`, `data: {"config": "Release", "platform": "…"}`).
- `canDebug` is `false` everywhere: debugging (DAP) is Phase 8.
- `$/cancelRequest` is accepted and ignored — builds cannot be interrupted from the protocol yet.
- `buildTarget/run` and `buildTarget/test` run `charpente run|test` as a child process, whose output comes back as `build/logMessage`. Captured child
  processes get **no stdin**: the protocol channel is never readable by them (this fixed a real hang, see the ADR).

## `charpente/*` methods

| Method | Result |
|---|---|
| `charpente/ping` | `{pong, version}` |
| `charpente/workspace`, `charpente/reload` | name, version, root, file, configurations, platforms, kits, options, host |
| `charpente/graph` | `{nodes, edges, order}` of targets |
| `charpente/toolchains` | detected toolchains and every platform with its tier and whether this machine can build it |
| `charpente/build` | `{ok, results, diagnostics}` (targets, config, platform, toolchain, jobs, cache) |
| `charpente/compileCommands` | `{entries}`: a clang compilation database with the **exact arguments the engine compiles with** |
| `charpente/check` | the quality gate outcome with every finding located |
| `charpente/explain` | `{code, text}` for `CHxxxx` |
| `charpente/why` | the `charpente why` explanation as text |
| `charpente/history` | recent sessions |
| `charpente/subscribe` / `unsubscribe` | every engine event as `charpente/event` notifications (dropped when the connection closes) |

### Methods added for Studio

| Method | Result |
|---|---|
| `charpente/files/list`, `read`, `write`, `create` | The project's files (never outside it; `.git` is never written). `write` takes the `sha256` the client read: a file that changed meanwhile is a conflict (`-32011`), not overwritten. |
| `charpente/dsl/schema` | The methods (with signatures) of `Workspace`/`Target`/`Rule` and the members of `Kind`/`Language`, for completion. |
| `charpente/profile`, `charpente/headers` | Time per target and action of the latest build that did work, its critical path; the most expensive headers. |
| `charpente/git/status`, `diff`, `log`, `stage`, `apply` (one block), `commit` (through the quality gate) | The Git panel. |
| `charpente/devices`, `devices/logs`, `deploy` | Android and HarmonyOS devices, live logs, deployment. |
| `charpente/packages/search`, `list`, `add`, `remove`, `install` | Edits `ws.requires` in your file. |
| `charpente/options/set` | Validates and saves option values in `.charpente/options.toml`, then reloads. |
| `charpente/terminal/run`, `charpente/stream/stop` | Runs an argument list in the project environment; output arrives as `charpente/stream` notifications (`{id, kind, line}` and a final `{exit}`). Streams stop when the connection closes. |
| `charpente/lsp/start`, `send`, `stop` | Starts clangd for the project and relays LSP (`charpente/lsp` notifications). `charpente/format` runs clang-format. |
| `charpente/debug/available`, `start`, `send`, `stop` | Starts `charpente debug-adapter` and relays DAP (`charpente/dap` notifications). See [debugging.md](debugging.md). |
| `charpente/ai/status`, `context`, `send`, `apply` | The assistant, in two steps: `context` returns exactly what would be sent (nothing is sent); `send` sends a context by id. See [ai.md](ai.md). |
| `charpente/compileCommands` | (P7) the compilation database with the engine's own arguments. |

`charpente studio` serves these plus static pages on one port; see [studio.md](studio.md). Workspace-load errors carry their `CHxxxx` code in the message, and a workspace whose packages are declared but not installed still loads (with `notice`: `CH6005`) — building it is refused until they are installed.

Errors use JSON-RPC codes: `-32001` workspace could not be loaded (the message starts with `[CHxxxx]`, and `data.code` has it), `-32002` call
`build/initialize` first, `-32000` busy, `-32602` bad parameters, `-32601` unknown method.

## What a server never does

- It never prompts (stdin is the protocol). A `.charpente` file that has not been approved yet is reported as an error; approve it once in a terminal, or set
  `CHARPENTE_TRUST_ALL=1` in a CI environment you control.
- It writes only where the command line would: the project's build and state folders and the user-level cache. The VS Code extension additionally writes `compile_commands.json` at the project root.
- It never publishes, pushes or uploads anything.

## Verified and not verified

Verified by tests (`tests/test_serve.py`, 56 tests) and by hand: framing (split chunks, garbage, truncation), the dispatcher, the WebSocket handshake
(the RFC 6455 example key), frame sizes 0…70000, fragmentation, token and Origin checks, a real server process over stdio and over WebSocket,
initialize → targets → sources → cppOptions → compile (with diagnostics appearing and disappearing) → run → shutdown → exit on a real C++ project.

Not verified: interoperability with a third-party BSP client (IntelliJ/CLion, Bloop-style tools) — the protocol is implemented from its
specification and exercised with our own clients only.
