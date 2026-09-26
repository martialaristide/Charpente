"""Kits: tested selections of libraries, declared as data (`charpente/pkg/kits/*.toml`).

A kit is a name for a set of packages that work together: `ws.kit("kit-core")` requires them all, and
`t.uses("kit-core")` uses all of them. Every member is an ordinary recipe (checksummed source, license, purl), so a kit
adds no new mechanism -- only the curation, and the statement of *what was verified*, kept honest in the kit file.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .. import _toml
from ..errors import ChError

_KEYS = {"name", "description", "requires", "uses", "verified", "unverified", "notes"}


@dataclass(frozen=True)
class Kit:
    name: str
    description: str
    requires: Tuple[str, ...]           # `ws.requires` specs (NAME@CONSTRAINT)
    uses: Tuple[str, ...]               # target names `t.uses("kit-x")` expands to
    verified: str = ""                  # what was actually built/run, and where
    unverified: str = ""                # what is declared but not verified
    notes: str = ""


def bundled_dir() -> Path:
    return Path(__file__).resolve().parent / "kits"


def parse(text: str, path: str = "<kit>") -> Kit:
    try:
        data = _toml.loads(text)
    except _toml.TOMLDecodeError as exc:
        raise ChError("CH6008", path=path, detail=f"not valid TOML: {exc}") from exc
    table = data.get("kit")
    if not isinstance(table, dict) or set(data) != {"kit"}:
        raise ChError("CH6008", path=path, detail="a kit file has exactly one [kit] table")
    unknown = sorted(set(table) - _KEYS)
    if unknown:
        raise ChError("CH6008", path=path, detail=f"[kit] unknown key(s) {', '.join(map(repr, unknown))}")
    name = table.get("name")
    if not isinstance(name, str) or not name.startswith("kit-"):
        raise ChError("CH6008", path=path, detail='[kit] name is required and starts with "kit-"')
    lists = {}
    for key in ("requires", "uses"):
        value = table.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            raise ChError("CH6008", path=path, detail=f"[kit] {key} must be a list of strings")
        lists[key] = tuple(value)
    if not lists["requires"]:
        raise ChError("CH6008", path=path, detail="[kit] requires must not be empty")
    return Kit(name=name, description=str(table.get("description", "")), requires=lists["requires"],
               uses=lists["uses"] or tuple(spec.partition("@")[0] for spec in lists["requires"]),
               verified=str(table.get("verified", "")), unverified=str(table.get("unverified", "")),
               notes=str(table.get("notes", "")))


def load_all(extra_dir: Optional[Path] = None) -> Dict[str, Kit]:
    """Bundled kits, plus a project's own `.charpente/kits/*.toml` (which may add kits, never replace a bundled one)."""
    kits: Dict[str, Kit] = {}
    for folder in (bundled_dir(), extra_dir):
        if folder is None or not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.toml")):
            kit = parse(path.read_text(encoding="utf-8"), str(path))
            if kit.name in kits:
                raise ChError("CH6008", path=str(path), detail=f"a kit named {kit.name!r} already exists")
            kits[kit.name] = kit
    return kits


def get(name: str, extra_dir: Optional[Path] = None) -> Kit:
    kits = load_all(extra_dir)
    if name not in kits:
        raise ChError("CH6016", name=name, known=", ".join(sorted(kits)) or "(none)")
    return kits[name]


def members(kits: Dict[str, Kit], names: List[str]) -> List[str]:
    """`uses("kit-core", "engine")` -> the kit's members followed by `engine` (order kept, duplicates dropped)."""
    out: List[str] = []
    for name in names:
        for item in (kits[name].uses if name in kits else (name,)):
            if item not in out:
                out.append(item)
    return out
