# @TITLE@

An ESP-IDF project. **Charpente does not build or flash it yet** (the ESP-IDF toolchain has its own build system; delegation is planned).
Use Espressif's tools:

```
. $IDF_PATH/export.sh          # or export.ps1 on Windows
idf.py set-target esp32
idf.py build flash monitor
```

`charpente check` (formatting, secrets, file sizes) works on this folder as on any other.
