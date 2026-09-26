# Git and GitHub

Git stays the source of truth: these commands run `git` (and `gh` when installed) and add the quality gate, commit-message discipline
and reporting. They never rewrite history, force-push without typed confirmation, or write a token to a file.

| Command | What it does |
|---|---|
| `charpente status` | Git state (branch, upstream, ahead/behind, staged/modified/untracked), last build, last gate result; `--json` |
| `charpente commit` | `check --changed` (level `rapide`, `--level` to change), then commits. `-m` must be a **Conventional Commit** (`--any-format` to override). Without `-m` it drafts one from the changed paths (`--ai`: the configured provider drafts it from the diff, which is sent to it) and opens your editor so you always review it. `-a` stages modified tracked files. `--no-verify` skips the gate, warns, and records it. |
| `charpente push` | The `standard` gate on the whole project, then push. `--force-with-lease` needs you to type the branch name. |
| `charpente pr` | Opens a pull request: summary, commits, last gate result, a **warning for commits without a passing gate record**, optional SBOM section (`--sbom`). Uses `gh` if installed, else the GitHub API with a token from `GH_TOKEN`/`GITHUB_TOKEN` or the system keyring. `--dry-run` prints it; `--push` pushes first. |
| `charpente hooks install/uninstall/status` | See [quality.md](quality.md) |
| `charpente ci init` | Writes `.github/workflows/charpente.yml` |
| `charpente release` | Version, changelog, packages, checksums, signature, provenance, commit and tag; publishes only with `--publish` |
| `charpente sign init/list/public/verify` | Ed25519 release keys |

Events: `vcs.commit_created`, `vcs.push_done`, `vcs.pr_opened`, and the `gate.*` events.

## `charpente ci init`

The workflow uses `permissions: contents: read`, a matrix (Ubuntu/Windows/macOS x Debug/Release), the Charpente cache, `charpente check`,
`build` and `test`, plus jobs for the platforms the workspace declares (`ws.platforms([...])` or `--platforms`): Android (the runner's
NDK), HarmonyOS (`charpente toolchain install ohos`), WebAssembly (Emscripten), other cross targets (zig), FreeBSD (in a VM). Actions are
pinned to major-version tags; for stricter supply-chain hygiene pin them to commit SHAs. `--install` sets how CI installs Charpente
(useful until it is published on PyPI). The YAML is emitted from data by a small emitter and structurally tested; it has **not been run on
GitHub** from here. There is no qemu step: Charpente does not run foreign binaries (except WebAssembly).

## `charpente release`

```
charpente release --dry-run                 # the plan: version, changelog section; changes nothing
charpente release [--bump auto|major|minor|patch|1.2.3] [--platforms linux-arm64,windows-x64] [--key release]
charpente release --publish                 # also: push the commit and tag, create the GitHub release (gh)
```

Preconditions (CH8016 otherwise): a clean tree, on the default branch, not behind the remote, commits since the last tag, the gate passing at `strict`.
The next version comes from the Conventional Commits since the last `v*` tag (`feat` -> minor, `fix`/`perf`/`refactor` -> patch, `!` or a
`BREAKING CHANGE` footer -> major; **before 1.0**, breaking -> minor and feat -> patch). It then updates the version declared in the workspace
(`Workspace("x", version="1.2.3")` or `charpente.toml`), prepends the changelog, builds the zip packages (Release) for each platform, writes SBOMs,
`SHA256SUMS`, a **signature** of it (`SHA256SUMS.sig`, Ed25519) and the release's public key, and an **in-toto/SLSA v1 provenance** statement wrapped in a
signed DSSE envelope, then commits `chore(release): vX.Y.Z` and tags it. Nothing leaves the machine without `--publish`.

**Provenance honesty:** produced on your machine it says what was built, from which commit, with which command, and names its builder as
`charpente:local-build (not an isolated builder: SLSA build level 1 documentation only)`. SLSA level 3 needs an isolated hosted builder: in
GitHub Actions use `actions/attest-build-provenance` as well. Installers (`--format installer`), notarisation and store uploads are separate.

## Signing keys

`charpente sign init [name]` creates an Ed25519 key in `~/.charpente/keys/`. The private part is stored **encrypted under your passphrase**
(scrypt-derived pad; a wrong passphrase is detected, not silently accepted) -- forget the passphrase and the key is gone. The passphrase comes from
`CHARPENTE_KEY_PASSPHRASE` (CI) or a prompt, never a file or argument. Keys are pure-Python Ed25519 (RFC 8032 vectors tested); for a hardware key or
an HSM, sign the checksums yourself. `charpente sign verify FILE SIG --public KEY|FILE` checks a signature.

## Limits

- `pr`'s API path and `release --publish` were tested with fakes and a local bare remote, not against GitHub. The `gh` path follows its documented CLI.
- Release artifacts are zip packages; `.deb`/installers, AAB/IPA, and store uploads are not part of `charpente release` yet.
- Pull-request attachments are not possible through the API: the SBOM is summarised in the description and written to `dist/`.
