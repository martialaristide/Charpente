# XR: headsets

| Target | How | Status |
|---|---|---|
| Meta Quest, Pico, other Android XR headsets | An Android app (`Kind.XR_APP` or `Kind.MOBILE_APP`) with `platform_settings("android", xr="quest"|"pico"|"openxr")` | Manifest generated and accepted by `aapt2`; APK signed and verified. **Never run on a headset.** |
| visionOS | `--platform visionos-arm64` / `visionos-sim-arm64` (see [apple.md](apple.md)) | Written without a Mac, Tier 3 |
| Desktop VR (OpenXR on Windows/Linux) | Ordinary executables linking the OpenXR loader (a package/kit, Phase P6) | Not part of this phase |

The `xr` profile adds to the manifest: `android.hardware.vr.headtracking`, the OpenXR permissions
(`org.khronos.openxr.permission.OPENXR[_SYSTEM]`) and runtime-broker `<queries>`, the
`org.khronos.openxr.intent.category.IMMERSIVE_HMD` launcher category, and, per vendor, Meta's
`com.oculus.supportedDevices` metadata and `com.oculus.intent.category.VR` (quest) or Pico's `pvr.app.type` (pico).
These follow the vendors' public documentation; store review requirements (Meta, Pico) are not checked.

The OpenXR loader itself, hand tracking, passthrough and the store manifests' optional features are for the kit
(`kit-xr`) and are not built here.
