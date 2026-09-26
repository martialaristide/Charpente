"""Shared by `package --format app|ipa` and `deploy` for iOS/visionOS: build, bundle, sign. Written without a Mac."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Tuple

from .. import apple
from ..builder import build_dir, build_workspace, dependency_closure
from ..core import process
from ..core.planner import effective_scope
from ..dsl.model import APP_KINDS, Target, Workspace
from ..errors import ChError
from ..flags import output_filename
from ._common import CommandError, toolchain_for
from ._session import Session


def build_app(parsed: argparse.Namespace, workspace: Workspace, target: Target, *, ipa: bool = False
              ) -> Tuple[Path, apple.AppSettings]:
    """Build a Kind.MOBILE_APP for `parsed.platform`, assemble its `.app`, sign it and optionally zip an `.ipa`."""
    if target.kind not in APP_KINDS:
        raise ChError("CH8006", platform="ios",
                      detail=f"target {target.name!r} is a {target.kind.value}; an app bundle needs Kind.MOBILE_APP")
    if not parsed.platform or parsed.platform not in apple.TARGETS:
        raise ChError("CH8006", platform="ios", detail=f"give an Apple platform with --platform ({', '.join(apple.TARGETS)})")
    target_os, toolchain = toolchain_for(parsed, workspace)
    closure = dependency_closure(workspace, target.name)
    with Session("package", parsed, workspace, toolchain=toolchain.name, config=parsed.config) as session:
        result = build_workspace(workspace, toolchain, target_os, config=parsed.config, only=closure, jobs=parsed.jobs,
                                 bus=session.bus, use_cache=not parsed.no_cache)
        session.flush()
        built = result.target(target.name)
        ok = built is not None and built.ok
        session.finish(ok, 0 if ok else 1)
    if result.interrupted:
        raise KeyboardInterrupt
    if not ok:
        raise CommandError("CH4001", detail=built.error if built else "unknown target build failure")
    _, effective = effective_scope(workspace, toolchain, parsed.config, closure, platform_name=parsed.platform)
    app = apple.settings_from(target.name, effective[target.name].platform_settings.get("ios", {}), parsed.platform)
    executable = build_dir(workspace, parsed.config, target, toolchain) / output_filename(target, target_os, toolchain)
    out_dir = workspace.root / "dist" / parsed.platform
    bundle = apple.build_bundle(app, parsed.platform, executable, out_dir, workspace.root)
    signing = process.run(apple.codesign_argv(bundle, app, workspace.root), timeout=300)
    if signing.returncode != 0:
        raise ChError("CH8008", step="codesign", detail=signing.output.strip()[-800:])
    if ipa:
        return apple.make_ipa(bundle, out_dir / f"{app.name}.ipa"), app
    return bundle, app
