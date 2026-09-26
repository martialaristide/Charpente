"""`charpente pkg vendor`: copy every locked package (recipe + the files needed to
build it) into `vendor/` inside the repository, so the project builds with no
store, no registry and no network at all -- on a plane, in a classroom, behind a
firewall.

    vendor/
        charpente-vendor.json            digests of what is vendored
        recipes/<name>-<version>.toml
        <name>-<version>/                headers, sources and licences (not tests, docs or benchmarks)

Only what building needs is copied: the include directories, the listed
sources, the `keep` globs of the recipe, and the licence files at the top of
the package (redistribution requires them).
"""
from __future__ import annotations

import fnmatch
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..core import globber
from ..dsl.model import Workspace
from ..errors import ChError
from ..modules.signing import tree_digest
from . import lock as lock_mod
from . import materialize
from .fetch import _long
from .recipe import Recipe
from .store import PackageStore

_LICENSE_GLOBS = ("license*", "licence*", "copying*", "copyright*", "notice*", "unlicense*")


def select_files(tree: Path, recipe: Recipe) -> List[str]:
    """Paths (relative, forward slashes) of the files a vendored copy must contain."""
    build = recipe.build
    if build.keep:
        patterns = list(build.keep)
    else:
        dirs = [*build.include_dirs, *build.private_include_dirs]
        for _pattern, override in build.platform:
            dirs += list(override.include_dirs)
        patterns = [("**" if d in (".", "") else f"{d.rstrip('/')}/**") for d in dirs]
        patterns += list(build.sources)
        for _pattern, override in build.platform:
            patterns += list(override.sources)
    root = str(tree)
    chosen: Set[str] = set(globber.expand(root, patterns)) if patterns else set()
    with os.scandir(root) as entries:                  # licence files at the top level
        for entry in entries:
            if entry.is_file() and any(fnmatch.fnmatchcase(entry.name.lower(), g) for g in _LICENSE_GLOBS):
                chosen.add(os.path.normpath(entry.path))
    excluded: Set[str] = set(globber.expand(root, list(build.exclude))) if build.exclude else set()
    return sorted(Path(p).relative_to(tree).as_posix() for p in chosen - excluded)


def _copy_files(tree: Path, files: List[str], destination: Path) -> None:
    shutil.rmtree(_long(str(destination)), ignore_errors=True)
    destination.mkdir(parents=True)
    for rel in files:
        target = destination / rel
        os.makedirs(_long(str(target.parent)), exist_ok=True)
        shutil.copyfile(_long(str(tree / rel)), _long(str(target)))


def vendor(workspace: Workspace, store: PackageStore, destination: Optional[Path] = None) -> List[str]:
    root = workspace.root
    lock = lock_mod.load(root)
    if lock is None or not workspace.requires:
        raise ChError("CH6005", name="(run `charpente pkg install` first)")
    dest = destination or materialize.vendor_dir(root)
    (dest / "recipes").mkdir(parents=True, exist_ok=True)
    packages: Dict[str, Dict[str, Any]] = {}
    done: List[str] = []
    try:
        for name in materialize.reachable(lock, workspace.requires):
            pkg = lock.packages[name]
            recipe, tree = materialize.load_locked_recipe(pkg, root, store)
            recipe_src, _ = materialize.locate(pkg, root, store)
            out_tree = dest / f"{name}-{pkg.version}"
            if out_tree.resolve() != tree.resolve():           # already vendored: nothing to copy
                _copy_files(tree, select_files(tree, recipe), out_tree)
                shutil.copyfile(recipe_src, dest / "recipes" / f"{name}-{pkg.version}.toml")
                files = recipe_src.with_name(recipe_src.stem + ".files")
                if files.is_dir():
                    shutil.copytree(files, dest / "recipes" / f"{name}-{pkg.version}.files", dirs_exist_ok=True)
            packages[name] = _entry(pkg.version, pkg.recipe_sha256, out_tree, recipe)
            done.append(name)
    except OSError as exc:
        raise ChError("CH6014", detail=f"could not copy a package ({type(exc).__name__}: {str(exc)[:200]})") from exc
    manifest_text = json.dumps({"packages": packages}, indent=1, sort_keys=True)
    (dest / materialize.VENDOR_MANIFEST).write_text(manifest_text, encoding="utf-8")
    return done


def _entry(version: str, recipe_sha256: str, tree: Path, recipe: Recipe) -> Dict[str, Any]:
    return {"version": version, "recipe_sha256": recipe_sha256, "tree_sha256": tree_digest(tree),
            "license": recipe.license}


def verify(workspace: Workspace) -> List[str]:
    """Names of vendored packages whose files no longer match the recorded digest."""
    dest = materialize.vendor_dir(workspace.root)
    try:
        data = json.loads((dest / materialize.VENDOR_MANIFEST).read_text(encoding="utf-8"))["packages"]
    except (OSError, ValueError, KeyError):
        raise ChError("CH6014", detail="no vendor/charpente-vendor.json") from None
    bad: List[str] = []
    for name, info in data.items():
        tree = dest / f"{name}-{info['version']}"
        if not tree.is_dir() or tree_digest(tree) != info.get("tree_sha256"):
            bad.append(name)
    return bad
