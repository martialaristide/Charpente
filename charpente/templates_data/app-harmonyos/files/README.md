# @TITLE@

A HarmonyOS app: ArkTS UI in `harmony/` (a hvigor project) and native code in C++ (`src/`), built by Charpente.

```
charpente toolchain install ohos                              # the OpenHarmony native SDK (2.6 GB, checksum-verified)
charpente pkg install
charpente build   --platform harmonyos-arm64                  # libentry.so
charpente package --format hap --platform harmonyos-arm64     # copies it into harmony/entry/libs/arm64-v8a and runs hvigor
charpente deploy  --platform harmonyos-arm64                  # hdc install + start
```

Packaging needs hvigor (DevEco Studio's command line tools) and, for a signed app, your developer certificate: see docs/harmonyos.md.
The `harmony/` project follows DevEco Studio's stage-model layout but was written without DevEco: if it complains, create a fresh project
in DevEco and keep the `libentry.so` / `Index.d.ts` parts.
