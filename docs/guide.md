# Charpente: the complete guide

*Français : [guide.fr.md](guide.fr.md).* Every page linked here goes deeper; [stability.md](stability.md) says what is verified and what is not.

## 1. What Charpente is

You describe your C/C++ project in a `.charpente` file (Python syntax, but a *description*, not a script you have to know Python to read). Charpente builds it, on Windows, Linux and macOS, for those systems and for
Android, HarmonyOS, the web (WebAssembly), microcontrollers and more. It has four parts:

* **Engine** -- exact incremental builds, a content-addressed cache (local and shareable), reproducible builds, an event stream for tools.
* **Pkg** -- packages and curated **kits** of libraries (`ws.requires("fmt")`), with checksums.
* **Kits and templates** -- ready-made project skeletons (`charpente init NAME --template ...`).
* **Studio** -- a local web app, a VS Code extension, a build server (`charpente serve`), a debugger front end.

## 2. Install and first run

```bash
pip install -e .                 # from a checkout (PyPI publication has not happened yet)
charpente setup                  # checks the machine; offers to install a compiler (zig) if there is none
charpente doctor                 # what this machine can build, and what is missing
```

See [setup-and-uninstall.md](setup-and-uninstall.md). Charpente asks before every download and never accepts a licence for you.

## 3. Your first project

Prefer to be guided? Type `charpente` alone in a terminal: a menu creates the project, builds and runs it, and shows the command behind each choice ([console.md](console.md)). The same steps by hand:

```bash
charpente init hello --template console
cd hello
charpente build
charpente run --target hello -- Ada        # Hello, Ada!
charpente test
```

The first time Charpente meets a `.charpente` file it asks whether to trust it, because it is code that runs on your machine ([security.md](security.md)). `charpente init --list` shows the 16 templates
([templates.md](templates.md)). The file itself is short:

```python
from charpente import *

with Workspace("hello") as ws:
    ws.configurations(["Debug", "Release"])
    with Target("hello") as t:
        t.kind(Kind.EXECUTABLE)
        t.standard("c++17")
        t.sources(["src/*.cpp"])
```

Everything you can write is in [dsl-reference.md](dsl-reference.md); a step-by-step walk is [tutorial.md](tutorial.md).

### How the console looks

An interactive `charpente build` prints a banner (once), then the stages, one line per target (`✔` built, `◆` up to date or served by the cache, `▲` warnings, `✘` failure), a progress bar and a
result box. Four themes (`CHARPENTE_THEME`: `bois`, `neon`, `foret`, `ocean`), `NO_COLOR` for no colour, `CHARPENTE_ASCII=1` for an ASCII drawing, `CHARPENTE_NO_BANNER=1` for no banner; nothing
changes for scripts (`--output plain` / `jsonl`, redirected output, CI). `python -m charpente.ui` shows it. Details, adaptations and screenshots: [console.md](console.md).

## 4. Day to day

| I want to... | Command |
|---|---|
| build / build for release | `charpente build` / `charpente build --config Release` |
| see why something rebuilt | `charpente build -v`, `charpente why FILE` |
| rebuild on every save | `charpente dev` ([hot-reload.md](hot-reload.md)) |
| run / test | `charpente run`, `charpente test` |
| understand an error | `charpente explain CH1009` (English or French) |
| find slow headers | `charpente headers` |
| compare with the last build | `charpente history`, `charpente diff-build` |
| clean | `charpente clean` |

Rebuilds are exact: editing a header rebuilds precisely the files that include it, decided by file *content*, never timestamps.

## 5. Dependencies

`ws.requires("fmt")` in the file, then `charpente pkg install`; `charpente kit list|add` for curated sets (graphics, game, network, embedded, mobile...). Packages are checked against SHA-256 digests and
can produce an SBOM. See [packages.md](packages.md), [kits.md](kits.md).

## 6. Other platforms

```bash
charpente toolchain install zig
charpente build --platform linux-arm64
charpente platforms                  # every platform, its support tier, and whether this machine can build it
```

Android: `charpente package --format apk`, `charpente deploy` (one device) or `charpente deploy --device all --logs` ([android.md](android.md), [multi-device.md](multi-device.md)).
Also: [HarmonyOS](harmonyos.md), [embedded](embedded.md), [Apple and XR](apple.md), [platforms](platforms.md). Many cross builds are *built* but not *executed* here; the tables say which.

## 7. Speed, and doing it together

* The **local cache** makes a revert or a fresh clone fast. `charpente cache stats`.
* A **shared cache** lets a team or CI reuse each other's work: [shared-cache.md](shared-cache.md) (with its threat model).
* **Reproducible builds** (`--reproducible`, `charpente verify-reproducible`) and **budgets** (`ws.budget(...)`) make results trustworthy: [reproducible-and-budgets.md](reproducible-and-budgets.md).
* On a small or battery-powered machine: memory and disk are watched, and `--eco` builds gently: [resources.md](resources.md).

## 8. Quality, Git, releases

`charpente check` runs the quality gate (format, warnings, secrets, tests, sanitizers, coverage, licences, SBOM); `charpente hooks install`, `commit`, `push`, `pr` put it in front of Git; `charpente ci init` and
`charpente release` prepare CI and signed releases (nothing is published without `--publish`). See [quality.md](quality.md) and [git.md](git.md).

## 9. Editors and Studio

* `charpente studio` -- the workspace in your browser: files, targets, editor with clangd, builds, profile, Git, devices, debugging ([studio.md](studio.md), [debugging.md](debugging.md)).
* VS Code: the `vscode-charpente/` extension ([vscode.md](vscode.md)). Any editor: `charpente serve` speaks BSP/JSON-RPC ([serve.md](serve.md)), and `charpente generate compile-commands` feeds clangd.
* Terminal: `charpente shell` (the project's toolchain on PATH), `charpente tui` ([terminal.md](terminal.md)).
* AI help is opt-in and shows what it would send first: `charpente fix`, `charpente ai ...` ([ai.md](ai.md)).

## 10. Coming from, or going to, other tools

`charpente import cmake` writes a `.charpente` from a CMake project; `charpente generate ninja|cmake|vs|compile-commands` writes project files for other tools ([import-and-generate.md](import-and-generate.md)).
`charpente docs` writes API documentation from your header comments ([api-docs.md](api-docs.md)).

## 11. When something goes wrong

Every error has a code: `charpente explain CHxxxx` gives the cause and the fix in your language ([errors.md](errors.md)). Common situations are in [troubleshooting.md](troubleshooting.md).
`charpente doctor` first; then `charpente build -v`. To remove everything Charpente stored: `charpente self uninstall`.

## 12. Honest limits

Version 0.13 is alpha. It was verified on one Windows machine; Linux and macOS were never run, and the CI workflow has never run on this work (it was not pushed; only Python 3.12 was used). Remote execution and Xcode projects are not done; a desktop app for Studio exists only as an
uncompiled skeleton. The complete list is [stability.md](stability.md).
