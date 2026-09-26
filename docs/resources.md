# Resource-aware builds, eco mode and resuming

A build should not exhaust your memory, fill your disk, or drain a laptop battery without telling you. Charpente looks at the machine before it starts and reports what it saw. **Nothing here ever
changes what a build produces**; it only chooses how many actions run at once, and says so.

## What is checked

| Signal | Rule | Event / message |
|---|---|---|
| Free memory | A heavy C++ compile can take several hundred MB. When free memory could not hold one such compile (about 700 MB planned) per job, the job count is lowered (never below 1). An out-of-memory kill is worse than a slower build. Always on; an explicit `-j N` is lowered only if memory really cannot hold it. | `resource.low_memory`, and a hint: "3724 MB of memory are available: running 5 job(s) instead of 8" |
| Free disk | Less than 500 MB free where the build writes: a warning, nothing else changes. Always on. | `resource.low_disk`, "low disk space" |
| Battery | With eco mode, on battery power the job count is halved. | `resource.on_battery` |
| Heat | With eco mode, on a machine that reports 85 C or more (Linux thermal zones) the job count is quartered. Windows and macOS report no temperature: only the battery rule applies there. | hint |

A reading that cannot be taken (a desktop with no battery, a system that does not say) is treated as *unknown*, and its rule is simply not applied.

## Eco mode

```bash
charpente build --eco              # halve the jobs, now
CHARPENTE_ECO=auto charpente build # only when on battery or hot
CHARPENTE_ECO=on                   # always (same as --eco)
```

It is **off by default**: nothing changes silently. `--eco` is accepted by every command that builds (`build`, `run`, `test`, `package`, `dev`, `deploy`, `generate`, `flash`...). One CPU stays one CPU.

## Resuming an interrupted build

A power cut, a closed laptop lid or Ctrl+C in the middle of a build costs nothing that had finished: every completed action was recorded and its result is in the content cache, so running `charpente build` again
re-does only what was not finished. Verified by killing a real build (the whole process tree) part-way through 14 compiles and running it again: the compiles that had finished were not run twice, and the result ran.
What can be lost is the action that was running at the moment of the interruption (it is simply run again).

## Not done

Battery and memory are read on Windows and Linux only (macOS reports neither yet: those rules are skipped there). No Linux or macOS run has verified the probes; on Windows they were checked against the real machine
and against simulated readings.
