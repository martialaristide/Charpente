"""Getting a package's source onto disk: download (resumable, verified),
extract safely, apply patches.

Nothing in an archive is trusted. Every member path is checked to stay inside
the destination (no `..`, no absolute paths, no links that point out), file
modes are reduced to plain files and folders, and the whole archive must match
the SHA-256 in the recipe before a single byte is unpacked.
"""
from __future__ import annotations

import os
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Callable, List, Optional

from ..core import download
from ..errors import ChError
from .recipe import Recipe
from .store import PackageStore, file_sha256


def _long(path: str) -> str:
    """On Windows a path over 260 characters fails unless it carries the `\\?\\` prefix
    (real source trees have such paths: test data, deep examples). Elsewhere a no-op."""
    if os.name == "nt" and len(path) >= 200 and not path.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(path)
    return path


def _dest(base: str, name: str) -> Optional[str]:
    """`base/name` if it stays inside `base` (checked lexically: nothing is ever extracted
    as a link, so a symlink cannot redirect a later member), else None."""
    dest = os.path.normpath(os.path.join(base, name))
    return dest if dest == base or dest.startswith(base + os.sep) else None


def _inside(base: Path, target: Path) -> bool:
    return _dest(os.path.normpath(str(base)), os.path.relpath(str(target), str(base))) is not None


def extract(archive: Path, destination: Path, strip_prefix: str = "") -> None:
    """Unpack `archive` into `destination` (created; must not exist)."""
    if destination.exists():
        raise ChError("CH6012", archive=archive.name, detail=f"{destination} already exists")
    tmp = destination.with_name(destination.name + ".x")
    shutil.rmtree(_long(str(tmp)), ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        _extract_into(archive, tmp)
        top = tmp / strip_prefix if strip_prefix else tmp
        if strip_prefix and not top.is_dir():
            raise ChError("CH6012", archive=archive.name,
                          detail=f"strip_prefix {strip_prefix!r} not found in the archive")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(top, destination)
    except OSError as exc:
        raise ChError("CH6012", archive=archive.name, detail=str(exc)) from exc
    finally:
        shutil.rmtree(_long(str(tmp)), ignore_errors=True)


def _extract_into(archive: Path, tmp: Path) -> None:
    base = os.path.normpath(str(tmp))
    name = archive.name.lower()
    try:
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    dest = _dest(base, info.filename)
                    if dest is None:
                        raise ChError("CH6012", archive=archive.name, detail=f"unsafe path {info.filename!r}")
                    if info.is_dir():
                        os.makedirs(_long(dest), exist_ok=True)
                        continue
                    os.makedirs(_long(os.path.dirname(dest)), exist_ok=True)
                    with zf.open(info) as src, open(_long(dest), "wb") as out:
                        shutil.copyfileobj(src, out)
            return
        with tarfile.open(archive) as tf:
            for member in tf:
                dest = _dest(base, member.name)
                if dest is None:
                    raise ChError("CH6012", archive=archive.name, detail=f"unsafe path {member.name!r}")
                if member.issym() or member.islnk():
                    link = os.path.normpath(os.path.join(os.path.dirname(dest), member.linkname))
                    if member.linkname.startswith(("/", "\\")) or not (link == base or link.startswith(base + os.sep)):
                        raise ChError("CH6012", archive=archive.name,
                                      detail=f"link {member.name!r} points outside the package")
                    continue                    # links are not needed to build; never created
                if member.isdir():
                    os.makedirs(_long(dest), exist_ok=True)
                elif member.isreg():
                    os.makedirs(_long(os.path.dirname(dest)), exist_ok=True)
                    source = tf.extractfile(member)
                    if source is None:
                        continue
                    with source, open(_long(dest), "wb") as out:
                        shutil.copyfileobj(source, out)
                # devices, FIFOs and anything else are ignored
    except (tarfile.TarError, zipfile.BadZipFile, EOFError) as exc:
        raise ChError("CH6012", archive=archive.name, detail=f"cannot be read: {exc}") from exc
    except OSError as exc:
        raise ChError("CH6012", archive=archive.name, detail=str(exc)) from exc


# ---------------------------------------------------------------- patches
def apply_unified_diff(text: str, root: Path) -> List[str]:
    """Apply a unified diff (`--- a/x` / `+++ b/x` / `@@` hunks) under `root`.
    Returns the files changed. Raises ChError CH6011 if any hunk does not match."""
    lines = text.splitlines()
    i, changed = 0, []
    while i < len(lines):
        if not lines[i].startswith("--- "):
            i += 1
            continue
        old_name = lines[i][4:].split("\t")[0].strip()
        new_name = lines[i + 1][4:].split("\t")[0].strip() if i + 1 < len(lines) else old_name
        i += 2
        rel = new_name if new_name != "/dev/null" else old_name
        rel = rel[2:] if rel.startswith(("a/", "b/")) else rel
        target = root / rel
        if not _inside(root, target):
            raise ChError("CH6011", file=rel, detail="the patch path leaves the package")
        original = target.read_text(encoding="utf-8").splitlines(keepends=True) if target.exists() else []
        result: List[str] = []
        cursor = 0
        while i < len(lines) and lines[i].startswith("@@"):
            header = lines[i]
            try:
                start = int(header.split(" ")[1].split(",")[0][1:])
            except (IndexError, ValueError) as exc:
                raise ChError("CH6011", file=rel, detail=f"bad hunk header {header!r}") from exc
            i += 1
            hunk_old: List[str] = []
            hunk_new: List[str] = []
            while i < len(lines) and not lines[i].startswith(("@@", "--- ")) and not lines[i].startswith("diff "):
                line = lines[i]
                tag, body = (line[:1], line[1:]) if line else (" ", "")
                if tag == " ":
                    hunk_old.append(body + "\n")
                    hunk_new.append(body + "\n")
                elif tag == "-":
                    hunk_old.append(body + "\n")
                elif tag == "+":
                    hunk_new.append(body + "\n")
                elif tag == "\\":
                    pass
                else:
                    break
                i += 1
            begin = max(start - 1, 0) if hunk_old else len(original)
            if [ln.rstrip("\r\n") + "\n" for ln in original[begin:begin + len(hunk_old)]] != hunk_old:
                raise ChError("CH6011", file=rel, detail=f"hunk at line {start} does not match the file")
            result += original[cursor:begin] + hunk_new
            cursor = begin + len(hunk_old)
        result += original[cursor:]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(result), encoding="utf-8", newline="")
        changed.append(rel)
    return changed


def fetch_source(recipe: Recipe, store: PackageStore, *, max_bytes: Optional[int] = None,
                 progress: Optional[Callable[[int, Optional[int]], None]] = None) -> Path:
    """The unpacked, patched source tree of `recipe` (downloading if needed).
    Idempotent: an existing tree for this exact recipe is reused."""
    target = store.source_dir(recipe.name, recipe.version, recipe.digest)
    if target.exists():
        return target
    archive = store.archive_path(recipe.source.sha256, recipe.source.url)
    if not archive.exists() or file_sha256(archive) != recipe.source.sha256:
        archive.unlink(missing_ok=True)
        download.download(recipe.source.url, archive, sha256=recipe.source.sha256, max_bytes=max_bytes,
                          progress=progress)
    extract(archive, target, recipe.source.strip_prefix)
    try:
        for patch in recipe.patches:
            patch_path = Path(recipe.directory) / patch.file
            data = patch_path.read_bytes()
            if patch.sha256 and file_sha256(patch_path) != patch.sha256:
                raise ChError("CH6011", file=patch.file, detail="the patch does not match its recorded sha256")
            apply_unified_diff(data.decode("utf-8"), target)
    except (OSError, ChError):
        shutil.rmtree(target, ignore_errors=True)         # never leave a half-patched tree behind
        raise
    return target
