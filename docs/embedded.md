# Microcontrollers (bare-metal firmware)

`Kind.FIRMWARE` compiles freestanding code for a microcontroller, links it with **your** linker script into an
`.elf` and derives the images you flash: `.bin`, `.hex` and, on request, `.uf2`. Charpente also reports the flash/RAM
use and starts the flashing tool.

```python
from charpente import *

with Workspace("blink") as ws:
    with Target("blink") as t:
        t.kind(Kind.FIRMWARE).language(Language.C).standard("c11")
        t.sources(["src/*.c"])
        t.platform_settings("embedded", linker_script="link.ld", entry="Reset_Handler",
                            flash="openocd", flash_args=["-f", "interface/stlink.cfg", "-f", "target/stm32f4x.cfg"])
```

```
charpente build --platform cortexm4-arm        # blink.elf, blink.bin, blink.hex (+ blink.map with GCC)
charpente size  --platform cortexm4-arm        # flash 74 bytes, ram 4 bytes; FLASH: 74 / 262144 bytes (0%)
charpente flash --platform cortexm4-arm --dry-run
```

## Platforms and toolchains

| Platform | CPU | Toolchains |
|---|---|---|
| `cortexm0-arm`, `cortexm3-arm`, `cortexm4-arm`, `cortexm7-arm` (Tier 2), `cortexm33-arm` (Tier 3) | Cortex-M0 ... M33 | `arm-none-eabi-gcc` on PATH, or **zig** (`charpente toolchain install zig`) |
| `avr-avr` (Tier 2) | AVR (`mcu="atmega328p"` required) | `avr-gcc`, or zig |
| `esp32-xtensa` (Tier 3) | | ESP-IDF: **not integrated yet** |

Both toolchains are cross-only: they are never used for a native build. With GCC the flags are `-mcpu=... -mthumb
-mfloat-abi=... -mfpu=...` (from the platform, overridable with `cpu`, `float_abi`, `fpu`), `-ffreestanding
-ffunction-sections -fdata-sections`, C++ without exceptions/RTTI unless `exceptions=True`, and at link
`-nostartfiles --specs=nano.specs -Wl,--gc-sections -T script -Wl,-e,ENTRY`. With zig the target triple carries the
ABI and `-nostdlib` replaces the specs.

## Settings (`platform_settings("embedded", ...)`)

`linker_script`, `entry` (default `Reset_Handler`), `mcu` (AVR), `cpu`, `float_abi`, `fpu`, `specs`
(`nano`/`nosys`/`none`, GCC only), `exceptions`, `flash` (`openocd`, `pyocd`, `probe-rs`, `avrdude`, `esptool`,
`dfu-util`), `flash_args`, `uf2_base` + `uf2_family` (`0x10000000` + `rp2040`: also produce a `.uf2`, the drag-and-drop
format of Raspberry Pi Pico boards). Unknown or invalid values are errors (CH8006).

## Verified for real (Windows host, zig 0.16.0)

- A Cortex-M4 firmware (vector table, linker script, `main`) built by Charpente: ELF machine 40 (ARM), entry
  `0x08000031`, first two words of the `.bin` are the initial stack pointer `0x20010000` and the reset vector; the
  `.hex` is valid Intel HEX; `charpente size` reads the linker script's memory regions. The same source built for
  Cortex-M0 and M7, and a `uf2` image checked by parsing it back (address `0x10000000`, family `0xE48BFF56`).
- An AVR firmware (`atmega328p`): ELF machine 83 (AVR).
- Real bug found: zig's linker has no map-file option, so no `.map` is requested with zig.

## Limits (honest)

- **Nothing was run on hardware or an emulator.** Images are checked structurally; flashing is argument
  construction, tested with a recording runner. Startup code, vector tables and linker scripts are yours (or a
  template's, Phase P6).
- No RTOS integration (Zephyr `west`, FreeRTOS, NuttX) and no ESP-IDF delegation yet; `esp32-xtensa` stays Tier 3.
- No serial monitor and no RISC-V microcontroller platform yet.
- `arm-none-eabi-gcc`/`avr-gcc` support is unit-tested only (neither compiler is installed on the development machine);
  the zig path is the verified one.
