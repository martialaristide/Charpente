# Security

## A `.charpente` file is not sandboxed

This is the one thing to understand before running a `.charpente` file you
didn't write. `charpente build` (and every other command that loads a
workspace) executes the file with Python's `exec()`, in a namespace that
happens to have `Workspace`/`Target`/`Kind`/`Language`/`OS` predefined —
nothing else about it is restricted. `import os`, `subprocess`, reading or
writing arbitrary files, opening a network connection: all valid, all with
the full permissions of whoever ran `charpente`.

This is deliberate, not an oversight. The DSL is native Python (in the
spirit of a `SConstruct` or `setup.py`) specifically so that a `.charpente`
file can do things like: compute a source file list with a helper
function, branch on `platform.system()`, or read a version number from
another file — without needing a second, restricted language bolted onto
Python for that. The tradeoff is that running someone else's `.charpente`
file is exactly as trusting as running a script you downloaded and didn't
read.

### The trust-on-first-use prompt

Because that's easy to forget, Charpente asks for confirmation the first
time it's about to run a `.charpente` file whose *exact current content*
hasn't been approved before:

```
! Charpente workspace file: /path/to/some.charpente
  This file will execute as unrestricted Python code (not a sandbox).
  Trust and run it? [y/N]
```

- Your answer is remembered in `~/.charpente/trusted_files.json`, keyed by
  a SHA-256 hash of the file's content — not by its path. Edit an approved
  file (even by one byte) and it's treated as unseen, asked about again.
  Nothing is ever sent anywhere; the file lives entirely on your machine.
- In a **non-interactive session** (a CI job, a script with no attached
  terminal) with no prior approval on record, Charpente refuses to run the
  file — a clear `TrustRequiredError`, not a prompt nobody can answer and
  not a silent bypass. Set `CHARPENTE_TRUST_ALL=1` in that environment if
  you trust the repository being built (this is what Charpente's own CI
  workflow does, since its own test fixtures are trusted by definition).
- This is consent, not containment. Approving a file doesn't restrict what
  it can do in any way — it only means you've been told, once, that it can
  do anything, and agreed to proceed.

## Everything else Charpente does on your behalf

A short list of the choices made deliberately with security in mind, so
they're stated rather than left to be discovered:

- **No `shell=True`, anywhere.** Every subprocess Charpente launches
  (compiler, linker, archiver, `iscc`/`dpkg-deb`/`pkgbuild`, the program
  under `charpente run`) is invoked as an explicit argument list, never a
  shell string. There is no feature in this version that runs an
  arbitrary shell command string from a `.charpente` file (no
  `pre_build_commands`-style hook) — if one is added later, it inherits
  the same rule.
- **Target/workspace names are validated at declaration time**
  (`charpente.safe_name`), not wherever a path happens to get built from
  them later. A name is rejected outright — empty, containing `..`, a
  path separator, or a control character — because it becomes part of a
  real output path (`build/<config>/<name>/...`) and, with `--format
  installer`, part of a generated Inno Setup script, `.deb` control file,
  or `pkgbuild` identifier.
- **`--ai-diagnose` and `charpente ask` are always opt-in, per invocation.**
  No build failure is ever sent to an AI provider automatically. There's
  no "always diagnose" setting to leave on by accident — you pass
  `--ai-diagnose` (or run `ask`) each time you want it, because doing so
  costs a request and sends text (compiler output, which can include
  source snippets) to whichever third-party provider is configured.
- **`pip install charpente` alone installs zero AI dependency.** The
  `anthropic`/`openai` packages are behind the `[ai]` extra; the local
  provider uses only `urllib` from the standard library. Every other
  feature (build, run, test, package, clean) works fully with nothing
  configured, and with nothing able to reach the network on Charpente's
  own initiative.

## Hooks run your code, so they need your approval

`@ws.on(Event.X)` functions live in the `.charpente` file, which you have
already approved. Scripts in `.charpente/hooks/` (named after an event:
`session.finished.py`, `action.failed.sh`...) are separate files, so they are
approved separately, by the SHA-256 of the whole folder's content: the first
time, and again whenever any of them changes. Non-interactively (CI) they run
only with `CHARPENTE_TRUST_ALL=1`; otherwise Charpente says they were skipped.
Scripts are started through an explicit interpreter chosen by extension
(`.py`, `.sh`, `.bat`, `.cmd`, `.ps1`), never a shell string, and are advisory:
a failing hook can never fail the build.

## Modules: capabilities are a contract, not a sandbox

A module declares what it needs in `charpente-module.toml`:

```toml
[capabilities]
process = ["glslangValidator"]     # programs it may start
filesystem = "workspace"           # none | workspace | build | home
network = false                    # or true, or a list of host names
```

At installation Charpente shows these in plain words and asks for approval;
the approval is stored, and a later version that asks for *more* stays disabled
until you approve again (`CH7015`). Modules reach the outside world through
guarded services (`ctx.process`, `ctx.fs`, `ctx.net`) that check every call
against the approved set, including path traversal and symlink escapes.

**What this does not do:** a Python module runs in Charpente's own process and
can `import subprocess` or `socket` and bypass the guards. The capability system
makes the honest path explicit, auditable and enforced for modules that use the
provided services; `charpente module check` warns when a module imports such
things directly. Real trust comes from the module's **signature and author**,
not from these checks. Install modules the way you would install any Python
package: only from sources you trust.

### Signatures

`charpente module sign` signs a module folder (Ed25519, RFC 8032, verified with
a from-scratch implementation checked against the RFC test vectors). A module is
"signed" only if its key is in your trust store (`charpente module trust-key`) or
among the official keys shipped with Charpente. **The official key list is empty
today**: no signed registry has been published yet, so every third-party module is
"unsigned" and needs `--allow-unsigned`. A signature that does not verify (a file
was changed after signing) is refused outright, never downgraded to "unsigned".
Installing is inert: a module's code is only imported when it is loaded.

## Notifications and secrets

The bundled `charpente-notify` module is **off until you enable it**, and sends
nothing until you create `.charpente/notify.toml`. Secrets (webhook URLs, bot
tokens, SMTP passwords) are never written in that file: it only names the
*environment variable* that holds them (`url_env = "MY_WEBHOOK"`), and a literal
`url = "..."` is rejected. Messages contain the machine name, configuration,
counts and duration -- never source code or compiler output. Charpente sends no
telemetry.

## Reporting a vulnerability

Open an issue at
[github.com/martialaristide/Charpente/issues](https://github.com/martialaristide/Charpente/issues).
This is a young project without a formal disclosure process yet — for
anything you'd rather not post publicly first, say so in the issue and a
private channel will be worked out from there.
