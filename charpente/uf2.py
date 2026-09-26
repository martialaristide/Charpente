"""UF2: the USB-drive firmware format of Raspberry Pi Pico (RP2040/RP2350), many Adafruit, Arduino and micro:bit boards.

A UF2 file is a sequence of 512-byte blocks, each carrying up to 256 bytes of the image and the flash address it
belongs to; dragging it onto the board's mass-storage drive programs it. Run as a program
(`python -m charpente.uf2 in.bin out.uf2 --base 0x10000000 --family 0xe48bff56`) so the build engine can treat the
conversion as an ordinary cached action.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path
from typing import List, Optional, Tuple

MAGIC_START0 = 0x0A324655      # "UF2\n"
MAGIC_START1 = 0x9E5D5157
MAGIC_END = 0x0AB16F30
FLAG_FAMILY_ID = 0x00002000
PAYLOAD = 256

FAMILIES = {"rp2040": 0xE48BFF56, "rp2350-arm-s": 0xE48BFF59, "samd21": 0x68ED2B88, "samd51": 0x55114460,
            "nrf52840": 0xADA52840, "stm32f4": 0x57755A57, "esp32": 0x1C5F21B0, "esp32s2": 0xBFDD4EEE,
            "esp32s3": 0xC47E5767, "esp32c3": 0xD42AF0C0}


def bin_to_uf2(data: bytes, base: int, family: int) -> bytes:
    """Wrap `data` (a flat binary image loaded at `base`) into UF2 blocks."""
    if not 0 <= base < 2 ** 32 or not 0 <= family < 2 ** 32:
        raise ValueError("base address and family id must fit in 32 bits")
    blocks: List[bytes] = []
    total = (len(data) + PAYLOAD - 1) // PAYLOAD
    for index in range(total):
        chunk = data[index * PAYLOAD:(index + 1) * PAYLOAD]
        header = struct.pack("<IIIIIIII", MAGIC_START0, MAGIC_START1, FLAG_FAMILY_ID, base + index * PAYLOAD, PAYLOAD,
                             index, total, family)
        blocks.append(header + chunk.ljust(476, b"\x00") + struct.pack("<I", MAGIC_END))
    return b"".join(blocks)


def parse_uf2(blob: bytes) -> List[Tuple[int, bytes, int, int, int]]:
    """(address, payload, block number, total, family) of every block; raises ValueError on a malformed file."""
    if len(blob) % 512:
        raise ValueError("a UF2 file is a multiple of 512 bytes")
    blocks: List[Tuple[int, bytes, int, int, int]] = []
    for offset in range(0, len(blob), 512):
        start0, start1, _flags, address, size, number, total, family = struct.unpack_from("<IIIIIIII", blob, offset)
        (end,) = struct.unpack_from("<I", blob, offset + 508)
        if (start0, start1, end) != (MAGIC_START0, MAGIC_START1, MAGIC_END):
            raise ValueError(f"block {offset // 512} has bad magic numbers")
        blocks.append((address, blob[offset + 32:offset + 32 + size], number, total, family))
    return blocks


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m charpente.uf2", description="Convert a .bin firmware image to UF2.")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--base", required=True, help="Flash address the image is loaded at (e.g. 0x10000000)")
    parser.add_argument("--family", required=True, help="Family id (number) or a known name: " + ", ".join(FAMILIES))
    parsed = parser.parse_args(argv)
    name = parsed.family.lower()
    family = FAMILIES[name] if name in FAMILIES else int(parsed.family, 0)
    Path(parsed.output).write_bytes(bin_to_uf2(Path(parsed.input).read_bytes(), int(parsed.base, 0), family))
    return 0


if __name__ == "__main__":
    sys.exit(main())
