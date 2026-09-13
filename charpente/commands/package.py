"""Packaging, honestly scoped for this version: a zip archive of the build
output for one target, not a platform installer (MSI/.pkg/.deb). Real
installer generation is a meaningfully larger, more platform-specific
feature -- better to ship a working, well-tested zip step now than a
half-working installer step that looks more capable than it is.
"""
from __future__ import annotations

import argparse
import zipfile
from typing import List

from ..builder import build_target, build_dir
from ._common import CommandError, load, resolve_target, toolchain_for_host


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente package", description="Archive build output as a zip.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--target", help="Target to package (default: the only one, if unambiguous)")
    parser.add_argument("--config", default="Release", choices=["Debug", "Release"])
    parser.add_argument("--output", help="Output zip path (default: dist/<target>-<config>.zip)")
    parsed = parser.parse_args(args)

    workspace = load(parsed.file)
    target = resolve_target(workspace, parsed.target)
    target_os, toolchain = toolchain_for_host()

    result = build_target(workspace, target, toolchain, target_os, config=parsed.config)
    if not result.ok:
        raise CommandError(f"Build failed, nothing to package: {result.error}")

    out_dir = workspace.location / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    archive_path = (
        workspace.location / parsed.output if parsed.output
        else out_dir / f"{target.name}-{parsed.config}-{target_os.value}.zip"
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    target_build_dir = build_dir(workspace, parsed.config, target)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in target_build_dir.rglob("*"):
            if path.is_file() and path.suffix not in (".o", ".obj"):
                zf.write(path, arcname=path.relative_to(target_build_dir))

    print(f"Packaged {archive_path}")
    return 0
