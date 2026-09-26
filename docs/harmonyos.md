# HarmonyOS and OpenHarmony

Two systems share one native SDK: **OpenHarmony** (open source) and **HarmonyOS NEXT / 5+** (Huawei's; it no longer runs
Android apps). Charpente builds the **native** part -- C/C++ shared libraries (typically Node-API modules loaded from ArkTS)
and executables -- with the SDK's clang and musl sysroot, and **delegates** the app (ArkTS, resources, `.hap`/`.har`/`.hsp`,
signing) to the ecosystem's own tool, hvigor. It never reimplements ArkCompiler or HAP signing.

```
charpente toolchain install ohos            # the open-source OpenHarmony native SDK, SHA-256 verified (2.6 GB download)
charpente build --platform harmonyos-arm64  # also harmonyos-arm, harmonyos-x64
```

```python
with Target("entry") as t:
    t.kind(Kind.MOBILE_APP)                 # the native library of a HAP: libentry.so
    t.sources(["src/*.cpp"])
    t.platform_settings("harmony", project="harmony", module="entry", package_type="hap",
                        bundle_name="com.example.app", stl="shared")
```

```
charpente package --format hap --platform harmonyos-arm64      # copies libentry.so into harmony/entry/libs/arm64-v8a/, runs hvigor
charpente deploy  --platform harmonyos-arm64 [--device SERIAL] # hdc install -r, aa start
```

## Finding the SDK

`OHOS_NDK_HOME` (the `native` folder), `OHOS_SDK_HOME` (a folder containing `native`), DevEco Studio's default folders
(`%LOCALAPPDATA%\Huawei\Sdk`, `~/Library/Huawei/Sdk`), then what `charpente toolchain install ohos` put in
`~/.charpente/toolchains/ohos-<version>/`. `charpente doctor` reports the SDK version and API level.
Charpente never redistributes DevEco or HarmonyOS-only tools; some command-line tools need a Huawei developer account.

## Flags: aligned with the SDK

The compile and link flags are those of the SDK's own `build/cmake/ohos.toolchain.cmake` (OpenHarmony 5.0): `--target=...-linux-ohos
--sysroot=<native>/sysroot`, `-fdata-sections -ffunction-sections -funwind-tables -fstack-protector-strong -fno-addrsig
-Wformat -Werror=format-security -D__MUSL__`, `-march=armv7a` for 32-bit ARM; linking with `--rtlib=compiler-rt -fuse-ld=lld
-Wl,--build-id=sha1 -Wl,--fatal-warnings -Wl,-z,noexecstack -lunwind -lm`, `--no-undefined` for libraries and `--gc-sections` for
executables. The STL is `c++_shared` like the SDK's default (`stl="static"` links `-static-libstdc++`). `charpente doctor` compares
these assumptions with the installed SDK's toolchain file and says what drifted.

## The Node-API skeleton

`charpente.harmony.napi_files(module, functions)` generates the three files of a minimal Node-API module (C++ registration,
`Index.d.ts`, `oh-package.json5`); the templates (`charpente init --template app-harmonyos`) arrive with Phase P6. HarmonyOS's
Node-API derives from Node.js's without being fully compatible: test on the real system.

## Verified for real (Windows host, OpenHarmony SDK 5.0.0.71 / API 12)

- The SDK archive was downloaded by `charpente toolchain install ohos` (resumable, SHA-256 verified, only the native component unpacked).
- A shared library and a C++ executable (using `std::string`, exceptions) built for `harmonyos-arm64`, `harmonyos-arm` and
  `harmonyos-x64`: ELF machine AArch64 / ARM / x86-64, interpreter `/lib/ld-musl-aarch64.so.1` (etc.), needing `libc++_shared.so` and `libc.so`.
- No drift between Charpente's flags and the SDK's toolchain file.

## Limits (honest)

- **hvigor, hdc, DevEco and a device were not available**: `package --format hap` and `deploy` build the exact commands the
  tools' documentation describes and are tested with a recording runner only. Nothing was installed on a HarmonyOS device or emulator.
- The libraries are built and inspected, not executed (no qemu-user, device or emulator here).
- Signing (debug/release certificates, profiles) belongs to hvigor/DevEco and Huawei's programme; `charpente sign init --ohos`
  is not implemented.
- No project generator yet (P6), no `hilog` streaming as events, no third-party recipe triplets (`arm64-ohos`...).
