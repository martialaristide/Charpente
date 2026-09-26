"""Target platforms and their support tiers.

A platform is what you build *for*: an OS and an architecture, written
`os-arch` (`windows-x64`, `linux-arm64`, `android-arm64`, `wasm32-wasi`...).
Each carries a **support tier**, so documentation and tools never promise more
than exists:

* **Tier 1** -- build *and tests run* in CI at every commit; official packages;
  blocks a release when it fails.
* **Tier 2** -- the build is verified in CI (cross-compiled or under an
  emulator); tests on real hardware are occasional and documented.
* **Tier 3** -- supported through a module; it should compile; no CI guarantee.

The tier is a statement about what the *project* verifies, not about what a
particular machine can do: `charpente platforms` shows both -- the tier, and
whether *this* machine has a toolchain that can build the platform right now.
"""
from __future__ import annotations

import platform as _platform
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .errors import ChError

_ARCH_ALIASES = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64", "x86": "x86", "i386": "x86",
                 "i686": "x86", "armv7l": "arm", "armv7": "arm", "riscv64": "riscv64", "wasm32": "wasm32"}


@dataclass(frozen=True)
class Platform:
    name: str
    os: str                                   # windows | linux | macos | android | ios | ohos | wasm | wasi | freebsd | ...
    arch: str                                 # x64 | arm64 | arm | x86 | riscv64 | wasm32 | cortex-m4 ...
    tier: int
    #: ABI -> target triple. The ABI a toolchain uses is its own business (msvc vs gnu vs musl).
    triples: Tuple[Tuple[str, str], ...]
    family: str = "desktop"                   # desktop | mobile | xr | web | embedded | server
    #: Something the user must install that Charpente cannot legally/practically provide.
    needs: str = ""
    note: str = ""
    #: Microcontroller targets: the CPU (GCC spelling), float ABI and FPU.
    cpu: str = ""
    float_abi: str = ""
    fpu: str = ""

    def triple(self, abi: Optional[str] = None) -> str:
        table = dict(self.triples)
        if abi and abi in table:
            return table[abi]
        return self.triples[0][1]

    @property
    def abis(self) -> List[str]:
        return [a for a, _ in self.triples]


def _p(name: str, os_: str, arch: str, tier: int, triples: Dict[str, str], **kw: str) -> Platform:
    return Platform(name=name, os=os_, arch=arch, tier=tier, triples=tuple(triples.items()), **kw)


_TABLE: List[Platform] = [
    # ---- desktop
    _p("windows-x64", "windows", "x64", 1, {"msvc": "x86_64-windows-msvc", "gnu": "x86_64-windows-gnu"}),
    _p("windows-arm64", "windows", "arm64", 2, {"msvc": "aarch64-windows-msvc", "gnu": "aarch64-windows-gnu"},
       note="Tier 2 today: cross-compiled, not yet executed in CI (target: Tier 1)."),
    _p("linux-x64", "linux", "x64", 1, {"gnu": "x86_64-linux-gnu", "musl": "x86_64-linux-musl"}),
    _p("linux-arm64", "linux", "arm64", 2, {"gnu": "aarch64-linux-gnu", "musl": "aarch64-linux-musl"},
       family="server", note="Also Raspberry Pi 4/5 and Jetson boards running Linux."),
    _p("linux-riscv64", "linux", "riscv64", 2, {"gnu": "riscv64-linux-gnu", "musl": "riscv64-linux-musl"}),
    _p("macos-x64", "macos", "x64", 1, {"macho": "x86_64-macos"}),
    _p("macos-arm64", "macos", "arm64", 1, {"macho": "aarch64-macos"}),
    # ---- mobile / XR
    _p("android-arm64", "android", "arm64", 1, {"android": "aarch64-linux-android"}, family="mobile",
       needs="Android NDK (charpente toolchain install ndk)"),
    _p("android-arm", "android", "arm", 1, {"android": "armv7a-linux-androideabi"}, family="mobile",
       needs="Android NDK (charpente toolchain install ndk)"),
    _p("android-x64", "android", "x64", 1, {"android": "x86_64-linux-android"}, family="mobile",
       needs="Android NDK (charpente toolchain install ndk)"),
    _p("harmonyos-arm64", "ohos", "arm64", 2, {"ohos": "aarch64-linux-ohos"}, family="mobile",
       needs="the OpenHarmony/HarmonyOS native SDK (installed by you; some tools need a Huawei account)"),
    _p("harmonyos-arm", "ohos", "arm", 2, {"ohos": "arm-linux-ohos"}, family="mobile",
       needs="the OpenHarmony/HarmonyOS native SDK"),
    _p("harmonyos-x64", "ohos", "x64", 2, {"ohos": "x86_64-linux-ohos"}, family="mobile",
       needs="the OpenHarmony/HarmonyOS native SDK"),
    _p("ios-arm64", "ios", "arm64", 2, {"apple": "arm64-apple-ios"}, family="mobile",
       needs="Xcode on a Mac (the Apple SDK cannot be redistributed)",
       note="Written without a Mac: command lines and bundle layout are tested, nothing has run against Xcode."),
    _p("ios-sim-arm64", "ios", "arm64", 3, {"apple": "arm64-apple-ios-simulator"}, family="mobile",
       needs="Xcode on a Mac", note="The iOS simulator on Apple silicon."),
    _p("ios-sim-x64", "ios", "x64", 3, {"apple": "x86_64-apple-ios-simulator"}, family="mobile",
       needs="Xcode on a Mac", note="The iOS simulator on an Intel Mac."),
    _p("visionos-arm64", "visionos", "arm64", 3, {"apple": "arm64-apple-xros"}, family="xr",
       needs="Xcode on a Mac"),
    _p("visionos-sim-arm64", "visionos", "arm64", 3, {"apple": "arm64-apple-xros-simulator"}, family="xr",
       needs="Xcode on a Mac"),
    # ---- web / WASI
    _p("wasm32-emscripten", "wasm", "wasm32", 1, {"emscripten": "wasm32-emscripten"}, family="web",
       needs="Emscripten (charpente toolchain install emsdk)"),
    _p("wasm32-wasi", "wasi", "wasm32", 2, {"wasi": "wasm32-wasi"}, family="server",
       note="Tests run under wasmtime; that checks the instruction set and WASI calls, not a real OS."),
    # ---- other Unix
    _p("freebsd-x64", "freebsd", "x64", 2, {"gnu": "x86_64-freebsd"}, family="server"),
    _p("openbsd-x64", "openbsd", "x64", 3, {"gnu": "x86_64-openbsd"}, family="server"),
    _p("netbsd-x64", "netbsd", "x64", 3, {"gnu": "x86_64-netbsd"}, family="server"),
    # ---- embedded
    _p("cortexm0-arm", "baremetal", "cortex-m0", 2, {"zig": "thumb-freestanding-eabi", "eabi": "thumbv6m-none-eabi"},
       family="embedded", needs="arm-none-eabi-gcc, or zig (`charpente toolchain install zig`)",
       cpu="cortex-m0", float_abi="soft"),
    _p("cortexm3-arm", "baremetal", "cortex-m3", 2, {"zig": "thumb-freestanding-eabi", "eabi": "thumbv7m-none-eabi"},
       family="embedded", needs="arm-none-eabi-gcc, or zig (`charpente toolchain install zig`)",
       cpu="cortex-m3", float_abi="soft"),
    _p("cortexm4-arm", "baremetal", "cortex-m4", 2, {"zig": "thumb-freestanding-eabihf", "eabi": "thumbv7em-none-eabihf"},
       family="embedded", needs="arm-none-eabi-gcc, or zig (`charpente toolchain install zig`)",
       cpu="cortex-m4", float_abi="hard", fpu="fpv4-sp-d16"),
    _p("cortexm7-arm", "baremetal", "cortex-m7", 2, {"zig": "thumb-freestanding-eabihf", "eabi": "thumbv7em-none-eabihf"},
       family="embedded", needs="arm-none-eabi-gcc, or zig (`charpente toolchain install zig`)",
       cpu="cortex-m7", float_abi="hard", fpu="fpv5-d16"),
    _p("cortexm33-arm", "baremetal", "cortex-m33", 3, {"zig": "thumb-freestanding-eabihf", "eabi": "thumbv8m.main-none-eabihf"},
       family="embedded", needs="arm-none-eabi-gcc, or zig (`charpente toolchain install zig`)",
       cpu="cortex-m33", float_abi="hard", fpu="fpv5-sp-d16"),
    _p("esp32-xtensa", "baremetal", "xtensa", 3, {"esp": "xtensa-esp32-elf"}, family="embedded",
       needs="ESP-IDF (not integrated yet)"),
    _p("avr-avr", "baremetal", "avr", 2, {"zig": "avr-freestanding", "avr": "avr"}, family="embedded",
       needs="avr-gcc, or zig (`charpente toolchain install zig`)"),
]

_BY_NAME: Dict[str, Platform] = {p.name: p for p in _TABLE}


def all_platforms() -> List[Platform]:
    return list(_TABLE)


def get(name: str) -> Platform:
    """Look a platform up by name (`linux-arm64`) or by one of its triples
    (`aarch64-linux-gnu`). Raises CH8001 with the list of known names."""
    key = name.strip().lower()
    found = _BY_NAME.get(key)
    if found is not None:
        return found
    for platform in _TABLE:
        if key in {t.lower() for _, t in platform.triples}:
            return platform
    raise ChError("CH8001", name=name, known=", ".join(sorted(_BY_NAME)))


def host() -> Platform:
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(_platform.system(), "")
    arch = _ARCH_ALIASES.get(_platform.machine().lower(), _platform.machine().lower())
    candidate = f"{system}-{arch}"
    if candidate in _BY_NAME:
        return _BY_NAME[candidate]
    raise ChError("CH2003", os=f"{_platform.system()} {_platform.machine()}")


def tier_label(tier: int) -> str:
    return {1: "Tier 1", 2: "Tier 2", 3: "Tier 3"}.get(tier, f"Tier {tier}")


def warning_for(platform: Platform) -> Optional[str]:
    """A sentence to print when the user asks to build for a platform with weaker guarantees."""
    if platform.tier >= 3:
        return (f"{platform.name} is Tier 3: it is supported through a module and compiles in principle, "
                f"but nothing in Charpente's CI checks it.")
    return None
