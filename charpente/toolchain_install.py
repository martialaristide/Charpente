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
import sys
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
    if not root.is_dir():
        return found
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or directory.name == "downloads":
            continue
        if directory.name == "android-sdk":
            for kind, name in (("ndk", "ndk"), ("build-tools", "build-tools"), ("platforms", "platform")):
                for component in sorted((directory / kind).glob("*")):
                    if component.is_dir():
                        found.append((name, component.name.replace("android-", ""), component))
            if (directory / "platform-tools").is_dir():
                found.append(("platform-tools", "", directory / "platform-tools"))
            continue
        match = re.fullmatch(r"([a-z][a-z0-9]*)-(\d[\w.+-]*|latest)", directory.name)
        if match:
            found.append((match.group(1), match.group(2), directory))
    return found


def remove(spec: str) -> Path:
    """Delete an installed toolchain given as `name@version` (or a unique `name`)."""
    name, _, version = spec.partition("@")
    matches = [d for n, v, d in installed() if n == name and (not version or v == version)]
    if not name:
        matches = []
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


# ------------------------------------------------------------------ Android SDK components
ANDROID_REPO = "https://dl.google.com/android/repository/"
ANDROID_MANIFEST = "repository2-3.xml"
MAX_ANDROID_BYTES = 1500 * 1024 * 1024
LICENSE_ID = "android-sdk-license"

_ANDROID_HOSTS = {"win32": "windows", "linux": "linux", "darwin": "macosx"}


@dataclass(frozen=True)
class AndroidComponent:
    path: str                     # "ndk;28.2.13676358", "build-tools;35.0.0", "platforms;android-35", "platform-tools"
    display: str
    url: str
    sha1: str
    size: int
    license_id: str

    @property
    def install_subdir(self) -> str:
        """Where it lives inside an SDK root -- the same layout Android Studio uses."""
        kind, _, rest = self.path.partition(";")
        return f"{kind}/{rest}" if rest else kind


def fetch_android_manifest(base_url: str = ANDROID_REPO) -> Tuple[Any, Dict[str, str]]:
    """(the repository's XML root, {license id: text}). The document is parsed only if it declares no
    entities, so a hostile mirror cannot expand one into gigabytes."""
    import xml.etree.ElementTree as ET

    with tempfile.TemporaryDirectory() as tmp:
        path = download.download(base_url + ANDROID_MANIFEST, Path(tmp) / "repo.xml", max_bytes=16 * 1024 * 1024)
        data = path.read_bytes()
    if b"<!ENTITY" in data or b"<!DOCTYPE" in data:
        raise ChError("CH8005", name="android", detail="the SDK repository manifest declares XML entities; refusing it")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ChError("CH8005", name="android", detail=f"the SDK repository manifest is not valid XML: {exc}") from exc
    licenses = {str(el.get("id")): (el.text or "").strip() for el in root.iter("license") if el.get("id")}
    return root, licenses


def _stable(package: Any) -> bool:
    ref = package.find("channelRef")
    return (ref is None or ref.get("ref") == "channel-0") and package.find("revision/preview") is None


def resolve_android(root: Any, spec: str, host: Optional[str] = None) -> AndroidComponent:
    """`ndk`, `ndk@28.2.13676358`, `build-tools`, `build-tools@35.0.0`, `platform@35`, `platform-tools`."""
    host = host or _ANDROID_HOSTS.get(sys.platform, "linux")
    name, _, version = spec.partition("@")
    prefix = {"ndk": "ndk", "build-tools": "build-tools", "platform": "platforms",
              "platform-tools": "platform-tools"}.get(name)
    if prefix is None:
        raise ChError("CH8005", name=spec, detail="components: ndk, build-tools, platform, platform-tools")
    wanted = None
    if prefix == "platform-tools":
        wanted = "platform-tools"
    elif version:
        wanted = f"platforms;android-{version}" if prefix == "platforms" else f"{prefix};{version}"
    matches = []
    for package in root.iter("remotePackage"):
        path = str(package.get("path", ""))
        if (wanted and path != wanted) or (not wanted and not path.startswith(prefix + ";")):
            continue
        if not wanted and not _stable(package):
            continue
        if prefix == "platforms" and not wanted and not re.fullmatch(r"platforms;android-\d+", path):
            continue
        matches.append(package)
    if not matches:
        raise ChError("CH8005", name=spec, detail="no such release in the Android SDK repository")
    package = max(matches, key=lambda p: _semver_key(str(p.get("path", "")).partition(";")[2].replace("android-", "")))
    for archive in package.iterfind("archives/archive"):
        archive_host = archive.findtext("host-os")
        if archive_host not in (None, host):
            continue
        complete = archive.find("complete")
        if complete is None:
            continue
        url, digest, size = complete.findtext("url"), complete.findtext("checksum"), complete.findtext("size")
        if url and digest and size:
            ref = package.find("uses-license")
            return AndroidComponent(str(package.get("path")), package.findtext("display-name") or spec, url,
                                    digest.strip().lower(), int(size), ref.get("ref", LICENSE_ID) if ref is not None else LICENSE_ID)
    raise ChError("CH8005", name=spec, detail=f"{package.get('path')} has no download for {host}")


def android_sdk_root() -> Path:
    return toolchains_dir() / "android-sdk"


def install_android(spec: str, *, accept_license: bool = False, base_url: str = ANDROID_REPO,
                    fetch_manifest: Callable[[str], Tuple[Any, Dict[str, str]]] = fetch_android_manifest,
                    host: Optional[str] = None, progress: Progress = None,
                    say: Callable[[str], None] = print) -> Path:
    """Install an Android SDK component into Charpente's own SDK root, after the Android SDK License
    Agreement has been accepted (`accept_license=True`, i.e. `--accept-android-license`).

    The license is Google's, not Charpente's: it is shown, never accepted on the user's behalf."""
    root, licenses = fetch_manifest(base_url)
    component = resolve_android(root, spec, host)
    target = android_sdk_root() / component.install_subdir
    if target.exists():
        return target
    if not accept_license:
        text = licenses.get(component.license_id, "")
        say(text[:1500] + ("\n[...]" if len(text) > 1500 else ""))
        raise ChError("CH8010", component=component.display, license=component.license_id,
                      url="https://developer.android.com/studio/terms")
    say(f"Downloading {component.display} ({component.size // (1024 * 1024)} MB) ...")
    archive = toolchains_dir() / "downloads" / component.url.rsplit("/", 1)[-1]
    download.download(base_url + component.url, archive, sha1=component.sha1,
                      max_bytes=min(component.size + 1024, MAX_ANDROID_BYTES), progress=progress)
    fetch.extract(archive, target, strip_prefix="*", keep_exec=True)
    (target / "charpente-install.json").write_text(
        json.dumps({"component": component.path, "url": base_url + component.url, "sha1": component.sha1},
                   indent=1), encoding="utf-8")
    try:
        archive.unlink()
    except OSError:
        pass
    return target


# ------------------------------------------------------------------ OpenHarmony native SDK
OHOS_BASE = "https://repo.huaweicloud.com/openharmony/os/"
OHOS_DEFAULT = "5.0.0"
MAX_OHOS_BYTES = 6 * 1024 * 1024 * 1024


def ohos_host_tag(platform_name: Optional[str] = None) -> str:
    """The token the SDK's native archives carry in their names (`native-windows-x64-...zip`)."""
    name = platform_name or sys.platform
    return {"win32": "windows-x64", "linux": "linux-x64", "darwin": "mac"}.get(name, "linux-x64")


def ohos_release_url(version: str, base: str = OHOS_BASE, host_tag: Optional[str] = None) -> str:
    """`5.0.0` -> .../5.0.0-Release/ohos-sdk-windows_linux-public.tar.gz (macOS, `host_tag` "mac", has its own archive). `host_tag` defaults to this machine's."""
    if not re.fullmatch(r"[0-9]+(\.[0-9]+){1,3}(-[A-Za-z0-9]+)?", version):
        raise ChError("CH8005", name="ohos", detail=f"{version!r} is not a release like 5.0.0 or 6.0-Release")
    folder = version if "-" in version else f"{version}-Release"
    archive = "ohos-sdk-mac-public.tar.gz" if (host_tag or ohos_host_tag()) == "mac" else "ohos-sdk-windows_linux-public.tar.gz"
    return f"{base}{folder}/{archive}"


def pick_ohos_native(names: List[str], host_tag: str) -> Optional[str]:
    """The member of the SDK archive holding the native (C/C++) component for this host."""
    candidates = [n for n in names if re.search(rf"(^|/)native-{re.escape(host_tag)}[^/]*\.zip$", n)]
    return sorted(candidates)[0] if candidates else None


def install_ohos(version: str = OHOS_DEFAULT, *, base: str = OHOS_BASE, progress: Progress = None,
                 say: Callable[[str], None] = print, host_tag: Optional[str] = None) -> Path:
    """Install the OpenHarmony *native* SDK (clang, sysroot, cmake toolchain file) for cross-compiling to
    `harmonyos-*` platforms. The whole SDK archive (~2.6 GB) is downloaded, checked against the SHA-256
    published next to it, and only the native component is unpacked."""
    import tarfile

    tag = host_tag or ohos_host_tag()
    url = ohos_release_url(version, base, tag)
    target = toolchains_dir() / f"ohos-{version}"
    if target.exists():
        return target
    say("Reading the published checksum ...")
    sha_file = toolchains_dir() / "downloads" / (url.rsplit("/", 1)[-1] + ".sha256")
    download.download(url + ".sha256", sha_file, max_bytes=4096)
    digest = sha_file.read_text(encoding="utf-8").split()[0].strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ChError("CH8005", name="ohos", detail="the published checksum file is not a SHA-256")
    say("Downloading the OpenHarmony SDK archive (large; resumable) ...")
    archive = toolchains_dir() / "downloads" / url.rsplit("/", 1)[-1]
    download.download(url, archive, sha256=digest, max_bytes=MAX_OHOS_BYTES, progress=progress, timeout=120)
    say(f"Unpacking the native component for {tag} ...")
    holder = toolchains_dir() / "downloads" / f"ohos-{version}-native.zip"
    try:
        with tarfile.open(archive, "r:gz") as tf:
            wanted: Optional[str] = None
            for member in tf:
                if member.isfile() and pick_ohos_native([member.name], tag):
                    wanted = member.name
                    source = tf.extractfile(member)
                    if source is None:
                        continue
                    with source, open(holder, "wb") as out:
                        shutil.copyfileobj(source, out)
                    break
        if wanted is None:
            raise ChError("CH8005", name="ohos", detail=f"the archive has no native component for {tag}")
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ChError("CH8005", name="ohos", detail=f"cannot read the SDK archive: {exc}") from exc
    fetch.extract(holder, target, strip_prefix="*", keep_exec=True)
    (target / "charpente-install.json").write_text(
        json.dumps({"name": "ohos", "version": version, "url": url, "sha256": digest}, indent=1), encoding="utf-8")
    for leftover in (holder, archive):
        try:
            leftover.unlink()
        except OSError:
            pass
    return target
