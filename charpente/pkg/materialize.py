"""Turning installed packages into targets of a workspace, offline.

`ws.requires("fmt@^10")` records a wish; `charpente pkg install` resolves it,
fetches and verifies the sources and writes `charpente.lock`. This module is the
last step, run every time a workspace is loaded: for each locked package it adds
an ordinary target (header-only or a static library, built by the same engine
with your toolchain and cached like everything else). It never touches the
network: a package that is not installed is an error that tells you what to run.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional, Set

from ..dsl.model import Kind, Language, Overlay, Target, Workspace
from ..errors import ChError
from . import lock as lock_mod
from . import recipe as recipe_mod
from .lock import Lock, LockedPackage
from .recipe import Recipe, constraint_of
from .store import PackageStore

VENDOR_MANIFEST = "charpente-vendor.json"
DEFAULT_STANDARDS = {"cpp": "c++17", "c": "c11"}


def vendor_dir(root: Path) -> Path:
    return root / "vendor"


def vendored(root: Path) -> Dict[str, Dict[str, str]]:
    """{name: {"version", "recipe_sha256"}} of the packages under `<root>/vendor`."""
    path = vendor_dir(root) / VENDOR_MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): dict(v) for k, v in data.get("packages", {}).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def locate(pkg: LockedPackage, root: Path, store: PackageStore) -> "tuple[Path, Path]":
    """(recipe file, source tree) of a locked package: vendor first, then the store."""
    v = vendored(root).get(pkg.name)
    if v and v.get("version") == pkg.version and v.get("recipe_sha256") == pkg.recipe_sha256:
        base = vendor_dir(root)
        recipe_file = base / "recipes" / f"{pkg.name}-{pkg.version}.toml"
        tree = base / f"{pkg.name}-{pkg.version}"
        if recipe_file.exists() and tree.is_dir():
            return recipe_file, tree
    recipe_file = store.recipe_path(pkg.name, pkg.version, pkg.recipe_sha256)
    tree = store.source_dir(pkg.name, pkg.version, pkg.recipe_sha256)
    if recipe_file.exists() and tree.is_dir():
        return recipe_file, tree
    raise ChError("CH6005", name=f"{pkg.name} {pkg.version}")


def load_locked_recipe(pkg: LockedPackage, root: Path, store: PackageStore) -> "tuple[Recipe, Path]":
    recipe_file, tree = locate(pkg, root, store)
    recipe = recipe_mod.load(recipe_file)
    if recipe.digest != pkg.recipe_sha256:
        raise ChError("CH6009", name=pkg.name, expected=pkg.recipe_sha256[:12], actual=recipe.digest[:12])
    files = recipe_file.with_name(recipe_file.stem + ".files")
    if files.is_dir():
        recipe = replace(recipe, directory=str(files))
    return recipe, tree


def package_target(recipe: Recipe, tree: Path) -> Target:
    build = recipe.build
    header_only = build.type == "header_only"
    language = Language.C if build.language == "c" else Language.CPP
    t = Target(name=recipe.name, location=tree, external=True,
               kind=Kind.HEADER_ONLY if header_only else Kind.STATIC_LIBRARY, language=language,
               standard=build.standard or DEFAULT_STANDARDS[build.language])
    t.source_patterns = list(build.sources)
    t.exclude_patterns = list(build.exclude)
    t.public_include_dirs = [str(tree / d) for d in build.include_dirs]
    t.include_dirs = [str(tree / d) for d in build.private_include_dirs]
    t.public_define_macros = list(build.defines)
    t.define_macros = list(build.private_defines)
    t.public_compile_flags = list(build.compile_flags)
    t.public_link_libraries = list(build.links)
    t.uses_public = [constraint_of(d)[0] for d in recipe.dependencies]
    for pattern, o in build.platform:
        t.overlays.append(Overlay(
            when={"platform": pattern}, source_patterns=list(o.sources), exclude_patterns=list(o.exclude),
            include_dirs=[], public_include_dirs=[str(tree / d) for d in o.include_dirs],
            define_macros=list(o.private_defines), public_define_macros=list(o.defines),
            public_compile_flags=list(o.compile_flags), public_link_libraries=list(o.links)))
    return t


def reachable(lock: Lock, requires: List[str]) -> List[str]:
    """Locked package names needed by `requires`, dependencies first."""
    order: List[str] = []
    seen: Set[str] = set()

    def visit(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        pkg = lock.get(name)
        if pkg is None:
            raise ChError("CH6006", path=lock_mod.LOCK_NAME, detail=f"{name!r} is required but not locked")
        for dep in pkg.dependencies:
            visit(constraint_of(dep)[0])
        order.append(name)

    for spec in requires:
        visit(constraint_of(spec)[0])
    return order


def materialize(workspace: Workspace, store: Optional[PackageStore] = None) -> List[str]:
    """Add the package targets to `workspace`. Returns their names. No network."""
    if not workspace.requires:
        return []
    store = store or PackageStore()
    root = workspace.root
    lock = lock_mod.load(root)
    if lock is None:
        raise ChError("CH6005", name=", ".join(workspace.requires))
    if not lock_mod.matches_requirements(lock, workspace.requires):
        raise ChError("CH6006", path=lock_mod.LOCK_NAME,
                      detail="it does not satisfy ws.requires(...) any more (a requirement changed?)")
    added: List[str] = []
    for name in reachable(lock, workspace.requires):
        if name in workspace.targets and not workspace.targets[name].external:
            raise ChError("CH6015", name=name)
        if name in workspace.targets:
            continue
        recipe, tree = load_locked_recipe(lock.packages[name], root, store)
        workspace.add_target(package_target(recipe, tree))
        added.append(name)
    return added
