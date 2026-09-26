# The quality gate: `charpente check`

Nothing should be committed, pushed or released without passing a configurable gate. `charpente check` runs the same checks
locally, in Git hooks and in CI (`charpente ci init`).

```
charpente check [--level rapide|standard|strict] [--changed] [--fix] [--only NAME] [--skip NAME] [--platform P] [--json]
charpente check --list        # the checks and their levels
charpente check --init        # write .charpente/quality.toml
```

Exit code 0 when nothing failed, 1 otherwise. Every problem becomes a located `diagnostic.emitted` event (clickable in an editor,
annotated in GitHub Actions); each check emits `gate.check_started/passed/failed` and a blocked gate emits `gate.blocked`.

## Levels

| Level | Checks |
|---|---|
| **rapide** (pre-commit) | `build` (incremental), `format` (clang-format), `dsl-lint`, `secrets`, `file-size` |
| **standard** (pre-push) | + `warnings` (changed sources compiled with `-Wall -Wextra -Werror`), `clang-tidy`, `cppcheck`, `tests` (with flaky detection) |
| **strict** (release/PR) | + `sanitizers` (ASan+UBSan), `coverage` (gcov, minimum configurable), `platforms` (cross builds), `audit` (OSV), `licenses`, `sbom` |

Levels are cumulative. `--changed` narrows the per-file checks (secrets, size, format, warnings, tidy) to files modified since the
last commit; `--fix` applies safe fixes (formatting, clang-tidy's fixes) **then re-runs the verification**.

## A check that cannot run is *skipped, visibly*

`format`, `clang-tidy` and `cppcheck` need their tools; `sanitizers`/`coverage` need toolchain support; `audit` needs the network and a
lock file. When something is missing the check reports **SKIP** with the reason instead of passing silently, and the summary says
how many checks did not run. In CI, set `fail_on_skipped = true` so a missing tool fails the gate.

## `.charpente/quality.toml`

```toml
[gate]
level = "standard"
fail_on_skipped = false

[checks.format]        # every check can be tuned or disabled: enabled = false
style = "file"

[checks.secrets]
allow = ["tests/fixtures/*"]

[checks.coverage]
minimum = 70
exclude = ["tests/*"]

[checks.licenses]
allow = ["MIT", "Apache-2.0", "BSD-3-Clause"]

[checks.platforms]
platforms = ["linux-arm64", "wasm32-wasi"]
```

## What the checks do

- **secrets**: known token formats (AWS, GitHub, Slack, Google, Stripe, private-key blocks, JWTs, `sk-` keys) and generic
  `password/secret/token = "..."` assignments whose value has high entropy. Placeholders (`changeme`, `${VAR}`, `xxxx`) are ignored, a line marked
  `charpente:allow-secret` is skipped, and findings **never print the secret** (only its first characters).
- **warnings**: the compile command from `build/compile_commands.json` turned into `-fsyntax-only -Werror`, only for changed files.
- **tests**: `charpente test --retries 1`; a test that fails then passes is reported as **flaky** (a warning finding).
- **sanitizers / coverage**: the toolchain is *probed* (a tiny program is built and run with the flags); MinGW, for instance, has no
  AddressSanitizer and the check is skipped with the linker's reason. Build flavours get their own directory (`build/Debug-san-address/`,
  `build/Debug-cov/`): `charpente test --sanitize address,undefined`, `charpente test --coverage`.
- **platforms**: builds each listed platform for which this machine has a toolchain, and names the ones it skipped.
- **audit / licenses / sbom**: OSV lookup (only package URLs and versions are sent; skipped offline), an allow-list of SPDX licenses (OR/AND
  expressions understood), and SPDX 2.3 + CycloneDX 1.5 documents in `dist/`.

Modules can add checks (extension kind `quality_check`; `run(workspace_root, files, fix)`), and the built-in ones are registered the same way.

## Git hooks

```
charpente hooks install     # pre-commit -> check --level rapide --changed; pre-push -> check --level standard
charpente hooks uninstall   # removes only hooks Charpente wrote; restores one it replaced
charpente hooks status
```

A hook Charpente did not write is never overwritten without `--force` (kept as `<name>.pre-charpente`). Git lets anyone skip hooks with
`--no-verify`; Charpente cannot prevent that, so it **records which Git trees passed the gate**, and `charpente pr` flags every commit
without a record in the pull request description.

## Limits

- The gate runs what is installed; a strict gate on a machine without clang-tidy, cppcheck, clang-format or sanitizer runtimes skips those checks.
- Sanitizers and coverage were verified for real only on the supported path here (coverage with GCC/gcov); ASan/UBSan were verified to be
  *refused correctly* on MinGW, and are unit-tested elsewhere.
- Coverage is line coverage through gcov (`llvm-cov gcov` for Clang); branch coverage and HTML reports are not produced.
- MSVC-style toolchains are not driven by the `warnings`, sanitizer and coverage checks yet.
