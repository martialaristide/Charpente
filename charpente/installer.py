"""Platform installer generation: an Inno Setup script for Windows, a
pkgbuild staging tree for macOS, a .deb staging tree for Linux.

Every function here is pure text/filesystem-staging generation -- no
subprocess call in this module, same separation as flags.py. The actual
tool invocation (iscc, pkgbuild, dpkg-deb) lives in commands/package.py,
which checks whether the tool is on PATH and falls back to leaving the
generated script/staging tree with a clear message when it isn't --
consistent with this project's rule of never pretending a step succeeded
when it was only prepared.

Target/workspace names are already validated at construction time
(safe_name.py, enforced in Target.__post_init__/Workspace.__post_init__),
so nothing here re-validates them -- by the time a Target exists at all,
its name is already safe to drop into a script or a path.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import List

from .dsl.model import OS, Target, Workspace

DEFAULT_VENDOR = "com.charpente"


def inno_setup_script(
    workspace: Workspace,
    target: Target,
    build_dir: Path,
    output_dir: Path,
    *,
    version: str = "1.0.0",
    exe_name: str,
) -> str:
    """Text of an Inno Setup (.iss) script that installs every file in
    `build_dir` and adds a Start Menu shortcut launching `exe_name`.

    Inno Setup syntax always requires Windows-style backslash paths,
    regardless of which host OS actually generates this text: `str(Path)`
    uses the *runtime* platform's separator (forward slashes on Linux/
    macOS), which would silently produce an invalid mixed-separator .iss
    file if this ever ran somewhere other than Windows (currently it
    doesn't -- commands/package.py only calls this on OS.WINDOWS -- but
    this function is documented as a pure, standalone generator, and a
    unit test exercising it directly on Linux/macOS CI is exactly what
    caught this). Forcing backslashes here makes the output correct
    independent of that call site.
    """
    build_dir_str = str(build_dir).replace("/", "\\")
    output_dir_str = str(output_dir).replace("/", "\\")
    return (
        f"[Setup]\n"
        f"AppName={target.name}\n"
        f"AppVersion={version}\n"
        f"DefaultDirName={{autopf}}\\{target.name}\n"
        f"DefaultGroupName={target.name}\n"
        f"OutputDir={output_dir_str}\n"
        f"OutputBaseFilename={target.name}-setup\n"
        f"Compression=lzma\n"
        f"SolidCompression=yes\n"
        f"DisableProgramGroupPage=yes\n"
        f"\n"
        f"[Files]\n"
        f'Source: "{build_dir_str}\\*"; DestDir: "{{app}}"; Flags: recursesubdirs\n'
        f"\n"
        f"[Icons]\n"
        f'Name: "{{group}}\\{target.name}"; Filename: "{{app}}\\{exe_name}"\n'
        f'Name: "{{group}}\\Uninstall {target.name}"; Filename: "{{uninstallexe}}"\n'
        f"\n"
        f"[Run]\n"
        f'Filename: "{{app}}\\{exe_name}"; Description: "Launch {target.name}"; '
        f"Flags: nowait postinstall skipifsilent\n"
    )


def iscc_args(script_path: Path) -> List[str]:
    return ["iscc", str(script_path)]


def find_iscc() -> "str | None":
    return shutil.which("iscc") or shutil.which("ISCC")


def debian_control(target: Target, *, version: str = "1.0.0", maintainer: str = "unknown <unknown@example.com>",
                   architecture: str = "amd64") -> str:
    return (
        f"Package: {target.name.lower()}\n"
        f"Version: {version}\n"
        f"Section: devel\n"
        f"Priority: optional\n"
        f"Architecture: {architecture}\n"
        f"Maintainer: {maintainer}\n"
        f"Description: {target.name} (built with Charpente)\n"
    )


def stage_debian_package(
    staging_dir: Path, target: Target, exe_path: Path, *, version: str = "1.0.0",
    maintainer: str = "unknown <unknown@example.com>",
) -> Path:
    """Builds the DEBIAN/control + usr/local/bin/<exe> tree under
    `staging_dir`, ready for `dpkg-deb --build`. Returns `staging_dir`."""
    debian_dir = staging_dir / "DEBIAN"
    debian_dir.mkdir(parents=True, exist_ok=True)
    (debian_dir / "control").write_text(
        debian_control(target, version=version, maintainer=maintainer), encoding="utf-8"
    )

    bin_dir = staging_dir / "usr" / "local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    dest = bin_dir / exe_path.name
    shutil.copy2(exe_path, dest)
    dest.chmod(0o755)
    return staging_dir


def dpkg_deb_args(staging_dir: Path, output_path: Path) -> List[str]:
    return ["dpkg-deb", "--build", "--root-owner-group", str(staging_dir), str(output_path)]


def find_dpkg_deb() -> "str | None":
    return shutil.which("dpkg-deb")


def pkgbuild_args(
    staging_dir: Path, output_path: Path, target: Target, *,
    version: str = "1.0.0", identifier_prefix: str = DEFAULT_VENDOR,
    install_location: str = "/usr/local",
) -> List[str]:
    return [
        "pkgbuild",
        "--root", str(staging_dir),
        "--identifier", f"{identifier_prefix}.{target.name.lower()}",
        "--version", version,
        "--install-location", install_location,
        str(output_path),
    ]


def stage_macos_package(staging_dir: Path, target: Target, exe_path: Path) -> Path:
    """Builds a `<target.name>/<exe>` tree under `staging_dir` (installed
    under --install-location by pkgbuild), ready for pkgbuild. Returns
    `staging_dir`."""
    bin_dir = staging_dir / target.name
    bin_dir.mkdir(parents=True, exist_ok=True)
    dest = bin_dir / exe_path.name
    shutil.copy2(exe_path, dest)
    dest.chmod(0o755)
    return staging_dir


def find_pkgbuild() -> "str | None":
    return shutil.which("pkgbuild")
