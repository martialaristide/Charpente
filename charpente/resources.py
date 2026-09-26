"""Resource-aware builds: warn before the disk fills, keep compilers from exhausting memory, and (opt-in) build gently on battery or on a hot machine.

`plan_jobs` is a pure function of a `Sample` (what the machine looks like right now), so every rule is testable without a battery or a full disk; `sample()` reads the real
machine. Nothing here ever makes a build fail or produce different output: it only chooses how many actions run at once and reports what it saw (`resource.*` events).

* **Memory** (always on): a C++ compile can take several hundred MB. When free memory could not hold one such compile per job, the job count is lowered (and
  `resource.low_memory` is emitted): an out-of-memory kill would be worse than a slower build.
* **Disk** (always on): under 500 MB free on the build folder's drive emits `resource.low_disk`.
* **Eco mode** (`--eco`, or `CHARPENTE_ECO=on`; `CHARPENTE_ECO=auto` applies it only when needed): on battery power the job count is halved (`resource.on_battery`); on a machine
  that reports itself hot (Linux thermal zones over 85 C) it is quartered. Windows and macOS report no temperature: only the battery rule applies there.

An interrupted build (a power cut, Ctrl+C) resumes without recompiling what finished: every completed action was recorded, and its result is also in the content cache.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

MEMORY_PER_JOB = 700 * 1024 * 1024          # a heavy C++ translation unit, as a planning figure
LOW_DISK_BYTES = 500 * 1024 * 1024
HOT_CELSIUS = 85.0


@dataclass(frozen=True)
class Sample:
    on_battery: Optional[bool] = None       # None: unknown (a desktop, or no way to tell)
    free_memory: Optional[int] = None       # bytes available to start programs
    free_disk: Optional[int] = None         # bytes free where the build writes
    temperature: Optional[float] = None     # hottest thermal zone, degrees Celsius


@dataclass(frozen=True)
class Plan:
    jobs: int
    events: Tuple[Tuple[str, dict], ...] = ()   # type: ignore[type-arg]
    notes: Tuple[str, ...] = ()


def plan_jobs(requested: int, cpus: int, sample: Sample, *, eco: str = "off", build_dir: str = "") -> Plan:
    """The job count to use and the resource events/notes to report. `eco` is "off", "auto" or "on"; `requested` 0 means one job per CPU."""
    jobs = requested if requested > 0 else max(cpus, 1)
    events: List[Tuple[str, dict]] = []  # type: ignore[type-arg]
    notes: List[str] = []
    if sample.free_disk is not None and sample.free_disk < LOW_DISK_BYTES:
        events.append(("resource.low_disk", {"path": build_dir, "free_bytes": int(sample.free_disk)}))
        notes.append(f"only {sample.free_disk // (1024 * 1024)} MB are free where the build writes")
    if sample.free_memory is not None and sample.free_memory < jobs * MEMORY_PER_JOB:
        safe = max(1, int(sample.free_memory // MEMORY_PER_JOB))
        if safe < jobs:
            events.append(("resource.low_memory", {"free_bytes": int(sample.free_memory)}))
            notes.append(f"{sample.free_memory // (1024 * 1024)} MB of memory are available: running {safe} job(s) instead of {jobs}")
            jobs = safe
    if eco in ("on", "auto"):
        hot = sample.temperature is not None and sample.temperature >= HOT_CELSIUS
        battery = bool(sample.on_battery)
        if eco == "on" or hot or battery:
            reduced = jobs
            if hot:
                reduced = max(1, min(reduced, max(cpus, 1) // 4 or 1))
                notes.append(f"the machine reports {sample.temperature:.0f} C: running {reduced} job(s)")
            elif battery:
                reduced = max(1, min(reduced, max(cpus, 1) // 2 or 1))
                events.append(("resource.on_battery", {"jobs": reduced}))
                notes.append(f"on battery power: running {reduced} job(s)")
            elif eco == "on":
                reduced = max(1, min(reduced, max(cpus, 1) // 2 or 1))
                notes.append(f"eco mode: running {reduced} job(s)")
            jobs = reduced
    return Plan(jobs, tuple(events), tuple(notes))


# ---------------------------------------------------------------------- reading the machine
def _windows_status() -> Tuple[Optional[bool], Optional[int]]:
    import ctypes
    from ctypes import wintypes

    class PowerStatus(ctypes.Structure):
        _fields_ = [("ACLineStatus", wintypes.BYTE), ("BatteryFlag", wintypes.BYTE), ("BatteryLifePercent", wintypes.BYTE), ("SystemStatusFlag", wintypes.BYTE),
                    ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    kernel = ctypes.windll.kernel32                       # type: ignore[attr-defined,unused-ignore]   # only exists on Windows
    power = PowerStatus()
    on_battery: Optional[bool] = None
    if kernel.GetSystemPowerStatus(ctypes.byref(power)):
        on_battery = {0: True, 1: False}.get(power.ACLineStatus)
    memory = MemoryStatus()
    memory.dwLength = ctypes.sizeof(MemoryStatus)
    free = int(memory.ullAvailPhys) if kernel.GlobalMemoryStatusEx(ctypes.byref(memory)) else None
    return on_battery, free


def _linux_status() -> Tuple[Optional[bool], Optional[int], Optional[float]]:
    on_battery: Optional[bool] = None
    base = Path("/sys/class/power_supply")
    try:
        supplies = list(base.iterdir())
    except OSError:
        supplies = []
    online = [s for s in supplies if (s / "type").is_file() and (s / "type").read_text().strip() == "Mains" and (s / "online").is_file()]
    if online:
        on_battery = not any((s / "online").read_text().strip() == "1" for s in online)
    free: Optional[int] = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                free = int(line.split()[1]) * 1024
    except OSError:
        pass
    temps: List[float] = []
    for zone in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            temps.append(int(zone.read_text().strip()) / 1000.0)
        except (OSError, ValueError):
            continue
    return on_battery, free, max(temps) if temps else None


def sample(build_dir: Path) -> Sample:
    """What this machine looks like now. Anything that cannot be read is None (and its rule is simply not applied)."""
    on_battery: Optional[bool] = None
    free_memory: Optional[int] = None
    temperature: Optional[float] = None
    try:
        if sys.platform == "win32":
            on_battery, free_memory = _windows_status()
        elif sys.platform.startswith("linux"):
            on_battery, free_memory, temperature = _linux_status()
    except Exception:
        pass                                                      # a probe must never break a build
    probe = build_dir
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        free_disk: Optional[int] = shutil.disk_usage(probe).free
    except OSError:
        free_disk = None
    return Sample(on_battery, free_memory, free_disk, temperature)


def eco_mode(flag: bool = False, env: Optional[dict] = None) -> str:  # type: ignore[type-arg]
    """"on" with --eco or CHARPENTE_ECO=on/1, "auto" with CHARPENTE_ECO=auto, else "off"."""
    value = str((os.environ if env is None else env).get("CHARPENTE_ECO", "")).strip().lower()
    if flag or value in ("on", "1", "true", "yes"):
        return "on"
    return "auto" if value == "auto" else "off"
