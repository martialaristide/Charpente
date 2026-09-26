"""`charpente kit list | show NAME | add NAME` -- curated sets of libraries."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List

from ..errors import ChError
from ..pkg import kits as kits_mod
from ..pkg import recipe as recipe_mod
from ..pkg.index import RecipeIndex
from ..pkg.store import PackageStore
from ..workspace_finder import find_workspace_file
from ._common import find_root

_WITH = re.compile(r"^(?P<indent>[ \t]*)with\s+Workspace\(.*\)\s+as\s+(?P<var>\w+)\s*:\s*$", re.M)


def _licenses(kit: kits_mod.Kit, root: Path) -> List[str]:
    index = RecipeIndex(PackageStore(), [], root)
    out = []
    for spec in kit.requires:
        name, constraint = recipe_mod.constraint_of(spec)
        version = index.best(name, constraint)
        ref = index.ref(name, version) if version else None
        try:
            recipe = index.load(ref) if ref else None
        except ChError as exc:
            out.append(f"{name} ({exc.code})")
            continue
        out.append(f"{name} {recipe.version} ({recipe.license})" if recipe else f"{name} (no recipe found)")
    return out


def add_to_file(text: str, kit: str) -> str:
    """Insert `ws.kit("kit-x")` right after the `with Workspace(...) as ws:` line (unchanged if already there)."""
    if re.search(rf"\.kit\(\s*[\"']{re.escape(kit)}[\"']\s*\)", text):
        return text
    match = _WITH.search(text)
    if not match:
        raise ChError("CH4005", usage="No `with Workspace(...) as ws:` line to add the kit to; add ws.kit(\"" + kit + "\") by hand.")
    inner = match.group("indent") + "    "
    line = "\n" + inner + match.group("var") + '.kit("' + kit + '")'
    return text[:match.end()] + line + text[match.end():]


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente kit", description="Curated, tested selections of libraries.")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="List the kits")
    show = sub.add_parser("show", help="What a kit contains, and what was verified")
    show.add_argument("name")
    add = sub.add_parser("add", help='Add ws.kit("NAME") to the workspace file')
    add.add_argument("name")
    parsed = parser.parse_args(args)

    root = find_root()
    extra = root / ".charpente" / "kits"
    if parsed.action == "list":
        for kit in kits_mod.load_all(extra).values():
            print(f"  {kit.name:<14} {kit.description}")
            print(f"  {'':<14} {', '.join(spec.partition('@')[0] for spec in kit.requires)}")
        return 0
    kit = kits_mod.get(parsed.name, extra)
    if parsed.action == "show":
        print(f"{kit.name}\n  {kit.description}\n")
        for line in _licenses(kit, root):
            print(f"  - {line}")
        print(f"\nUse it: ws.kit(\"{kit.name}\") in the workspace, then t.uses(\"{kit.name}\") in a target; "
              "`charpente pkg install` fetches the sources (checksummed, pinned in charpente.lock).")
        for label, text in (("Verified", kit.verified), ("Not verified", kit.unverified), ("Notes", kit.notes)):
            if text:
                print(f"\n{label}: {text}")
        return 0
    path = find_workspace_file(start_dir=root)
    if path.suffix.lower() == ".toml":
        raise ChError("CH4005", usage="Kits are not supported in the charpente.toml form yet: use a .charpente file.")
    path.write_text(add_to_file(path.read_text(encoding="utf-8-sig"), kit.name), encoding="utf-8")
    print(f'Added ws.kit("{kit.name}") to {path.name}. Next: `charpente pkg install`, then t.uses("{kit.name}").')
    return 0
