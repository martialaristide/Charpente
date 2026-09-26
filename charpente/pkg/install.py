"""`charpente pkg install`: resolve, fetch, verify, lock.

The only place where a package operation may use the network, and only
because you asked for it. Everything it fetches is verified against a SHA-256
from the recipe; everything it decides is written to `charpente.lock`, so the
next build (on any machine) needs neither the registry nor the network.
"""
from __future__ import annotations

import shutil
import urllib.parse
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Optional

from ..dsl.model import Workspace
from ..errors import ChError
from . import fetch, materialize, resolver
from . import lock as lock_mod
from .index import RecipeIndex
from .lock import Lock, LockedPackage
from .recipe import Recipe
from .store import PackageStore

Progress = Callable[[str], None]


def _say(progress: Optional[Progress], text: str) -> None:
    if progress is not None:
        progress(text)


def store_recipe(recipe: Recipe, ref_path: Optional[Path], store: PackageStore) -> Recipe:
    """Copy the recipe (and its patch files) into the store, returning the stored form."""
    dest = store.recipe_path(recipe.name, recipe.version, recipe.digest)
    files = dest.with_name(dest.stem + ".files")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        if ref_path is None:
            raise ChError("CH6009", name=recipe.name, expected=recipe.digest[:12], actual="(missing)")
        shutil.copyfile(ref_path, dest)
    if recipe.patches:
        files.mkdir(exist_ok=True)
        for patch in recipe.patches:
            source = Path(recipe.directory) / patch.file
            target = files / patch.file
            if not target.exists() and source.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        return replace(recipe, directory=str(files))
    return replace(recipe, directory=str(dest.parent))


def is_installed(workspace: Workspace, store: PackageStore) -> bool:
    """True if `charpente.lock` satisfies the requirements and every locked package is on disk."""
    try:
        lock = lock_mod.load(workspace.root)
        if lock is None or not lock_mod.matches_requirements(lock, workspace.requires):
            return False
        for name in materialize.reachable(lock, workspace.requires):
            materialize.load_locked_recipe(lock.packages[name], workspace.root, store)
    except ChError:
        return False
    return True


def install(workspace: Workspace, store: PackageStore, index: RecipeIndex, *, update: bool = False,
            max_bytes: Optional[int] = None, progress: Optional[Progress] = None) -> Lock:
    root = workspace.root
    if not workspace.requires:
        raise ChError("CH4005", usage="This workspace declares no ws.requires(...): nothing to install.")
    if not update and is_installed(workspace, store):
        _say(progress, "Everything in charpente.lock is already installed.")
        lock = lock_mod.load(root)
        assert lock is not None
        return lock

    existing = None if update else lock_mod.load(root)
    preferred = existing.versions() if existing is not None else {}
    _say(progress, "Resolving " + ", ".join(workspace.requires))
    resolved = resolver.resolve(workspace.requires, index, preferred=preferred, max_bytes=max_bytes)

    lock = Lock()
    remaining = max_bytes
    for name in resolver.install_order(resolved):
        r = resolved[name]
        recipe = store_recipe(r.recipe, r.ref.path, store)
        if r.ref.url and "://" not in recipe.source.url:
            # A mirror's recipes name their archives relative to themselves.
            recipe = replace(recipe, source=replace(recipe.source, url=urllib.parse.urljoin(r.ref.url, recipe.source.url)))
        _say(progress, f"  {recipe.name} {recipe.version} ({recipe.license}) from {r.ref.origin}")

        def report(received: int, total: Optional[int], _name: str = name) -> None:
            if total and received == total:
                _say(progress, f"    downloaded {_name}: {received // 1024} KiB, verified")

        fetch.fetch_source(recipe, store, max_bytes=remaining, progress=report)
        lock.packages[name] = LockedPackage(
            name=name, version=recipe.version, recipe_sha256=recipe.digest, source_url=recipe.source.url,
            source_sha256=recipe.source.sha256, dependencies=recipe.dependencies,
            requested_by=tuple(r.requested_by))
    lock_mod.save(root, lock)
    _say(progress, f"Wrote {lock_mod.LOCK_NAME} ({len(lock.packages)} package(s)). Commit it.")
    return lock


def names_installed(workspace: Workspace) -> List[str]:
    lock = lock_mod.load(workspace.root)
    return sorted(lock.packages) if lock else []
