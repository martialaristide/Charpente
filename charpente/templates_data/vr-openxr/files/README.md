# @TITLE@

```
charpente pkg install
charpente run                                    # desktop: probes the OpenXR runtime
charpente package --format apk --platform android-arm64 --target @IDENT@_quest    # Quest/Pico APK with the OpenXR manifest
```

Next steps: create a session (`xrCreateSession` with your graphics API's binding), reference spaces, swapchains, and the frame loop.
Set `xr="pico"` or `"openxr"` instead of `"quest"` in the workspace file for other headsets.
