"""Installing, updating and removing modules.

Sources: a folder, a `.zip`, a URL to a `.zip` (`https://…/m.zip#sha256=…`),
or a name looked up in the configured registries (`name` or `name@^1.2`).

Every install shows what the module asks for (its capabilities) and asks for
approval; a module that is not signed by a trusted key needs explicit
confirmation (`--allow-unsigned`). A signature that does not verify is refused
outright. Nothing is ever executed during installation: the module's code is
only imported later, when it is loaded.
"""
from __future__ import annotations

import json
import shutil
import sys
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core import download
from ..errors import ChError
from ..semver import Constraint, Version
from . import manifest as manifest_mod
from . import signing
from .api import MANIFEST_NAME, SIGNATURE_NAME, Manifest
from .store import InstalledModule, ModuleStore

Approver = Callable[[Manifest, signing.SignatureStatus], bool]


def _python_ok(manifest: Manifest) -> bool:
    if not manifest.python:
        return True
    current = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return Constraint.parse(manifest.python).matches(current)


def _safe_extract(archive: Path, destination: Path) -> None:
    """Extract a zip refusing any member that would land outside `destination`."""
    root = destination.resolve()
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            target = (destination / info.filename).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ChError("CH7007", name=archive.name,
                              detail=f"unsafe path in archive: {info.filename!r}") from exc
        zf.extractall(destination)


def _module_root(directory: Path) -> Path:
    """The folder that holds charpente-module.toml (top level, or one level down)."""
    if (directory / MANIFEST_NAME).exists():
        return directory
    children = [p for p in directory.iterdir() if p.is_dir()]
    if len(children) == 1 and (children[0] / MANIFEST_NAME).exists():
        return children[0]
    return directory


# ------------------------------------------------------------------ registries
def read_index(registry: str, max_bytes: int = 5_000_000) -> Dict[str, Any]:
    """Load a registry index (a JSON file or URL):

        {"modules": {"name": {"versions": {"1.0.0": {"url": "...", "sha256": "..."}}}}}
    """
    if "://" not in registry:
        registry = Path(registry).resolve().as_uri()
    tmp = Path(_tmp_file())
    try:
        download.download(registry, tmp, max_bytes=max_bytes, retries=1)
        data = json.loads(tmp.read_text(encoding="utf-8"))
    except ChError as exc:
        raise ChError("CH7012", registry=registry, detail=exc.message) from exc
    except (OSError, ValueError) as exc:
        raise ChError("CH7012", registry=registry, detail=f"not a valid registry index: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)
    if not isinstance(data, dict) or not isinstance(data.get("modules"), dict):
        raise ChError("CH7012", registry=registry, detail="missing the 'modules' table")
    return data


def _tmp_file() -> str:
    import tempfile

    fd, name = tempfile.mkstemp(prefix="charpente-index-")
    import os

    os.close(fd)
    return name


def find_in_registries(name: str, constraint: str, registries: List[str]) -> Tuple[str, str, Dict[str, Any]]:
    """(registry, version, release entry) of the best match, or CH7006."""
    wanted = Constraint.parse(constraint or "*")
    best: Optional[Tuple[Version, str, str, Dict[str, Any]]] = None
    last_error: Optional[ChError] = None
    for registry in registries:
        try:
            index = read_index(registry)
        except ChError as exc:
            last_error = exc
            continue
        versions = index["modules"].get(name, {}).get("versions", {})
        picked = wanted.best(list(versions))
        if picked is not None:
            candidate = Version.parse(picked)
            if best is None or candidate > best[0]:
                best = (candidate, picked, registry, versions[picked])
    if best is None:
        if last_error is not None and not registries[1:]:
            raise last_error
        raise ChError("CH7006", name=name, where=f"searched {len(registries)} registr{'y' if len(registries) == 1 else 'ies'}")
    return best[2], best[1], best[3]


# --------------------------------------------------------------------- install
def install(
    source: str,
    store: ModuleStore,
    *,
    approve: Optional[Approver] = None,
    allow_unsigned: bool = False,
    assume_yes: bool = False,
    registries: Optional[List[str]] = None,
    max_download: Optional[int] = None,
    keys: Optional[Dict[str, str]] = None,
) -> InstalledModule:
    """Install (or reinstall a different version of) a module from `source`."""
    staging = store.staging_dir() / f"in-{abs(hash(source)) % 10**8}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        folder, origin = _fetch(source, store, staging, registries, max_download)
        return _install_folder(folder, origin, store, approve=approve, allow_unsigned=allow_unsigned,
                               assume_yes=assume_yes, keys=keys)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _fetch(source: str, store: ModuleStore, staging: Path, registries: Optional[List[str]],
           max_download: Optional[int]) -> Tuple[Path, str]:
    path = Path(source)
    if path.is_dir():
        return _module_root(path), str(path.resolve())
    if path.is_file() and path.suffix == ".zip":
        _safe_extract(path, staging)
        return _module_root(staging), str(path.resolve())
    if "://" in source:
        url, _, fragment = source.partition("#")
        expected = fragment[len("sha256="):] if fragment.startswith("sha256=") else None
        archive = staging / "module.zip"
        download.download(url, archive, sha256=expected, max_bytes=max_download)
        _safe_extract(archive, staging / "x")
        return _module_root(staging / "x"), url
    # a bare name, optionally with a constraint: name@^1.2
    name, _, constraint = source.partition("@")
    regs = registries if registries is not None else store.registries()
    if not regs:
        raise ChError("CH7006", name=name, where="no registry is configured: `charpente module registry add URL`")
    registry, version, release = find_in_registries(name, constraint, regs)
    url = str(release.get("url", ""))
    if "://" not in url:
        base = registry if "://" in registry else Path(registry).resolve().as_uri()
        url = urllib.parse.urljoin(base, url)
    archive = staging / "module.zip"
    download.download(url, archive, sha256=release.get("sha256"), max_bytes=max_download)
    _safe_extract(archive, staging / "x")
    return _module_root(staging / "x"), f"{registry}#{name}@{version}"


def _install_folder(folder: Path, origin: str, store: ModuleStore, *, approve: Optional[Approver],
                    allow_unsigned: bool, assume_yes: bool, keys: Optional[Dict[str, str]]) -> InstalledModule:
    manifest, _warnings = manifest_mod.load(folder)
    manifest_mod.check_api(manifest)
    if not _python_ok(manifest):
        raise ChError("CH7003", path=str(folder / MANIFEST_NAME),
                      detail=f"needs Python {manifest.python}, running {sys.version.split()[0]}")

    existing = store.get(manifest.name)
    if existing is not None and existing.version == manifest.version and not existing.bundled:
        raise ChError("CH7011", name=manifest.name, version=manifest.version)

    status = signing.check_signature(folder, keys)
    if status.state == "invalid":
        raise ChError("CH7007", name=manifest.name, detail=status.detail)
    if not status.signed and not allow_unsigned:
        if approve is None or not approve(manifest, status):
            raise ChError("CH7010", name=manifest.name, detail=status.detail)
    elif approve is not None and not assume_yes and not approve(manifest, status):
        raise ChError("CH7010", name=manifest.name, detail="installation declined")

    destination = store.package_dir(manifest.name, manifest.version)
    shutil.rmtree(destination, ignore_errors=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(folder, destination, ignore=shutil.ignore_patterns("__pycache__", ".git"))

    record = InstalledModule(
        name=manifest.name, version=manifest.version, path=str(destination), enabled=True,
        approved=manifest.capabilities.to_dict(), source=origin, digest=signing.tree_digest(destination),
        signature=f"signed:{status.key}" if status.signed else "unsigned",
    )
    store.put(record)
    if existing is not None and existing.version != manifest.version and not existing.bundled:
        shutil.rmtree(store.package_dir(existing.name, existing.version), ignore_errors=True)
    return record


def update(name: str, store: ModuleStore, **kwargs: Any) -> Optional[InstalledModule]:
    """Install the newest registry version of `name` if it is newer than the installed one."""
    current = store.get(name)
    if current is None:
        raise ChError("CH7006", name=name, where="not installed")
    regs = kwargs.pop("registries", None) or store.registries()
    if not regs:
        raise ChError("CH7006", name=name, where="no registry is configured")
    _, version, _ = find_in_registries(name, "*", regs)
    if Version.parse(version) <= Version.parse(current.version):
        return None
    return install(name, store, registries=regs, **kwargs)


def remove(name: str, store: ModuleStore) -> bool:
    return store.remove(name)


__all__ = ["Approver", "MANIFEST_NAME", "SIGNATURE_NAME", "find_in_registries", "install", "read_index",
           "remove", "update"]
