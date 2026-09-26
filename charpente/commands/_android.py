"""Shared by `package --format apk` and `deploy`: build a MOBILE_APP for Android and wrap it in a signed APK."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .. import android, cross
from ..builder import build_dir, build_workspace, dependency_closure
from ..core.planner import effective_scope
from ..dsl.model import Kind, Target, Workspace
from ..errors import ChError
from ..flags import output_filename
from ._common import CommandError, android_min_sdk
from ._session import Session


def add_apk_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--keystore", help="Release signing key (a .jks/.keystore); its password is read from "
                                           "$CHARPENTE_KEYSTORE_PASSWORD, never from the command line")
    parser.add_argument("--key-alias", default="release", help="Alias of the key inside --keystore")


def _platforms(parsed: argparse.Namespace) -> List[str]:
    names = [n.strip() for n in (getattr(parsed, "platform", None) or "android-arm64").split(",") if n.strip()]
    for name in names:
        if name not in android.ABIS:
            raise ChError("CH8006", platform="android",
                          detail=f"{name!r} is not an Android platform (use {', '.join(android.ABIS)})")
    return names


def build_apk(parsed: argparse.Namespace, workspace: Workspace, target: Target, out_path: Optional[Path] = None,
              ) -> Tuple[Path, android.AppSettings]:
    """Build `target` for each requested Android ABI, then package, align, sign and verify one APK."""
    if target.kind != Kind.MOBILE_APP:
        raise ChError("CH8006", platform="android",
                      detail=f"target {target.name!r} is a {target.kind.value}; an APK needs Kind.MOBILE_APP")
    sdk = android.require_tools(android.find_sdk(api=android_min_sdk(workspace)))
    names = _platforms(parsed)
    closure = dependency_closure(workspace, target.name)
    libs: Dict[str, List[Path]] = {}
    settings: Optional[android.AppSettings] = None
    with Session("package", parsed, workspace, toolchain="ndk", config=parsed.config) as session:
        for name in names:
            target_os, toolchain = cross.select(name, getattr(parsed, "toolchain", None) or "ndk",
                                                android_api=android_min_sdk(workspace))
            result = build_workspace(workspace, toolchain, target_os, config=parsed.config, only=closure,
                                     jobs=parsed.jobs, bus=session.bus, use_cache=not parsed.no_cache)
            session.flush()
            built = result.target(target.name)
            if result.interrupted:
                raise KeyboardInterrupt
            if built is None or not built.ok:
                session.finish(False)
                raise CommandError("CH4001", detail=built.error if built else "unknown target build failure")
            _, effective = effective_scope(workspace, toolchain, parsed.config, closure, platform_name=name)
            raw = effective[target.name].platform_settings.get("android", {})
            settings = android.settings_from(target.name, raw, debuggable=parsed.config == "Debug")
            files = [build_dir(workspace, parsed.config, target, toolchain) / output_filename(target, target_os, toolchain)]
            if settings.stl == "shared":
                stl = android.shared_stl(toolchain)
                if stl is None:
                    raise ChError("CH8007", what="the NDK's libc++_shared.so", hint="use the Android NDK, or stl=\"static\"")
                files.append(stl)
            libs[android.ABIS[name][0]] = files
        session.finish(True)
    assert settings is not None
    if getattr(parsed, "keystore", None):
        signing = android.release_signing(Path(parsed.keystore), parsed.key_alias)
    else:
        signing = android.debug_signing()
        if parsed.config == "Release":
            print("charpente: warning: signed with the Android DEBUG key (pass --keystore for a release key); "
                  "this APK cannot go on the Play Store.", file=sys.stderr)
    out = out_path or workspace.root / "dist" / f"{target.name}-{parsed.config}.apk"
    staging = workspace.root / "build" / ".charpente" / "apk" / target.name
    if staging.exists():
        shutil.rmtree(staging)
    apk = android.build_apk(sdk, settings, libs, signing, out, staging, say=lambda text: print(f"  {text}..."))
    android.verify_apk(sdk, apk)
    return apk, settings
