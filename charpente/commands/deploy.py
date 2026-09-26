"""`charpente deploy` -- build, package, install on a device or emulator, and start the app (Android)."""
from __future__ import annotations

import argparse
from typing import List

from .. import android
from ..core import process
from ._android import add_apk_args, build_apk
from ._common import load, resolve_target
from ._session import add_engine_args


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente deploy",
                                     description="Build an Android app, install it on a device or emulator and start it.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--target", help="Target to deploy (default: the only one, if unambiguous)")
    parser.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    parser.add_argument("--device", help="Serial of the device or emulator (see `adb devices`)")
    parser.add_argument("--no-launch", action="store_true", help="Install but do not start the app")
    add_apk_args(parser)
    add_engine_args(parser, output=False)
    parsed = parser.parse_args(args)
    if not parsed.platform:
        parsed.platform = "android-arm64"

    workspace = load(parsed.file, parsed.opt)
    target = resolve_target(workspace, parsed.target)
    sdk = android.find_sdk()
    adb = android.adb_path(sdk)
    devices = android.parse_devices(process.run([adb, "devices"], timeout=60).output)
    serial = android.select_device(devices, parsed.device)       # fail before spending time on a build
    apk, app = build_apk(parsed, workspace, target)
    android.install_and_launch(adb, apk, app.package, serial=serial, launch=not parsed.no_launch,
                               say=lambda text: print(f"  {text}..."))
    print(f"Deployed {app.package} to {serial}.")
    return 0

