# CLI reference

Every command accepts `--file PATH` to point at a specific `.charpente`
file. Without it, Charpente looks for the single `.charpente` file in the
current directory, then each parent directory in turn, until it finds
exactly one (an error names the directory if there's more than one, or if
there's none at all the way up).

The first time any command loads a `.charpente` file whose exact content
hasn't been approved before, you're asked to confirm — see
[`security.md`](security.md).

## `charpente init NAME [--dir DIR]`

Scaffolds `NAME.charpente` and `src/main.cpp` (a minimal "Hello, world"
executable target) in `DIR` (default: the current directory). Fails if
`NAME.charpente` already exists there — it never overwrites.

```bash
charpente init MyApp
cd MyApp  # if you used --dir MyApp; otherwise you're already there
charpente build
```

## `charpente build`

```
charpente build [--config Debug|Release] [--keep-going] [--ai-diagnose]
```

Compiles every target in the workspace, in dependency order.

- `--config` (default `Debug`): which configuration to build. Affects
  optimization/debug-symbol flags (`-O0 -g` / `/Od /Zi` for Debug,
  `-O2` / `/O2` for Release) and the output directory (`build/<config>/...`).
- `--keep-going`: without it, a target failure stops the whole build
  immediately. With it, unrelated targets still get built — only the
  failed target and anything that (directly or transitively) depends on
  it are skipped.
- `--ai-diagnose`: on a target failure, sends the compiler/linker's error
  output to the configured AI provider and prints its suggested cause and
  fix. Never automatic — see [AI features](#ai-features-1) below.

Builds are incremental: a source file whose object is already newer than
it is skipped. **This is timestamp-only** — there's no per-header
dependency tracking yet, so editing a header won't by itself trigger a
rebuild of the `.cpp` files that include it. Run `charpente clean` if a
build looks stale after a header change.

Output per target:

```
  [ok]         app -> build/Debug/app/app
  [up to date] otherlib
  [FAILED]     broken: <compiler/linker error, last line>
```

## `charpente run`

```
charpente run [--target NAME] [--config Debug|Release] [--no-build] [-- program args...]
```

Builds (unless `--no-build`) then executes the target.

- `--target`: which target to run. Optional if the workspace has exactly
  one target; required (with a clear error listing the known names)
  otherwise.
- `--no-build`: skip the build step and run whatever's already in
  `build/<config>/<target>/` — fails clearly if nothing's there yet.
- Arguments after `--` are forwarded to the program's own `argv`, and the
  `--` separator itself is stripped (not passed as a literal argument):

  ```bash
  charpente run -- --verbose input.txt
  # the program sees argv = ["--verbose", "input.txt"], not ["--", "--verbose", "input.txt"]
  ```

## `charpente test`

```
charpente test [--config Debug|Release]
```

Builds and runs every target declared with `.kind(Kind.TEST)`. A test
"passes" if the program exits with code 0. Prints a `[PASS]`/`[FAIL]` line
per test target and a summary (`N/M test target(s) passed.`); exits 0 only
if every test passed. A workspace with no `Kind.TEST` targets prints a
note and exits 0 (not an error — most workspaces don't have tests yet).

## `charpente package`

```
charpente package [--target NAME] [--config Release] [--format zip|installer]
                  [--version X.Y.Z] [--maintainer "Name <email>"] [--output PATH]
```

Builds the target, then packages the result.

- `--format zip` (default): a `.zip` of the build output directory
  (object files excluded), written to `dist/<target>-<config>.zip`. Needs
  no external tool, works identically on every platform.
- `--format installer`: a real platform installer — see
  [Building a real installer](#building-a-real-installer) below.
- `--version`: embedded in the installer's metadata (Inno Setup
  `AppVersion`, `.deb` `Version`, `.pkg` version). Default `1.0.0`.
- `--maintainer`: the `.deb` control file's `Maintainer` field
  (`--format installer` on Linux only). Default `unknown <unknown@example.com>`
  — set this for a real package.
- `--output`: override the output path (zip format only).

### Building a real installer

```bash
charpente package --format installer --config Release --version 1.2.3
```

| Platform | Tool needed | Produces | If the tool is missing |
|---|---|---|---|
| Windows | [Inno Setup](https://jrsoftware.org/isinfo.php) (`iscc` on `PATH`) | `dist/<target>-setup.exe` | The `.iss` script is still written to `dist/`; install Inno Setup, then run the printed `iscc ...` command |
| Linux | `dpkg-deb` (usually preinstalled on Debian/Ubuntu) | `dist/<target>.deb` | The staging tree (`DEBIAN/control` + binary) is still written to `dist/`; run the printed `dpkg-deb ...` command on a Debian/Ubuntu machine |
| macOS | `pkgbuild` (via Xcode Command Line Tools) | `dist/<target>.pkg` | The staging tree is still written to `dist/`; run the printed `pkgbuild ...` command on macOS |

Charpente never silently falls back to a zip when the installer tool is
missing, and never claims an installer was built when only its input was
prepared — the fallback message always names the exact command to finish
the job yourself.

## `charpente clean`

```
charpente clean
```

Removes the whole `build/` directory (every config, every target).
Prints what it removed, or says there was nothing to clean.

## `charpente ask`

```
charpente ask [--file PATH] <question, free text, any words including ones starting with '->
```

Asks the configured AI provider a question. If a `.charpente` workspace
can be found (same discovery rules as every other command), its name and
target list are included as context. Prints `(using <provider>)` then the
answer.

Without any provider configured, prints a plain explanation of how to
configure one instead of an error — see [AI features](#ai-features-1).

`ask`'s question is deliberately *not* parsed by the same mechanism as
other commands' flags: a natural-language question can legitimately start
with a dash (`charpente ask "--verbose isn't printing anything"`), so
everything after an optional `--file PATH` is treated as literal question
text, dashes included. `charpente ask --help` / `-h` still shows usage,
as a special case.

## AI features

Charpente works completely without any AI provider configured — installing
it with just `pip install charpente` (no `[ai]` extra) pulls in zero AI
dependency, and every command above works fully. Configuring a provider
unlocks `charpente ask` and `--ai-diagnose`.

Set one of these environment variables — the first match, in this order,
wins:

| Provider | Environment variable | Extra dependency |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY=sk-ant-...` | `pip install "charpente[ai]"` |
| OpenAI | `OPENAI_API_KEY=sk-...` | `pip install "charpente[ai]"` |
| Local (Ollama, llama.cpp server, LM Studio, any OpenAI-compatible server) | `CHARPENTE_AI_URL=http://localhost:11434/v1` | none — stdlib `urllib` only |

`CHARPENTE_AI_PROVIDER=anthropic\|openai\|local\|none` forces a specific
choice regardless of what else is set (`none` explicitly disables AI even
if a key is present). `CHARPENTE_AI_MODEL` overrides the default model for
whichever provider ends up active.

`--ai-diagnose` is opt-in on every single `build` invocation where you
want it — there's no "always diagnose" setting — because every call costs
a request and sends the compiler/linker's error output (which can include
snippets of your source) to whichever provider you've configured.
