# Reproducible builds and budgets

Two ways to make a build *trustworthy*: prove that it produces the same bytes wherever and whenever it runs, and make it fail when it grows beyond limits you set.

## Reproducible builds

```bash
charpente build --reproducible          # its own build folder (`build/Debug-repro`), so it never mixes with your normal build
charpente verify-reproducible           # builds twice in two different folders and compares every output, byte for byte
```

`--reproducible` builds with a *flavour* that removes what makes output depend on the machine:

* the project folder is rewritten to `/src` in everything the compiler embeds (`-ffile-prefix-map`: debug info, `__FILE__`, assertion messages);
* the clock is fixed (`SOURCE_DATE_EPOCH=1700000000`; `__DATE__`/`__TIME__` follow it in GCC and Clang), `TZ=UTC`, `LC_ALL=C`;
* the linker writes no timestamp (`--no-insert-timestamp` on MinGW) and no build-id (`--build-id=none` on GCC/Clang for ELF);
* static libraries are made deterministically (no timestamps, owners or modes).

**It is also what makes the [shared cache](shared-cache.md) work across machines**: cache keys are relocatable only in this flavour.

`charpente verify-reproducible [--config Debug|Release] [--platform OS-ARCH] [--keep] [--json]` copies the project (without `build/`, `.git`, `node_modules`) into two temporary folders with
*different names and depths*, builds each with `--reproducible --no-cache`, and compares the outputs. When they differ it prints the first differing byte and the likely causes it recognises
(an embedded path, a timestamp, a build-id). `--keep` keeps the two folders so you can inspect them. Exit code 0 means identical, 1 means different or a build failed (CH8025).

What it proves and what it does not: identical bytes from two *folders on this machine, with this toolchain*. It does not prove the same result on another OS or another compiler
version, and a program that itself writes `__TIMESTAMP__` or random data into its output will (correctly) be reported as not reproducible.

**Limits**: GNU-style toolchains only (GCC, Clang, MinGW, zig). MSVC-style ones need `/Brepro`, which Charpente does not drive yet, and refuses rather than half-supports. macOS linkers get no
extra flags. Verified on Windows with MinGW-w64 only.

## Budgets

```python
with Workspace("app") as ws:
    ws.budget(build_time="90s", total_size="40MB")      # the whole build
    with Target("app") as t:
        t.budget(size="2MB")                            # the file this target produces
```

After `charpente build`, each budget is checked; one that is exceeded **fails the build** (exit code 1) and emits a `budget.exceeded` event, with the measured and the allowed value. A build that
stays within its budgets says so (`budget.checked`). `--no-budget` turns the check off for one run.

* Sizes accept `B, KB, MB, GB, TB` (also `KiB`...; **1 MB = 1024 KB**); durations accept `ms, s, m, h` and combinations (`1h30m`). A typo (`sise=`) or a value you cannot read is error **CH1026**: a budget must never silently mean "no budget".
* A target's size is the size of the file it produced (a program, a library, a firmware image). A target with a size budget that produced no output file in this run (a header-only target, for instance) cannot be measured: the build says so (`[budget skipped]`) instead of passing silently.
* Size budgets are most meaningful on stripped Release builds (`charpente build --config Release`); mobile and XR budgets are about the shipped file.
* Build time includes only this run; a build served from the cache is fast and passes, which is the point of a cache.

Use them in CI to catch a dependency that suddenly adds 5 MB, or a header change that doubles build time.
