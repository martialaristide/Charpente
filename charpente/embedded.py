"""Bare-metal firmware: settings, compiler/linker flags, `.bin`/`.hex` conversion, size, flashing.

A firmware target (`Kind.FIRMWARE`) is compiled freestanding for a microcontroller and linked with *your*
linker script into an `.elf`; Charpente also produces the `.bin` and `.hex` images and can report the size
and start a flashing tool. Everything here builds argument lists (no shell). The compiler is either the
vendor GCC (`arm-none-eabi-gcc`, `avr-gcc`) or zig, whose bundled clang/lld cross-compile freestanding
ARM and AVR code with no other installation.

Not verified on hardware in this repository: the ELF/BIN/HEX outputs are checked structurally, flashing is
argument construction only.
"""
from __future__ import annotations

import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import platforms
from .errors import ChError
from .toolchains import Toolchain

FLASH_TOOLS = ("openocd", "pyocd", "probe-rs", "avrdude", "esptool", "dfu-util")


@dataclass(frozen=True)
class FirmwareSettings:
    linker_script: str = ""
    entry: str = "Reset_Handler"
    mcu: str = ""                  # AVR part name (atmega328p...)
    cpu: str = ""                  # overrides the platform's CPU (cortex-m4...)
    float_abi: str = ""            # hard | softfp | soft; overrides the platform's
    fpu: str = ""                  # fpv4-sp-d16, fpv5-d16...
    specs: str = "nano"            # newlib-nano | nosys | none (GCC only)
    exceptions: bool = False       # C++ exceptions and RTTI are off unless asked for
    flash: str = ""
    flash_args: Tuple[str, ...] = ()
    #: Also produce a `.uf2` image: the flash address of the image and the board family (name or number).
    uf2_base: str = ""
    uf2_family: str = ""


_KNOWN = {"linker_script", "entry", "mcu", "cpu", "float_abi", "fpu", "specs", "exceptions", "flash", "flash_args", "uf2_base", "uf2_family"}
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def settings_from(target_name: str, raw: Mapping[str, Any]) -> FirmwareSettings:
    """Validate a firmware target's `platform_settings("embedded", ...)`."""
    unknown = sorted(set(raw) - _KNOWN)
    if unknown:
        raise ChError("CH8006", platform="embedded",
                      detail=f"unknown setting(s) {', '.join(unknown)} (known: {', '.join(sorted(_KNOWN))})")
    entry = str(raw.get("entry", "Reset_Handler"))
    if not _IDENT.match(entry):
        raise ChError("CH8006", platform="embedded", detail=f"entry {entry!r} is not a C symbol name")
    float_abi = str(raw.get("float_abi", ""))
    if float_abi not in ("", "hard", "softfp", "soft"):
        raise ChError("CH8006", platform="embedded", detail="float_abi must be hard, softfp or soft")
    specs = str(raw.get("specs", "nano"))
    if specs not in ("nano", "nosys", "none"):
        raise ChError("CH8006", platform="embedded", detail="specs must be nano, nosys or none")
    flash = str(raw.get("flash", ""))
    if flash and flash not in FLASH_TOOLS:
        raise ChError("CH8006", platform="embedded", detail=f"flash must be one of {', '.join(FLASH_TOOLS)}")
    for key in ("mcu", "cpu", "fpu"):
        if raw.get(key) and not re.fullmatch(r"[A-Za-z0-9_.+-]+", str(raw[key])):
            raise ChError("CH8006", platform="embedded", detail=f"{key} {raw[key]!r} is not a valid name")
    uf2_base, uf2_family = str(raw.get("uf2_base", "")), str(raw.get("uf2_family", ""))
    if bool(uf2_base) != bool(uf2_family):
        raise ChError("CH8006", platform="embedded", detail="uf2 needs both uf2_base (0x10000000) and uf2_family (rp2040...)")
    if uf2_base:
        from . import uf2

        try:
            int(uf2_base, 0)
            if uf2_family.lower() not in uf2.FAMILIES:
                int(uf2_family, 0)
        except ValueError as exc:
            raise ChError("CH8006", platform="embedded",
                          detail=f"uf2_base/uf2_family are not valid ({exc}); families: {', '.join(uf2.FAMILIES)}") from exc
    args = raw.get("flash_args", ())
    if isinstance(args, str):
        args = (args,)
    return FirmwareSettings(linker_script=str(raw.get("linker_script", "")), entry=entry, mcu=str(raw.get("mcu", "")),
                            cpu=str(raw.get("cpu", "")), float_abi=float_abi, fpu=str(raw.get("fpu", "")),
                            specs=specs, exceptions=bool(raw.get("exceptions", False)), flash=flash,
                            flash_args=tuple(str(a) for a in args), uf2_base=uf2_base, uf2_family=uf2_family)


def is_baremetal(toolchain: Toolchain) -> bool:
    if not toolchain.target:
        return False
    try:
        return platforms.get(toolchain.target).os == "baremetal"
    except ChError:
        return False


def _platform_of(toolchain: Toolchain) -> platforms.Platform:
    return platforms.get(toolchain.target)


def cpu_flags(toolchain: Toolchain, settings: FirmwareSettings) -> List[str]:
    """Flags choosing the CPU (`-mcpu=cortex-m4 -mthumb -mfloat-abi=hard`, or `-mmcu=` for AVR)."""
    platform = _platform_of(toolchain)
    zig = toolchain.name == "zig"
    if platform.arch == "avr":
        if not settings.mcu:
            raise ChError("CH8006", platform="embedded",
                          detail="an AVR target needs its part: platform_settings(\"embedded\", mcu=\"atmega328p\")")
        return [f"-mmcu={settings.mcu}"]
    cpu = settings.cpu or platform.cpu
    if not cpu:
        return []
    if zig:
        return [f"-mcpu={cpu.replace('-', '_')}"]              # the target triple already says thumb + float ABI
    flags = [f"-mcpu={cpu}", "-mthumb"]
    float_abi = settings.float_abi or platform.float_abi
    if float_abi:
        flags.append(f"-mfloat-abi={float_abi}")
    fpu = settings.fpu or platform.fpu
    if fpu and float_abi != "soft":
        flags.append(f"-mfpu={fpu}")
    return flags


def compile_flags(toolchain: Toolchain, settings: FirmwareSettings, cxx: bool) -> List[str]:
    flags = [*cpu_flags(toolchain, settings), "-ffreestanding", "-ffunction-sections", "-fdata-sections"]
    if cxx and not settings.exceptions:
        flags += ["-fno-exceptions", "-fno-rtti", "-fno-threadsafe-statics"]
    return flags


def link_flags(toolchain: Toolchain, settings: FirmwareSettings, root: Path, map_file: Optional[Path]) -> List[str]:
    flags = [*cpu_flags(toolchain, settings), "-Wl,--gc-sections", f"-Wl,-e,{settings.entry}"]
    if toolchain.name == "zig":
        pass          # zig's freestanding targets have no libc to leave out, and keep compiler-rt (soft-float, division helpers)
    else:
        flags.append("-nostartfiles")
        if settings.specs != "none":
            flags.append(f"--specs={settings.specs}.specs")
    if settings.linker_script:
        flags += ["-T", str(root / settings.linker_script)]
    if map_file is not None and toolchain.name != "zig":      # zig cc has no linker-map option
        flags.append(f"-Wl,-Map={map_file}")
    return flags


# ------------------------------------------------------------------ images
def uf2_argv(bin_image: Path, out: Path, settings: FirmwareSettings) -> List[str]:
    """The UF2 conversion as a command (this Python interpreter running charpente.uf2), so it is a cached action."""
    return [sys.executable, "-m", "charpente.uf2", str(bin_image), str(out), "--base", settings.uf2_base,
            "--family", settings.uf2_family]


def objcopy_argv(toolchain: Toolchain, image: str, elf: Path, out: Path) -> List[str]:
    """`objcopy -O binary|ihex` (GNU), `zig objcopy -O binary|hex`."""
    if image not in ("bin", "hex"):
        raise ValueError(image)
    extras = dict(toolchain.extras)
    exe = extras.get("objcopy")
    if not exe:
        raise ChError("CH8007", what="objcopy", hint="install the vendor toolchain (arm-none-eabi-gcc, avr-gcc) or zig")
    prefix = [extras["objcopy_args"]] if extras.get("objcopy_args") else []
    fmt = {"bin": "binary", "hex": "hex" if toolchain.name == "zig" else "ihex"}[image]
    return [exe, *prefix, "-O", fmt, str(elf), str(out)]


@dataclass(frozen=True)
class Sizes:
    text: int          # code + read-only data (allocated, not writable)
    data: int          # initialised writable data (stored in flash, copied to RAM)
    bss: int           # zero-initialised RAM

    @property
    def flash(self) -> int:
        return self.text + self.data

    @property
    def ram(self) -> int:
        return self.data + self.bss


def elf_sizes(path: Path) -> Sizes:
    """text/data/bss of a 32-bit little-endian ELF, from its section headers (the `size` command's classification)."""
    raw = path.read_bytes()
    if raw[:4] != b"\x7fELF" or raw[4] != 1 or raw[5] != 1:
        raise ChError("CH8008", step="Reading the firmware", detail=f"{path.name} is not a 32-bit little-endian ELF file")
    shoff = struct.unpack_from("<I", raw, 32)[0]
    shentsize, shnum = struct.unpack_from("<HH", raw, 46)
    text = data = bss = 0
    for index in range(shnum):
        _name, kind, flags, _addr, _offset, size = struct.unpack_from("<IIIIII", raw, shoff + index * shentsize)
        if not flags & 0x2:                      # SHF_ALLOC
            continue
        if kind == 8:                            # SHT_NOBITS
            bss += size
        elif flags & 0x1:                        # SHF_WRITE
            data += size
        else:
            text += size
    return Sizes(text, data, bss)


def parse_size(text: str) -> Optional[int]:
    """`256K`, `1M`, `0x4000`, `65536` -> bytes (None when not a size)."""
    match = re.fullmatch(r"\s*(0x[0-9a-fA-F]+|\d+)\s*([kKmM]?)\s*", text)
    if not match:
        return None
    value = int(match.group(1), 0)
    return value * {"": 1, "k": 1024, "m": 1024 * 1024}[match.group(2).lower()]


def memory_regions(script: str) -> Dict[str, int]:
    """`MEMORY { FLASH (rx) : ORIGIN = ..., LENGTH = 256K ... }` -> {region name: bytes}; {} if none found."""
    body = re.search(r"MEMORY\s*\{(.*?)\}", script, re.S)
    regions: Dict[str, int] = {}
    if not body:
        return regions
    for name, length in re.findall(r"(\w+)\s*(?:\([^)]*\))?\s*:\s*ORIGIN\s*=\s*[^,]+,\s*LENGTH\s*=\s*([^\s,}]+)", body.group(1)):
        size = parse_size(length)
        if size is not None:
            regions[name] = size
    return regions


def size_report(sizes: Sizes, regions: Mapping[str, int]) -> str:
    lines = [f"flash {sizes.flash} bytes (text {sizes.text}, data {sizes.data}), ram {sizes.ram} bytes (bss {sizes.bss})"]
    for label, used in (("FLASH", sizes.flash), ("RAM", sizes.ram)):
        total = regions.get(label) or regions.get(label.lower())
        if total:
            lines.append(f"{label}: {used} / {total} bytes ({used * 100 // total}%)")
    return "\n".join(lines)


# ------------------------------------------------------------------ flashing
def flash_argv(tool: str, elf: Path, args: Sequence[str], *, image: Optional[Path] = None) -> List[str]:
    """The command that programs the board. `args` come from the project's `flash_args` (probe/target
    configuration) and are passed through untouched."""
    if tool == "openocd":
        return ["openocd", *args, "-c", f"program {{{elf.as_posix()}}} verify reset exit"]
    if tool == "pyocd":
        return ["pyocd", "flash", *args, str(elf)]
    if tool == "probe-rs":
        return ["probe-rs", "download", *args, str(elf)]
    if tool == "avrdude":
        if image is None:
            raise ChError("CH8006", platform="embedded", detail="avrdude needs the .hex image")
        return ["avrdude", *args, "-U", f"flash:w:{image}:i"]
    if tool == "esptool":
        if image is None:
            raise ChError("CH8006", platform="embedded", detail="esptool needs the .bin image")
        return ["esptool", *args, "write_flash", "0x0", str(image)]
    if tool == "dfu-util":
        if image is None:
            raise ChError("CH8006", platform="embedded", detail="dfu-util needs the .bin image")
        return ["dfu-util", *args, "-D", str(image)]
    raise ChError("CH8006", platform="embedded", detail=f"unknown flash tool {tool!r}")
