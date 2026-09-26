"""Where recipes come from.

In order of preference:

1. a `vendor/` folder next to the workspace (fully offline builds);
2. recipe folders you added (`CHARPENTE_RECIPES` = paths separated by the OS path
   separator, and `~/.charpente/pkg/recipes-local/`);
3. the recipes bundled with Charpente (`charpente/pkg/recipes/*.toml`);
4. registries (JSON index files or URLs, `charpente pkg registry add`) --
   including a mirror on your local network.

A registry index looks like:

    {"packages": {"fmt": {"versions": {"10.2.1": {
        "recipe": "recipes/fmt-10.2.1.toml", "sha256": "<recipe digest>",
        "binaries": {"<build key>": {"url": "...", "sha256": "..."}}}}}}}

Relative URLs resolve against the index's own address.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core import download
from ..dsl.trust import config_dir
from ..errors import ChError
from ..semver import Constraint, Version
from . import recipe as recipe_mod
from .recipe import Recipe
from .store import PackageStore

BUNDLED_DIR = Path(__file__).resolve().parent / "recipes"


@dataclass(frozen=True)
class RecipeRef:
    """A recipe that can be loaded: a local file, or a URL to fetch."""

    name: str
    version: str
    origin: str                       # human-readable: "bundled", "vendor", a registry address...
    path: Optional[Path] = None
    url: Optional[str] = None
    sha256: str = ""
    binaries: Optional[Dict[str, Dict[str, str]]] = None


def local_recipe_dirs(workspace_root: Optional[Path] = None) -> List["tuple[str, Path]"]:
    dirs: List["tuple[str, Path]"] = []
    if workspace_root is not None:
        dirs.append(("vendor", workspace_root / "vendor" / "recipes"))
    for entry in os.environ.get("CHARPENTE_RECIPES", "").split(os.pathsep):
        if entry.strip():
            dirs.append(("local", Path(entry.strip())))
    dirs.append(("local", config_dir() / "pkg" / "recipes-local"))
    dirs.append(("bundled", BUNDLED_DIR))
    return dirs


class RecipeIndex:
    def __init__(self, store: PackageStore, registries: Optional[List[str]] = None,
                 workspace_root: Optional[Path] = None, offline: Optional[bool] = None) -> None:
        self.store = store
        self.registries = registries or []
        self.workspace_root = workspace_root
        self.offline = download.offline() if offline is None else offline
        self._local: Optional[Dict[str, Dict[str, RecipeRef]]] = None
        self._remote: Dict[str, Dict[str, Dict[str, RecipeRef]]] = {}

    # ------------------------------------------------------------------ local
    def _scan_local(self) -> Dict[str, Dict[str, RecipeRef]]:
        found: Dict[str, Dict[str, RecipeRef]] = {}
        for origin, directory in local_recipe_dirs(self.workspace_root):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.toml")):
                try:
                    r = recipe_mod.load(path)
                except ChError:
                    continue                      # a broken recipe file hides itself, not the others
                found.setdefault(r.name, {}).setdefault(r.version, RecipeRef(r.name, r.version, origin, path=path,
                                                                             sha256=r.digest))
        return found

    def _local_index(self) -> Dict[str, Dict[str, RecipeRef]]:
        if self._local is None:
            self._local = self._scan_local()
        return self._local

    # ----------------------------------------------------------------- remote
    def _read_registry(self, registry: str) -> Dict[str, Dict[str, RecipeRef]]:
        if registry in self._remote:
            return self._remote[registry]
        address = registry if "://" in registry else Path(registry).resolve().as_uri()
        if self.offline and address.startswith(("http://", "https://")):
            self._remote[registry] = {}
            return {}
        fd, tmp_name = tempfile.mkstemp(prefix="charpente-index-")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            download.download(address, tmp, max_bytes=20_000_000, retries=1)
            data: Any = json.loads(tmp.read_text(encoding="utf-8"))
        except ChError as exc:
            raise ChError("CH7012", registry=registry, detail=exc.message) from exc
        except (OSError, ValueError) as exc:
            raise ChError("CH7012", registry=registry, detail=f"not a valid registry index: {exc}") from exc
        finally:
            tmp.unlink(missing_ok=True)
        packages = data.get("packages") if isinstance(data, dict) else None
        if not isinstance(packages, dict):
            raise ChError("CH7012", registry=registry, detail="missing the 'packages' table")
        out: Dict[str, Dict[str, RecipeRef]] = {}
        for name, entry in packages.items():
            for version, info in (entry.get("versions") or {}).items():
                url = urllib.parse.urljoin(address, str(info.get("recipe", "")))
                out.setdefault(name, {})[version] = RecipeRef(
                    name, version, registry, url=url, sha256=str(info.get("sha256", "")).lower(),
                    binaries=info.get("binaries") or None)
        self._remote[registry] = out
        return out

    # ---------------------------------------------------------------- queries
    def versions(self, name: str) -> List[str]:
        found = set(self._local_index().get(name, {}))
        for registry in self.registries:
            found |= set(self._read_registry(registry).get(name, {}))
        return sorted(found, key=Version.parse)

    def ref(self, name: str, version: str) -> Optional[RecipeRef]:
        local = self._local_index().get(name, {}).get(version)
        if local is not None:
            return local
        for registry in self.registries:
            remote = self._read_registry(registry).get(name, {}).get(version)
            if remote is not None:
                return remote
        return None

    def names(self) -> List[str]:
        found = set(self._local_index())
        for registry in self.registries:
            found |= set(self._read_registry(registry))
        return sorted(found)

    def best(self, name: str, constraint: Constraint) -> Optional[str]:
        return constraint.best(self.versions(name))

    def load(self, ref: RecipeRef, max_bytes: Optional[int] = None) -> Recipe:
        """Read the recipe, downloading it (verified against the index) if it is remote."""
        if ref.path is not None:
            return recipe_mod.load(ref.path)
        assert ref.url is not None
        self.store.recipes.mkdir(parents=True, exist_ok=True)
        tmp = self.store.recipes / f".fetch-{hashlib.sha256(ref.url.encode()).hexdigest()[:12]}.toml"
        try:
            download.download(ref.url, tmp, sha256=ref.sha256 or None, max_bytes=max_bytes or 1_000_000)
            recipe = recipe_mod.load(tmp)
            # Keep the exact bytes: the lock file pins their digest, and builds must not need the registry again.
            final = self.store.recipe_path(recipe.name, recipe.version, recipe.digest)
            if not final.exists():
                os.replace(tmp, final)
            return recipe_mod.load(final)
        finally:
            tmp.unlink(missing_ok=True)

    def binary(self, ref: RecipeRef, key: str) -> Optional[Dict[str, str]]:
        return (ref.binaries or {}).get(key)
