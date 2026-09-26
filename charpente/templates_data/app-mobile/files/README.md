# @TITLE@

One engine (`src/engine/`), thin platform entry points (`src/platform/`), one shared API for the device (`charpente::mobile`).

```
charpente pkg install
charpente test                                    # engine tests on your PC
charpente run --target @IDENT@_desktop            # try it on the desktop
charpente deploy --platform android-x64           # Android (emulator or device)
charpente build --platform harmonyos-arm64        # HarmonyOS native library (needs the OpenHarmony SDK: charpente toolchain install ohos)
charpente package --format app --platform ios-sim-arm64   # iOS: on a Mac only
```
