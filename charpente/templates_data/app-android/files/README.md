# @TITLE@

Needs an Android SDK with the NDK, build-tools and a platform (Android Studio's, or `charpente toolchain install ndk`, see docs/android.md)
and a JDK. `charpente doctor` says what is found.

```
charpente pkg install                                   # the kit's sources (checksummed)
charpente build   --platform android-arm64
charpente package --format apk --platform android-arm64,android-x64
charpente deploy  --platform android-x64                # to the connected device or emulator
```

Change `@PACKAGE@` (the application id) in `@NAME@.charpente` before publishing. `adb logcat -s @IDENT@` shows the app's log.
