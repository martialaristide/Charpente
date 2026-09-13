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

## Reporting a vulnerability

Open an issue at
[github.com/martialaristide/Charpente/issues](https://github.com/martialaristide/Charpente/issues).
This is a young project without a formal disclosure process yet — for
anything you'd rather not post publicly first, say so in the issue and a
private channel will be worked out from there.
