"""The package store: everything Charpente Pkg keeps on disk, under
`~/.charpente/pkg/` (override with `CHARPENTE_PKG_DIR`).

    downloads/<sha256>.<ext>          verified archives (resumable partials as .part)
    src/<name>-<version>-<sha8>/      unpacked, patched source trees
    recipes/<name>-<version>-<sha8>.toml   the exact recipe bytes that were installed
    binaries/<key>.zip                prebuilt packages, indexed by build key
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import List, Optional

from ..dsl.trust import config_dir


class PackageStore:
    def __init__(self, root: Optional[Path] = None) -> None:
        override = os.environ.get("CHARPENTE_PKG_DIR")
        self.root = Path(root) if root is not None else (
            Path(override).expanduser().resolve() if override else config_dir() / "pkg")

    @property
    def downloads(self) -> Path:
        return self.root / "downloads"

    @property
    def recipes(self) -> Path:
        return self.root / "recipes"

    @property
    def binaries(self) -> Path:
        return self.root / "binaries"

    def _registries_file(self) -> Path:
        return self.root / "registries.json"

    def registries(self) -> List[str]:
        try:
            data = json.loads(self._registries_file().read_text(encoding="utf-8"))
            return [str(r) for r in data] if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _write_registries(self, urls: List[str]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._registries_file().write_text(json.dumps(urls, indent=1), encoding="utf-8")

    def add_registry(self, url: str) -> None:
        urls = self.registries()
        if url not in urls:
            self._write_registries([*urls, url])

    def remove_registry(self, url: str) -> bool:
        urls = self.registries()
        if url not in urls:
            return False
        urls.remove(url)
        self._write_registries(urls)
        return True

    def archive_path(self, sha256: str, url: str) -> Path:
        suffix = ".zip" if url.lower().split("?")[0].endswith(".zip") else (
            ".tar.xz" if url.lower().endswith((".tar.xz", ".txz")) else
            ".tar.bz2" if url.lower().endswith((".tar.bz2", ".tbz2")) else ".tar.gz")
        return self.downloads / f"{sha256}{suffix}"

    @staticmethod
    def short(digest: str) -> str:
        return digest[:8]

    def source_dir(self, name: str, version: str, recipe_digest: str) -> Path:
        return self.root / "src" / f"{name}-{version}-{self.short(recipe_digest)}"

    def recipe_path(self, name: str, version: str, recipe_digest: str) -> Path:
        return self.recipes / f"{name}-{version}-{self.short(recipe_digest)}.toml"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
