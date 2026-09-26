"""`charpente pkg ...`, `charpente sbom`: dependencies, offline mirrors, audits."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional

from ..dsl.model import Workspace
from ..errors import ChError
from ..pkg import audit as audit_mod
from ..pkg import install as install_mod
from ..pkg import lock as lock_mod
from ..pkg import materialize, mirror, sbom, vendor
from ..pkg.index import RecipeIndex
from ..pkg.recipe import Recipe
from ..pkg.store import PackageStore
from ..units import parse_size
from ._common import load


def _index(workspace: Optional[Workspace], store: PackageStore, extra: Optional[List[str]] = None) -> RecipeIndex:
    registries = [*store.registries(), *(extra or [])]
    return RecipeIndex(store, registries, workspace.root if workspace is not None else None)


def _workspace(parsed: argparse.Namespace) -> Workspace:
    return load(getattr(parsed, "file", None), getattr(parsed, "opt", None), materialize_packages=False)


def _recipes(workspace: Workspace, store: PackageStore) -> Dict[str, Recipe]:
    """Recipes of every locked package (from the store or vendor/), keyed by name."""
    lock = lock_mod.load(workspace.root)
    out: Dict[str, Recipe] = {}
    if lock is None:
        return out
    for name in lock.packages:
        try:
            out[name] = materialize.load_locked_recipe(lock.packages[name], workspace.root, store)[0]
        except ChError:
            continue
    return out


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente pkg", description="Manage the workspace's external packages.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    sub = parser.add_subparsers(dest="action", required=True)
    ins = sub.add_parser("install", help="Resolve ws.requires(...), fetch and verify sources, write charpente.lock")
    ins.add_argument("--update", action="store_true", help="Look for newer versions instead of keeping the locked ones")
    ins.add_argument("--max-download", default=None, help="Refuse to download more than this in total (e.g. 200MB)")
    ins.add_argument("--registry", action="append", default=[], help="Extra registry (repeatable)")
    sub.add_parser("list", help="The locked packages")
    sub.add_parser("check", help="Exit 1 unless charpente.lock is up to date and installed (for CI)")
    info = sub.add_parser("info", help="Versions and dependencies of a package")
    info.add_argument("name")
    search = sub.add_parser("search", help="List available packages")
    search.add_argument("text", nargs="?", default="")
    vend = sub.add_parser("vendor", help="Copy locked packages into vendor/ for fully offline builds")
    vend.add_argument("--dir", default=None)
    vend.add_argument("--verify", action="store_true", help="Check vendor/ against its recorded digests")
    sub.add_parser("audit", help="Check locked packages against the OSV vulnerability database (uses the network)")
    reg = sub.add_parser("registry", help="Manage recipe registries")
    reg.add_argument("verb", choices=["add", "list", "remove"])
    reg.add_argument("url", nargs="?")
    mir = sub.add_parser("mirror", help="Share packages on a local network")
    mir.add_argument("verb", choices=["populate", "serve"])
    mir.add_argument("directory")
    mir.add_argument("--host", default="127.0.0.1", help="Address to serve on (default: this machine only)")
    mir.add_argument("--port", type=int, default=8765)
    parsed = parser.parse_args(args)
    handler = globals()[f"_cmd_{parsed.action}"]
    return int(handler(parsed))


def _cmd_install(parsed: argparse.Namespace) -> int:
    workspace = _workspace(parsed)
    store = PackageStore()
    limit = parse_size(parsed.max_download) if parsed.max_download else None
    install_mod.install(workspace, store, _index(workspace, store, parsed.registry), update=parsed.update,
                        max_bytes=limit, progress=print)
    return 0


def _cmd_list(parsed: argparse.Namespace) -> int:
    workspace = _workspace(parsed)
    lock = lock_mod.load(workspace.root)
    if lock is None:
        print("No charpente.lock yet." + (" Run `charpente pkg install`." if workspace.requires else
                                          " This workspace declares no ws.requires(...)."))
        return 0
    recipes = _recipes(workspace, PackageStore())
    for name in sorted(lock.packages):
        pkg = lock.packages[name]
        recipe = recipes.get(name)
        state = "installed" if recipe else "NOT INSTALLED"
        print(f"  {name:<20}{pkg.version:<10}{recipe.license if recipe else '?':<22}{state}"
              f"   (needed by {', '.join(pkg.requested_by) or '-'})")
    return 0


def _cmd_check(parsed: argparse.Namespace) -> int:
    workspace = _workspace(parsed)
    if not workspace.requires:
        print("No ws.requires(...): nothing to check.")
        return 0
    if install_mod.is_installed(workspace, PackageStore()):
        print("charpente.lock is up to date and every package is installed.")
        return 0
    print("charpente.lock is missing, stale or not installed: run `charpente pkg install`.")
    return 1


def _cmd_info(parsed: argparse.Namespace) -> int:
    workspace = _workspace(parsed)
    index = _index(workspace, PackageStore())
    versions = index.versions(parsed.name)
    if not versions:
        raise ChError("CH6007", name=parsed.name, where="no recipe in any configured source")
    for version in reversed(versions):
        ref = index.ref(parsed.name, version)
        assert ref is not None
        recipe = index.load(ref)
        deps = ", ".join(recipe.dependencies) or "none"
        print(f"{recipe.name} {recipe.version}  [{recipe.license}]  from {ref.origin}")
        print(f"    {recipe.description}\n    build: {recipe.build.type}   depends on: {deps}")
    return 0


def _cmd_search(parsed: argparse.Namespace) -> int:
    workspace = _workspace(parsed)
    index = _index(workspace, PackageStore())
    names = [n for n in index.names() if parsed.text.lower() in n.lower()]
    for name in names:
        print(f"  {name:<24}{', '.join(reversed(index.versions(name)))}")
    if not names:
        print("No package matches.")
    return 0 if names else 1


def _cmd_vendor(parsed: argparse.Namespace) -> int:
    workspace = _workspace(parsed)
    if parsed.verify:
        bad = vendor.verify(workspace)
        for name in bad:
            print(f"  MODIFIED: {name}")
        print("vendor/ matches its recorded digests." if not bad else f"{len(bad)} package(s) differ.")
        return 1 if bad else 0
    done = vendor.vendor(workspace, PackageStore(), Path(parsed.dir) if parsed.dir else None)
    print(f"Vendored {len(done)} package(s): {', '.join(done)}. Commit vendor/ to build fully offline.")
    return 0


def _cmd_audit(parsed: argparse.Namespace) -> int:
    workspace = _workspace(parsed)
    lock = lock_mod.load(workspace.root)
    if lock is None:
        raise ChError("CH6005", name="(run `charpente pkg install` first)")
    report = audit_mod.audit(lock, _recipes(workspace, PackageStore()))
    for f in report.findings:
        print(f"  VULNERABLE {f.package} {f.version}: {f.id} {f.summary}")
    for item in report.unchecked:
        print(f"  not checked (no purl in its recipe): {item}")
    print(f"Checked {report.checked} package(s): {len(report.findings)} finding(s). "
          f"OSV coverage of C/C++ libraries is partial: no finding does not mean no vulnerability.")
    return 1 if report.findings else 0


def _cmd_registry(parsed: argparse.Namespace) -> int:
    store = PackageStore()
    if parsed.verb == "list":
        for url in store.registries():
            print(url)
        return 0
    if not parsed.url:
        raise ChError("CH4005", usage="Usage: charpente pkg registry add|remove URL")
    if parsed.verb == "add":
        store.add_registry(parsed.url)
        print(f"Added {parsed.url}")
        return 0
    ok = store.remove_registry(parsed.url)
    print("Removed." if ok else "No such registry.")
    return 0 if ok else 1


def _cmd_mirror(parsed: argparse.Namespace) -> int:
    directory = Path(parsed.directory)
    if parsed.verb == "populate":
        workspace = _workspace(parsed)
        added = mirror.populate(workspace, PackageStore(), directory)
        print(f"Mirror {directory}: {len(added)} package(s) ({', '.join(added) or 'none'}).")
        return 0
    if not (directory / "index.json").exists():
        raise ChError("CH4005", usage=f"{directory} has no index.json: create it with `charpente pkg mirror populate`.")
    print(f"Serving {directory} (Ctrl+C to stop). This server has no authentication"
          f"{'' if parsed.host in ('127.0.0.1', 'localhost') else f' and is reachable from {parsed.host}'}.")
    mirror.serve_forever(directory, parsed.host, parsed.port, announce=lambda url: print(f"Registry: {url}"))
    return 0


def execute_sbom(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente sbom",
                                     description="Write a Software Bill of Materials (SPDX and/or CycloneDX).")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--format", choices=["spdx", "cyclonedx", "both"], default="both")
    parser.add_argument("--output", default=None, help="Output folder (default: dist/); '-' prints to stdout")
    parsed = parser.parse_args(args)
    workspace = load(parsed.file, None, materialize_packages=False)
    lock = lock_mod.load(workspace.root) or lock_mod.Lock()
    recipes = _recipes(workspace, PackageStore())
    docs = {}
    if parsed.format in ("spdx", "both"):
        docs["spdx"] = sbom.spdx(workspace.name, workspace.version, lock, recipes)
    if parsed.format in ("cyclonedx", "both"):
        docs["cyclonedx"] = sbom.cyclonedx(workspace.name, workspace.version, lock, recipes)
    if parsed.output == "-":
        print(json.dumps(docs if len(docs) > 1 else next(iter(docs.values())), indent=2))
        return 0
    out = Path(parsed.output) if parsed.output else workspace.root / "dist"
    out.mkdir(parents=True, exist_ok=True)
    for kind, doc in docs.items():
        path = out / f"{workspace.name}.{'spdx' if kind == 'spdx' else 'cdx'}.json"
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        print(f"Wrote {path} ({len(lock.packages)} package(s))")
    if not lock.packages:
        print("Note: this workspace has no locked packages; the SBOM lists only the application itself.")
    return 0

