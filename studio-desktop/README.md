# Charpente Studio — desktop wrapper (Tauri 2)

> **Status: skeleton, not compiled, not tested.** No Rust toolchain was available where this was written, so nothing in this folder has been built or run. It is here to show the intended shape (see [ADR 0018](../docs/adr/0018-studio-pile-technique.md)); expect to fix compile errors when you first build it. **No installer, signed or unsigned, exists.**

Studio is a web application served by `charpente studio`. This wrapper is only a native window around it:

1. `main.rs` starts `charpente studio --no-browser --json --root <folder>` as a child process, reads the one JSON line it prints (the address, with its private token), and opens a webview on that address.
2. The child is killed when the window closes.

The wrapper adds nothing to the UI, so everything in [docs/studio.md](../docs/studio.md) — including its limits — applies. What a native wrapper would add later: an integrated terminal with a real pty (`xterm.js` + the `portable-pty` crate), native file dialogs, installers (MSI, dmg, AppImage) and signed auto-updates.

## Build (untested)

```
cargo install tauri-cli --version "^2"
cd studio-desktop/src-tauri
cargo tauri dev          # needs `charpente` on PATH
cargo tauri build        # installers: not configured for signing
```

The window loads `http://127.0.0.1:<port>/`, so the page's Content-Security-Policy and Host/Origin checks apply as in a browser. `tauri.conf.json` still names a `frontendDist` folder (`dist/`, holding a placeholder page); whether Tauri 2 accepts a config with no window and no dev URL is one of the things not checked.
