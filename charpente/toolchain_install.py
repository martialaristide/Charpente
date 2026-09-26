"""`charpente toolchain install`: fetch a toolchain into Charpente's own directory.

Only on explicit request, never during a build. What is downloaded is checked
against the SHA-256 the vendor publishes next to the download link (over
HTTPS); the archive is unpacked with the same safe extractor as packages, into
`~/.charpente/toolchains/<name>-<version>/`. Nothing is added to PATH or
touched outside that directory, and `charpente toolchain remove` deletes it.

Supported here: zig (a C/C++ cross compiler with every libc bundled). Android's
NDK, Emscripten and wasmtime follow the same shape.
"""
from __future__ import annotations

import json
import platform as _platform
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .core import download, process
from .errors import ChError
from .pkg import fetch
from .toolchains import installed_zigs, toolchains_dir

ZIG_INDEX_URL = "https://ziglang.org/download/index.json"
MAX_ZIG_BYTES = 400 * 1024 * 1024

FetchJson = Callable[[str], Dict[str, Any]]
Progress = Optional[Callable[[int, Optional[int]], None]]


@dataclass(frozen=True)
class Release:
    name: str
    version: str
    url: str
    sha256: str
    size: Optional[int]

    @property
    def folder(self) -> str:
        return f"{self.name}-{self.version}"


def zig_host_key() -> str:
    """The `arch-os` key zig's download index uses for this machine ('x86_64-windows')."""
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(_platform.system(), "")
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64",
            "armv7l": "arm", "riscv64": "riscv64"}.get(_platform.machine().lower(), "")
    if not system or not arch:
        raise ChError("CH8005", name="zig",
                      detail=f"no zig download exists for {_platform.system()} {_platform.machine()}")
    return f"{arch}-{system}"


def _semver_key(text: str) -> Tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text)[:3])


def choose_zig(index: Dict[str, Any], version: Optional[str], host_key: str) -> Release:
    """The release to install: `version`, or the newest release (never the moving `master`)."""
    releases = {k: v for k, v in index.items() if k != "master" and isinstance(v, dict)}
    if version is None:
        if not releases:
            raise ChError("CH8005", name="zig", detail="the download index lists no releases")
        version = max(releases, key=_semver_key)
    entry = releases.get(version)
    if entry is None:
        known = ", ".join(sorted(releases, key=_semver_key, reverse=True)[:8])
        raise ChError("CH8005", name="zig", detail=f"version {version} does not exist (latest: {known})")
    artifact = entry.get(host_key)
    if not isinstance(artifact, dict) or not artifact.get("tarball") or not artifact.get("shasum"):
        raise ChError("CH8005", name="zig", detail=f"zig {version} has no download for {host_key}")
    size = artifact.get("size")
    return Release("zig", version, str(artifact["tarball"]), str(artifact["shasum"]).lower(),
                   int(size) if isinstance(size, (str, int)) and str(size).isdigit() else None)


def fetch_json(url: str) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        path = download.download(url, Path(tmp) / "index.json", max_bytes=8 * 1024 * 1024)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ChError("CH8005", name="zig", detail=f"the download index is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ChError("CH8005", name="zig", detail="the download index has an unexpected shape")
    return data


def install_zig(version: Optional[str] = None, *, index_fetcher: FetchJson = fetch_json,
                host_key: Optional[str] = None, progress: Progress = None,
                opener: Optional[Callable[..., Any]] = None) -> Path:
    """Install zig; returns the directory. Installing what is already there is a no-op."""
    release = choose_zig(index_fetcher(ZIG_INDEX_URL), version, host_key or zig_host_key())
    target = toolchains_dir() / release.folder
    if target.exists():
        return target
    archive = toolchains_dir() / "downloads" / release.url.rsplit("/", 1)[-1]
    download.download(release.url, archive, sha256=release.sha256, max_bytes=MAX_ZIG_BYTES, progress=progress,
                      opener=opener)
    stem = archive.name
    for suffix in (".tar.xz", ".zip", ".tar.gz"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    fetch.extract(archive, target, strip_prefix=stem, keep_exec=True)
    (target / "charpente-install.json").write_text(
        json.dumps({"name": release.name, "version": release.version, "url": release.url,
                    "sha256": release.sha256}, indent=1), encoding="utf-8")
    try:
        archive.unlink()
    except OSError:
        pass
    return target


EMSDK_REPO = "https://github.com/emscripten-core/emsdk.git"


def install_emsdk(version: str = "latest", *, runner: Optional[process.Runner] = None,
                  which: Callable[[str], Optional[str]] = shutil.which,
                  say: Callable[[str], None] = print) -> Path:
    """Install Emscripten through emscripten's own `emsdk` (needs git and Python on PATH).

    Unlike zig this is not a single verified archive: emsdk clones its repository and downloads LLVM,
    Binaryen and Node from Google's release bucket, with the integrity checks emsdk itself does. The
    result lives in `~/.charpente/toolchains/emsdk-<version>/` and is deleted by `toolchain remove`."""
    git, python = which("git"), which("python") or which("python3")
    if not git or not python:
        raise ChError("CH8005", name="emsdk", detail="emsdk needs `git` and `python` on PATH")
    if not re.fullmatch(r"latest|[0-9]+(\.[0-9]+){1,2}", version):
        raise ChError("CH8005", name="emsdk", detail=f"{version!r} is not 'latest' or a version like 4.0.10")
    target = toolchains_dir() / f"emsdk-{version}"
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    steps = [
        ("Cloning emsdk", [git, "clone", "--depth", "1", EMSDK_REPO, str(target)], None),
        (f"Installing Emscripten {version} (large download)", [python, "emsdk.py", "install", version], target),
        (f"Activating {version}", [python, "emsdk.py", "activate", version], target),
    ]
    for label, argv, cwd in steps:
        say(label + " ...")
        result = process.run(argv, cwd=str(cwd) if cwd else None, runner=runner, timeout=3600)
        if result.returncode != 0:
            shutil.rmtree(fetch._long(str(target)), ignore_errors=True)
            raise ChError("CH8005", name="emsdk", detail=f"{label} failed: {result.output.strip()[-400:]}")
    return target


def installed() -> List[Tuple[str, str, Path]]:
    """(name, version, directory) of everything Charpente installed."""
    found: List[Tuple[str, str, Path]] = []
    root = toolchains_dir()
    if root.is_dir():
        for directory in sorted(root.iterdir()):
            if directory.is_dir() and directory.name != "downloads" and "-" in directory.name:
                name, _, version = directory.name.partition("-")
                found.append((name, version, directory))
    return found


def remove(spec: str) -> Path:
    """Delete an installed toolchain given as `name@version` (or a unique `name`)."""
    name, _, version = spec.partition("@")
    matches = [d for n, v, d in installed() if n == name and (not version or v == version)]
    if not matches:
        raise ChError("CH8005", name=spec, detail="it is not installed (see `charpente toolchain list`)")
    if len(matches) > 1:
        raise ChError("CH8005", name=spec,
                      detail="several versions are installed; say which: " + ", ".join(m.name for m in matches))
    root = toolchains_dir().resolve()
    directory = matches[0].resolve()
    if root not in directory.parents:
        raise ChError("CH8005", name=spec, detail="refusing to delete outside the toolchain directory")
    shutil.rmtree(fetch._long(str(directory)))
    return directory


def zig_executable() -> Optional[Path]:
    found = installed_zigs()
    return found[0] if found else None
