"""Kit sources that ship *inside* Charpente (`charpente://NAME`).

Most recipes name an archive to download. A few kits -- code written for Charpente itself, such as a freestanding
C library for microcontrollers or the mobile abstraction layer -- ship with Charpente and need no download. They use
the same recipe format, with `url = "charpente://NAME"` and `sha256` set to the digest of that folder's content, so the
lock file pins them exactly like a downloaded archive and a modified copy is refused.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Iterator, Tuple

from ..errors import ChError

SCHEME = "charpente://"


def is_local(url: str) -> bool:
    return url.startswith(SCHEME)


def root() -> Path:
    return Path(__file__).resolve().parent.parent / "kit_sources"


def resolve(url: str) -> Path:
    """The folder a `charpente://NAME` URL names; refuses anything that would leave the kit folder."""
    name = url[len(SCHEME):].strip("/")
    parts = Path(name).parts
    if not name or ".." in parts or Path(name).is_absolute():
        raise ChError("CH6012", archive=url, detail="not a valid Charpente kit path")
    folder = root().joinpath(*parts)
    if not folder.is_dir():
        raise ChError("CH6012", archive=url, detail="this Charpente has no such kit")
    return folder


def _files(folder: Path) -> Iterator[Tuple[str, Path]]:
    for path in sorted(folder.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and not path.name.endswith(".pyc"):
            yield path.relative_to(folder).as_posix(), path


def tree_digest(folder: Path) -> str:
    """SHA-256 over the sorted (path, content) pairs. Line endings are normalised so a checkout with CRLF
    (Windows `core.autocrlf`) has the same digest as the wheel."""
    h = hashlib.sha256()
    for relative, path in _files(folder):
        content = path.read_bytes().replace(b"\r\n", b"\n")
        h.update(relative.encode("utf-8") + b"\0" + hashlib.sha256(content).digest())
    return h.hexdigest()


def materialize(url: str, expected_sha256: str, destination: Path) -> None:
    """Copy the kit into `destination` (which must not exist) after checking its digest."""
    folder = resolve(url)
    actual = tree_digest(folder)
    if actual != expected_sha256.lower():
        raise ChError("CH6002", url=url, expected=expected_sha256.lower(), actual=actual)
    destination.mkdir(parents=True)
    for relative, path in _files(folder):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
