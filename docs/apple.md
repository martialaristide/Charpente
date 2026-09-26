# iOS, iPadOS and visionOS

**This part of Charpente was written and unit-tested without a Mac.** Every command it builds is documented Apple
tooling, and the tests use a recording runner and fake trees; nothing has run against a real Xcode, simulator or device.
That is why these platforms are Tier 2/3 and why `charpente platforms` shows a note. If something fails on your Mac,
that is a bug to report, not a guarantee broken -- and please include the command line printed by `-v`.

The Apple SDKs cannot be redistributed: nothing is downloaded. Xcode must be installed (`xcode-select --install`).

```python
with Target("app") as t:
    t.kind(Kind.MOBILE_APP).sources(["src/*.mm", "src/*.cpp"])
    t.platform_settings("ios", bundle_id="com.example.app", name="My App", min_os="15.0",
                        frameworks=["UIKit", "Metal", "QuartzCore"], orientations=["portrait"])
```

```
charpente build   --platform ios-sim-arm64                       # clang -target arm64-apple-ios15.0-simulator -isysroot <SDK>
charpente package --format app --platform ios-sim-arm64          # dist/ios-sim-arm64/My App.app, ad-hoc signed
charpente package --format ipa --platform ios-arm64              # a device build: needs identity=...
charpente deploy  --platform ios-sim-arm64                       # xcrun simctl install booted + launch
charpente deploy  --platform ios-arm64 --device <UDID>           # xcrun devicectl device install app / process launch
```

Platforms: `ios-arm64`, `ios-sim-arm64`, `ios-sim-x64`, `visionos-arm64`, `visionos-sim-arm64`. The deployment target is the
highest `min_os` of the workspace (default 13.0; visionOS 1.0). Objective-C/C++ sources compile with `-fobjc-arc`.

Settings: `bundle_id` (required), `name`, `version`, `build`, `min_os`, `device_family`, `orientations`, `frameworks`,
`identity` (code-signing identity; simulator default is ad hoc `-`), `entitlements`, `provisioning_profile`, `resources`,
`plist` (extra Info.plist keys). Unknown keys are errors.

## Limits

- Not run on a Mac. Storyboards/asset catalogs (`actool`), Swift, `xcodebuild` delegation, notarisation, App Store upload
  and Xcode project generation are not done.
- A device build needs your signing identity and provisioning profile; Charpente never creates or stores them.
- SwiftUI/UIKit entry code is yours; a starter template arrives with the kits (P6).
