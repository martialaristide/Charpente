"""Shared by `package --format hap|har|hsp` and `deploy` for HarmonyOS: build the native library, delegate to hvigor."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Tuple

from .. import cross, harmony
from ..builder import build_dir, build_workspace, dependency_closure
from ..dsl.model import APP_KINDS, Target, Workspace
from ..errors import ChError
from ..flags import output_filename
from ._common import CommandError
from ._session import Session


def _platforms(parsed: argparse.Namespace) -> List[str]:
    names = [n.strip() for n in (getattr(parsed, "platform", None) or "harmonyos-arm64").split(",") if n.strip()]
    for name in names:
        if name not in harmony.ABI_DIRS:
            raise ChError("CH8006", platform="harmony",
                          detail=f"{name!r} is not a HarmonyOS platform (use {', '.join(harmony.ABI_DIRS)})")
    return names


def build_package(parsed: argparse.Namespace, workspace: Workspace, target: Target
                  ) -> Tuple[List[Path], harmony.HarmonySettings]:
    if target.kind not in APP_KINDS:
        raise ChError("CH8006", platform="harmony",
                      detail=f"target {target.name!r} is a {target.kind.value}; a HarmonyOS package needs Kind.MOBILE_APP")
    settings = harmony.settings_from(target.name, target.platform_settings.get("harmony", {}))
    closure = dependency_closure(workspace, target.name)
    libraries: Dict[str, Path] = {}
    with Session("package", parsed, workspace, toolchain="ohos", config=parsed.config) as session:
        for name in _platforms(parsed):
            target_os, toolchain = cross.select(name, getattr(parsed, "toolchain", None) or "ohos")
            result = build_workspace(workspace, toolchain, target_os, config=parsed.config, only=closure,
                                     jobs=parsed.jobs, bus=session.bus, use_cache=not parsed.no_cache)
            session.flush()
            built = result.target(target.name)
            if result.interrupted:
                raise KeyboardInterrupt
            if built is None or not built.ok:
                session.finish(False)
                raise CommandError("CH4001", detail=built.error if built else "unknown target build failure")
            libraries[name] = build_dir(workspace, parsed.config, target, toolchain) / output_filename(
                target, target_os, toolchain)
        session.finish(True)
    packages = harmony.build_package(workspace.root, settings, libraries, say=lambda text: print(f"  {text}..."))
    return packages, settings
