# @TITLE@

```
charpente toolchain install zig          # or install arm-none-eabi-gcc
charpente build --platform cortexm4-arm --config Release
charpente size  --platform cortexm4-arm
charpente flash --platform cortexm4-arm --dry-run      # remove --dry-run with an ST-Link connected (needs OpenOCD)
```

`@NAME@.elf`, `.bin` and `.hex` are in `build/Release-cortexm4-arm/@NAME@/`. Adjust `stm32f4.ld` (memory sizes) and the register
addresses in `main.c` for your board.
