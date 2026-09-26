# Installing, first run, and uninstalling

## Install

```bash
pip install charpente                 # when a release is published (see "Status" below)
pip install -e .                      # from a checkout of the repository
pip install "charpente[tui,ai,fast]"  # optional extras: terminal UI, AI providers' SDKs, faster hashing
```

Python 3.9 or newer. Charpente itself has no compiled part; it uses the C/C++ compiler already on your machine (or one it installs for you, see below).

> **Status**: the package builds and passes `twine check`, but **nothing has been uploaded to PyPI**: publishing is a decision for the maintainer, never done automatically.

## First run: `charpente setup`

```bash
charpente setup                # look at this machine, then offer what would help
charpente setup --yes          # accept the offers that only download open tools
charpente setup --lang fr      # remember French for messages
```

`setup` runs the same checks as `charpente doctor` and turns what is missing into steps:

| Step | When | What it does |
|---|---|---|
| Compiler | no C/C++ compiler found | offers `charpente toolchain install zig` (a download of the open-source zig compiler). Or install GCC, Clang or MSVC yourself. |
| git | not found | advice only: git is used by `commit`/`push`/`pr`, repository dependencies and releases. |
| clangd | not found | advice only (optional): code completion in Studio and VS Code. |
| Debugger | none found | advice only (optional): gdb 14+ or lldb-dap for `charpente debug`. |
| Language | not chosen yet | asks for English or French and remembers it in `~/.charpente/settings.json`. |

Rules it keeps: it asks before every download and **starts none without a yes** (`--yes` is a yes for open tools only); it **never accepts a vendor licence for you** (the Android NDK and similar need
`charpente toolchain install ndk --accept-android-license`, typed by you); it never runs an installer that is not Charpente's own (git, gdb and clangd are left to your system); when it is not connected to a terminal
and has no `--yes`, it only reports. `CHARPENTE_LANG` always overrides the remembered language, so scripts and CI are not affected by a developer's choice.

## What Charpente keeps on your machine

Everything is under `~/.charpente` (or `CHARPENTE_HOME`), plus the cache folder if `CHARPENTE_CACHE_DIR` moves it:

| Group | Contains | Can be recreated? |
|---|---|---|
| `cache` | build cache, the cache server's store, remembered compiler identities | yes (rebuilt) |
| `toolchains` | compilers and SDKs installed by Charpente (zig, emsdk, NDK...) | yes (downloaded again) |
| `packages` | downloaded and built packages, local recipes | yes |
| `modules` | installed extension modules | yes |
| `android` | the Android debug keystore | yes (a new one; debug-signed apps must be reinstalled) |
| `trust` | which files and keys you decided to trust | yes (you are asked again) |
| `settings` | remembered preferences | yes |
| `keys` | **signing keys for releases** | **no** |

## Uninstalling: `charpente self uninstall`

```bash
charpente self uninstall                       # DRY RUN: lists what would be removed and how big it is
charpente self uninstall --yes                 # removes every group except `keys`
charpente self uninstall --only cache --yes    # only the cache
charpente self uninstall --keys --yes          # also the signing keys
pip uninstall charpente                        # the program itself (the command prints this line for you)
```

Safety rules: **nothing is removed without `--yes`**; the `keys` group is never removed unless you say `--keys` (a key that signed a release cannot be recreated, and users trust it); projects and the `.charpente`
files in them are never touched; only the entries listed above are removed, so if `CHARPENTE_HOME` points at a folder that also holds your own files, they stay (and the folder is removed only when it ends up empty);
a symbolic link or junction inside the folder is unlinked, never followed; a `CHARPENTE_CACHE_DIR` outside the config folder is removed only if it looks like a cache (its name contains `cache` or `charpente`, and it is not a
drive root or your home folder), otherwise it is reported and left for you. Charpente cannot always delete the program it is running from (notably on Windows), so the last step is pip's.
