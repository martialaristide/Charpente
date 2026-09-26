"""OpenHarmony / HarmonyOS native code: the SDK's clang as a cross toolchain.

Charpente builds the **native** part of an OpenHarmony/HarmonyOS application -- C/C++ shared libraries (typically
NAPI modules loaded from ArkTS) and executables -- with the `native` component of the SDK (clang, a musl sysroot).
It does **not** build ArkTS, package a `.hap`, sign it or deploy it: that needs the `ets`/`toolchains` components,
`hvigor` and, for HarmonyOS proper, certificates from Huawei's developer program, which are neither redistributable
nor something a build system can obtain for you. See docs/harmonyos.md.

The SDK is found from `OHOS_NDK_HOME` (the `native` folder) or `OHOS_SDK_HOME` (a folder containing `native`), DevEco
Studio's default location, or `charpente toolchain install ohos` (the open-source OpenHarmony SDK, checksum-verified).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from .toolchains import Toolchain, toolchains_dir

#: platform -> (target triple, extra compile flags the SDK's `ohos.toolchain.cmake` adds for that architecture)
TARGETS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "harmonyos-arm64": ("aarch64-linux-ohos", ()),
    "harmonyos-arm": ("arm-linux-ohos", ("-march=armv7a",)),
    "harmonyos-x64": ("x86_64-linux-ohos", ()),
}
#: Compile flags `ohos.toolchain.cmake` (OpenHarmony 5.0) sets for every target and language.
COMMON_FLAGS = ("-fdata-sections", "-ffunction-sections", "-funwind-tables", "-fstack-protector-strong",
                "-no-canonical-prefixes", "-fno-addrsig", "-Wa,--noexecstack", "-Wformat", "-Werror=format-security",
                "-D__MUSL__")
#: Its linker flags for shared libraries and executables (`OHOS_COMMON_LINKER_FLAGS`); `--no-undefined` is its default.
LINK_FLAGS = ("--rtlib=compiler-rt", "-fuse-ld=lld", "-Wl,--build-id=sha1", "-Wl,--warn-shared-textrel",
              "-Wl,--fatal-warnings", "-Qunused-arguments", "-Wl,-z,noexecstack")
#: Words each flag above must still appear in the SDK's own toolchain file; `alignment()` reports what drifted.
_REFERENCE_WORDS = ("-fstack-protector-strong", "-fno-addrsig", "-D__MUSL__", "--rtlib=compiler-rt", "-fuse-ld=lld",
                    "-Wl,--build-id=sha1", "-Wl,--fatal-warnings", "-Wl,-z,noexecstack", "aarch64-linux-ohos",
                    "arm-linux-ohos", "x86_64-linux-ohos")


def _is_native(path: Path) -> bool:
    return (path / "llvm" / "bin").is_dir() and (path / "sysroot").is_dir()


def find_native(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[Path]:
    """The `native` component directory of an OpenHarmony SDK, or None."""
    env = os.environ if env is None else env
    home = home or Path.home()
    candidates: List[Path] = []
    if env.get("OHOS_NDK_HOME"):
        candidates.append(Path(env["OHOS_NDK_HOME"]))
    if env.get("OHOS_SDK_HOME"):
        sdk = Path(env["OHOS_SDK_HOME"])
        candidates += [sdk / "native", *sorted(sdk.glob("*/native"), reverse=True)]
    for base in ([Path(env["LOCALAPPDATA"]) / "Huawei" / "Sdk"] if env.get("LOCALAPPDATA") else []) + [
            home / "Library" / "Huawei" / "Sdk", home / "Huawei" / "Sdk"]:
        candidates += sorted(base.glob("openharmony/*/native"), reverse=True) + sorted(base.glob("*/native"), reverse=True)
    candidates += sorted(toolchains_dir().glob("ohos-*"), reverse=True)
    candidates += [c / "native" for c in sorted(toolchains_dir().glob("ohos-*"), reverse=True)]
    for candidate in candidates:
        if _is_native(candidate):
            return candidate
    return None


def ohos_toolchain(native: Path, platform_name: str = sys.platform) -> Toolchain:
    bin_dir = native / "llvm" / "bin"
    suffix = ".exe" if platform_name == "win32" else ""
    return Toolchain(name="ohos", c_compiler=str(bin_dir / f"clang{suffix}"), cxx_compiler=str(bin_dir / f"clang++{suffix}"),
                     archiver=str(bin_dir / f"llvm-ar{suffix}"), linker=str(bin_dir / f"clang++{suffix}"),
                     targets=tuple(TARGETS), cross_only=True, extras=(("native_root", str(native)),))


def specialise_ohos(toolchain: Toolchain, platform_name: str) -> Toolchain:
    triple, extra = TARGETS[platform_name]
    native = dict(toolchain.extras)["native_root"]
    args = (f"--target={triple}", f"--sysroot={Path(native) / 'sysroot'}", *COMMON_FLAGS, *extra)
    link_args = (f"--target={triple}", f"--sysroot={Path(native) / 'sysroot'}", *extra, *LINK_FLAGS)
    return replace(toolchain, c_args=args, cxx_args=args, ld_args=link_args, target=platform_name)


def toolchain_file(native: Path) -> Path:
    return native / "build" / "cmake" / "ohos.toolchain.cmake"


def sdk_info(native: Path) -> Dict[str, str]:
    """`{"version": "5.0.0.71", "api": "12"}` from the SDK's own `oh-uni-package.json` (empty when absent)."""
    try:
        data = json.loads((native / "oh-uni-package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {"version": str(data.get("version", "")), "api": str(data.get("apiVersion", ""))}


def alignment(native: Path) -> List[str]:
    """What Charpente assumes about the SDK that its own `ohos.toolchain.cmake` no longer says: an empty list when the
    reference file agrees, else the missing words -- a hint that a newer SDK changed its defaults."""
    try:
        text = toolchain_file(native).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ["ohos.toolchain.cmake not found (cannot compare with the SDK's reference settings)"]
    return [word for word in _REFERENCE_WORDS if word not in text]
