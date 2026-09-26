"""Deploying to every connected device at once, and following all their logs in one stream.

`charpente deploy --device all` asks each ready Android device which CPU ABIs it runs, builds **one** APK with the native libraries for exactly those ABIs, installs and
starts it on every device in parallel, and reports each device's outcome (one device failing does not stop the others). With `--logs`, the devices' `logcat` streams are merged into one
output, every line tagged with its device, until Ctrl+C (or `--log-seconds`).
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import android
from .core import process
from .errors import ChError

#: getprop ro.product.cpu.abilist -> the Charpente platform that produces the matching libraries
ABI_TO_PLATFORM = {abi: platform for platform, (abi, _triple) in android.ABIS.items()}


def parse_abilist(text: str) -> List[str]:
    return [a.strip() for a in text.strip().split(",") if a.strip()]


def platform_for(abis: Sequence[str]) -> Optional[str]:
    """The first ABI of the device (its preferred one) that Charpente can build for, as a platform name; None when it supports none."""
    for abi in abis:
        if abi in ABI_TO_PLATFORM:
            return ABI_TO_PLATFORM[abi]
    return None


@dataclass
class Device:
    serial: str
    abis: List[str] = field(default_factory=list)
    platform: Optional[str] = None


@dataclass
class Outcome:
    serial: str
    ok: bool
    detail: str = ""


def discover(adb: str, run: Callable[..., process.ProcessResult] = process.run) -> List[Device]:
    """Every ready device with its ABIs (a device whose properties cannot be read is listed without any, and later skipped)."""
    listed = android.parse_devices(run([adb, "devices"], timeout=60).output)
    devices: List[Device] = []
    for serial, state in listed:
        if state != "device":
            continue
        result = run([adb, "-s", serial, "shell", "getprop", "ro.product.cpu.abilist"], timeout=60)
        abis = parse_abilist(result.stdout) if result.returncode == 0 else []
        devices.append(Device(serial, abis, platform_for(abis)))
    return devices


def split_supported(devices: Sequence[Device]) -> Tuple[List[Device], List[Device]]:
    """(devices we can build for, devices we cannot)."""
    return [d for d in devices if d.platform], [d for d in devices if not d.platform]


def platforms_needed(devices: Sequence[Device]) -> List[str]:
    """The platforms to build, in the order Charpente lists them, without duplicates."""
    needed = {d.platform for d in devices if d.platform}
    return [p for p in android.ABIS if p in needed]


def deploy_all(devices: Sequence[Device], install: Callable[[Device], None], *, workers: int = 4) -> List[Outcome]:
    """Run `install(device)` for every device in parallel; a failure is recorded for that device and never stops the others."""
    def one(device: Device) -> Outcome:
        try:
            install(device)
            return Outcome(device.serial, True)
        except ChError as exc:
            return Outcome(device.serial, False, f"[{exc.code}] {exc.message}")
        except Exception as exc:                                      # a bug in one device's path must not hide the results of the others
            return Outcome(device.serial, False, f"{type(exc).__name__}: {exc}")

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(devices) or 1)), thread_name_prefix="deploy") as pool:
        return list(pool.map(one, devices))


class LogMerger:
    """Follows `adb logcat` on several devices and prints one interleaved stream; each line carries its device's tag.

    Lines from one device stay in order. `emit(device, line)` is called under a lock, so lines from different devices never interleave inside a line.
    """

    def __init__(self, adb: str, devices: Sequence[Device], emit: Callable[[str, str], None], *, flt: str = "", start: Optional[Callable[..., process.LineStream]] = None) -> None:
        self._emit = emit
        self._filter = flt.lower()
        self._lock = threading.Lock()
        self._streams: List[process.LineStream] = []
        self.finished = threading.Event()
        self._open = len(devices)
        make = start or process.LineStream
        for device in devices:
            def on_line(line: str, serial: str = device.serial) -> None:
                if not self._filter or self._filter in line.lower():
                    with self._lock:
                        self._emit(serial, line)

            def on_exit(code: int) -> None:
                with self._lock:
                    self._open -= 1
                    if self._open <= 0:
                        self.finished.set()

            self._streams.append(make([adb, "-s", device.serial, "logcat", "-v", "time"], on_line, on_exit))
        if not devices:
            self.finished.set()

    def stop(self) -> None:
        for stream in self._streams:
            stream.stop()
        self.finished.set()

    def wait(self, seconds: Optional[float] = None) -> bool:
        """True when every log ended by itself; False when `seconds` passed first.

        Waits in short slices: one long `Event.wait()` cannot be interrupted by Ctrl+C on Windows.
        """
        deadline = None if seconds is None else time.monotonic() + seconds
        while True:
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                return self.finished.is_set()
            if self.finished.wait(0.25 if left is None else min(0.25, left)):
                return True


def tag(serial: str, width: int = 0) -> str:
    return f"[{serial}]".ljust(width)


def summarize(outcomes: Sequence[Outcome], skipped: Sequence[Device]) -> Dict[str, List[str]]:
    return {"ok": [o.serial for o in outcomes if o.ok], "failed": [f"{o.serial}: {o.detail}" for o in outcomes if not o.ok],
            "skipped": [f"{d.serial}: runs {', '.join(d.abis) or 'unknown ABIs'} (Charpente builds arm64-v8a, armeabi-v7a, x86_64)" for d in skipped]}
