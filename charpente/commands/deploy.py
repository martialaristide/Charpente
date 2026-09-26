"""`charpente deploy` -- build, package, install on a device or emulator, and start the app (Android)."""
from __future__ import annotations

import argparse
import shutil
from typing import List

from .. import android, apple, harmony, ohos
from ..core import process
from ..dsl.model import Target, Workspace
from ..errors import ChError
from ._android import add_apk_args, build_apk
from ._apple import build_app
from ._common import load, resolve_target
from ._harmony import build_package
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
    if parsed.platform in apple.TARGETS:
        return _deploy_apple(parsed, workspace, target)
    if parsed.platform in harmony.ABI_DIRS:
        return _deploy_harmony(parsed, workspace, target)
    sdk = android.find_sdk()
    adb = android.adb_path(sdk)
    devices = android.parse_devices(process.run([adb, "devices"], timeout=60).output)
    serial = android.select_device(devices, parsed.device)       # fail before spending time on a build
    apk, app = build_apk(parsed, workspace, target)
    android.install_and_launch(adb, apk, app.package, serial=serial, launch=not parsed.no_launch,
                               say=lambda text: print(f"  {text}..."))
    print(f"Deployed {app.package} to {serial}.")
    return 0



def _deploy_harmony(parsed: argparse.Namespace, workspace: Workspace, target: Target) -> int:
    """Build, delegate the package to hvigor, install with hdc and start the app."""
    hdc = harmony.hdc_path(ohos.find_native())
    targets = harmony.parse_targets(process.run([hdc, "list", "targets"], timeout=60).output)
    if parsed.device and parsed.device not in targets:
        raise ChError("CH8009", detail=f"{parsed.device!r} is not connected (connected: {', '.join(targets) or 'none'})")
    if not parsed.device and len(targets) != 1:
        raise ChError("CH8009", detail="expected exactly one connected device or emulator, found "
                                       f"{len(targets)}; choose with --device")
    packages, settings = build_package(parsed, workspace, target)
    harmony.install_and_launch(hdc, packages[0], settings.bundle_name, serial=parsed.device or targets[0],
                               launch=not parsed.no_launch, say=lambda text: print(f"  {text}..."))
    print(f"Deployed {packages[0].name}.")
    return 0


def _deploy_apple(parsed: argparse.Namespace, workspace: Workspace, target: Target) -> int:
    """Simulator: `simctl install` + `launch` on the booted (or --device) simulator. Device: `devicectl`."""
    simulator = "sim" in parsed.platform
    if not simulator and not parsed.device:
        raise ChError("CH8009", detail="a real device needs --device (its identifier; see `xcrun devicectl list devices`)")
    xcrun = shutil.which("xcrun")
    if not xcrun:
        raise ChError("CH8007", what="xcrun", hint="deploying to iOS needs Xcode on a Mac")
    bundle, app = build_app(parsed, workspace, target)
    device = parsed.device or "booted"
    install = apple.simctl_install_argv(bundle, device, xcrun) if simulator else apple.device_install_argv(bundle, device, xcrun)
    launch = apple.simctl_launch_argv(app.bundle_id, device, xcrun) if simulator else apple.device_launch_argv(
        app.bundle_id, device, xcrun)
    for label, argv in (("Installing", install), ("Starting", launch)):
        if label == "Starting" and parsed.no_launch:
            break
        print(f"  {label} {app.bundle_id}...")
        result = process.run(argv, timeout=600)
        if result.returncode != 0:
            raise ChError("CH8008", step=label, detail=result.output.strip()[-800:])
    print(f"Deployed {app.bundle_id} to {device}.")
    return 0
