"""Packaging: a zip archive by default (works everywhere, no external tool
needed), or a real platform installer with --format installer -- an Inno
Setup .exe on Windows, a .deb on Linux, a .pkg on macOS.

The installer path always writes its staging files/script first and only
then looks for the platform tool (iscc/dpkg-deb/pkgbuild) on PATH. If the
tool isn't installed, it says so plainly and leaves the staged input in
place with the exact command to finish the job by hand, rather than
silently falling back to a zip or pretending the installer was built.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import zipfile
from typing import List

from .. import installer
from ..builder import build_target, build_dir
from ..dsl.model import OS
from ._common import CommandError, load, resolve_target, toolchain_for_host


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente package", description="Package build output.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--target", help="Target to package (default: the only one, if unambiguous)")
    parser.add_argument("--config", default="Release", choices=["Debug", "Release"])
    parser.add_argument("--output", help="Output path (default: dist/<target>-<config>.<ext>)")
    parser.add_argument("--format", default="zip", choices=["zip", "installer"],
                        help="'zip' (default, no external tool needed) or 'installer' "
                             "(a real platform installer: .exe/.deb/.pkg)")
    parser.add_argument("--version", default="1.0.0", help="Version string embedded in the installer")
    parser.add_argument("--maintainer", default="unknown <unknown@example.com>",
                        help="Maintainer field for a .deb package")
    parsed = parser.parse_args(args)

    workspace = load(parsed.file)
    target = resolve_target(workspace, parsed.target)
    target_os, toolchain = toolchain_for_host()

    result = build_target(workspace, target, toolchain, target_os, config=parsed.config)
    if not result.ok:
        raise CommandError(f"Build failed, nothing to package: {result.error}")

    out_dir = workspace.location / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)

    if parsed.format == "zip":
        return _package_zip(workspace, target, parsed, out_dir)
    return _package_installer(workspace, target, target_os, parsed, out_dir, result.output_path)


def _package_zip(workspace, target, parsed, out_dir) -> int:
    archive_path = (
        workspace.location / parsed.output if parsed.output
        else out_dir / f"{target.name}-{parsed.config}.zip"
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    target_build_dir = build_dir(workspace, parsed.config, target)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in target_build_dir.rglob("*"):
            if path.is_file() and path.suffix not in (".o", ".obj"):
                zf.write(path, arcname=path.relative_to(target_build_dir))

    print(f"Packaged {archive_path}")
    return 0


def _package_installer(workspace, target, target_os, parsed, out_dir, exe_path) -> int:
    if target_os == OS.WINDOWS:
        return _package_windows(workspace, target, parsed, out_dir, exe_path)
    if target_os == OS.LINUX:
        return _package_linux(target, parsed, out_dir, exe_path)
    if target_os == OS.MACOS:
        return _package_macos(target, parsed, out_dir, exe_path)
    raise CommandError(f"No installer format defined for {target_os.value}.")


def _package_windows(workspace, target, parsed, out_dir, exe_path) -> int:
    script_path = out_dir / f"{target.name}-setup.iss"
    script_path.write_text(
        installer.inno_setup_script(
            workspace, target, exe_path.parent, out_dir,
            version=parsed.version, exe_name=exe_path.name,
        ),
        encoding="utf-8",
    )
    print(f"Wrote Inno Setup script: {script_path}")

    iscc = installer.find_iscc()
    if not iscc:
        print(
            "Inno Setup (iscc) not found on PATH -- installer not built.\n"
            f"Install Inno Setup (https://jrsoftware.org/isinfo.php), then run:\n"
            f"  iscc {script_path}"
        )
        return 0

    completed = subprocess.run(installer.iscc_args(script_path), shell=False)
    if completed.returncode != 0:
        raise CommandError(f"iscc failed (exit code {completed.returncode}).")
    print(f"Built installer: {out_dir / (target.name + '-setup.exe')}")
    return 0


def _package_linux(target, parsed, out_dir, exe_path) -> int:
    staging = out_dir / f"{target.name}-deb-staging"
    if staging.exists():
        shutil.rmtree(staging)
    installer.stage_debian_package(staging, target, exe_path, version=parsed.version,
                                   maintainer=parsed.maintainer)
    print(f"Staged .deb contents: {staging}")

    dpkg_deb = installer.find_dpkg_deb()
    output_path = out_dir / f"{target.name.lower()}.deb"
    if not dpkg_deb:
        args = installer.dpkg_deb_args(staging, output_path)
        print(
            "dpkg-deb not found on PATH -- package not built.\n"
            f"Run this on a Debian/Ubuntu machine:\n  {' '.join(args)}"
        )
        return 0

    completed = subprocess.run(installer.dpkg_deb_args(staging, output_path), shell=False)
    if completed.returncode != 0:
        raise CommandError(f"dpkg-deb failed (exit code {completed.returncode}).")
    print(f"Built package: {output_path}")
    return 0


def _package_macos(target, parsed, out_dir, exe_path) -> int:
    staging = out_dir / f"{target.name}-pkg-staging"
    if staging.exists():
        shutil.rmtree(staging)
    installer.stage_macos_package(staging, target, exe_path)
    print(f"Staged .pkg contents: {staging}")

    pkgbuild = installer.find_pkgbuild()
    output_path = out_dir / f"{target.name}.pkg"
    if not pkgbuild:
        args = installer.pkgbuild_args(staging, output_path, target, version=parsed.version)
        print(
            "pkgbuild not found (this isn't macOS, or Xcode Command Line "
            "Tools aren't installed) -- package not built.\n"
            f"Run this on macOS:\n  {' '.join(args)}"
        )
        return 0

    completed = subprocess.run(
        installer.pkgbuild_args(staging, output_path, target, version=parsed.version), shell=False
    )
    if completed.returncode != 0:
        raise CommandError(f"pkgbuild failed (exit code {completed.returncode}).")
    print(f"Built package: {output_path}")
    return 0
