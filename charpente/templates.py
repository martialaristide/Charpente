"""Project templates: `charpente init NAME --template T`.

A template is a folder (`templates_data/<name>/`) with a `template.toml` describing it and a `files/` tree copied to the new
project. Text tokens are replaced in file *contents and names*:

    @NAME@      the project name as given                  my-game
    @IDENT@     a C/C++ identifier made from it            my_game
    @TITLE@     a display name                             My Game
    @PACKAGE@   a reverse-DNS id (change it!)               dev.example.my_game

Templates are data, so a project or a module can add its own: bundled ones are registered through the same `template`
extension point a module uses, and a project can put templates in `.charpente/templates/`. Every bundled template says, in
its `template.toml`, what was verified (built, run) and what was not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import _toml
from .errors import ChError

_KEYS = {"name", "description", "kits", "platforms", "verified", "unverified", "install", "next"}
_TOKEN = re.compile(r"@(NAME|IDENT|TITLE|PACKAGE)@")


@dataclass(frozen=True)
class Info:
    name: str
    description: str
    kits: Tuple[str, ...] = ()
    platforms: Tuple[str, ...] = ()
    verified: str = ""
    unverified: str = ""
    install: bool = False              # the project needs `charpente pkg install` before its first build
    next: Tuple[str, ...] = ()         # commands to suggest afterwards


def bundled_dir() -> Path:
    return Path(__file__).resolve().parent / "templates_data"


def values_for(project_name: str) -> Dict[str, str]:
    ident = re.sub(r"[^a-z0-9_]", "_", project_name.lower())
    if not ident or ident[0].isdigit():
        ident = "p_" + ident
    title = re.sub(r"[-_.]+", " ", project_name).strip().title() or project_name
    return {"NAME": project_name, "IDENT": ident, "TITLE": title, "PACKAGE": f"dev.example.{ident}"}


def real_name(relative: str) -> str:
    """`dot_gitignore` -> `.gitignore`, `dot_charpente/quality.toml` -> `.charpente/quality.toml`. Hidden files are stored
    with a `dot_` prefix because packaging tools skip dot-files (they were silently missing from the wheel)."""
    return "/".join("." + part[4:] if part.startswith("dot_") else part for part in relative.split("/"))


def render(text: str, values: Dict[str, str]) -> str:
    return _TOKEN.sub(lambda m: values[m.group(1)], text)


def parse_info(text: str, path: str) -> Info:
    try:
        data = _toml.loads(text)
    except _toml.TOMLDecodeError as exc:
        raise ChError("CH6008", path=path, detail=f"not valid TOML: {exc}") from exc
    table = data.get("template")
    if not isinstance(table, dict):
        raise ChError("CH6008", path=path, detail="a template.toml has a [template] table")
    unknown = sorted(set(table) - _KEYS)
    if unknown:
        raise ChError("CH6008", path=path, detail=f"[template] unknown key(s) {', '.join(map(repr, unknown))}")
    if not isinstance(table.get("name"), str) or not re.fullmatch(r"[a-z][a-z0-9-]*", table["name"]):
        raise ChError("CH6008", path=path, detail="[template] name is required (lower case, digits, dashes)")
    return Info(name=table["name"], description=str(table.get("description", "")), kits=tuple(table.get("kits", ())),
                platforms=tuple(table.get("platforms", ())), verified=str(table.get("verified", "")),
                unverified=str(table.get("unverified", "")), install=bool(table.get("install", False)),
                next=tuple(str(n) for n in table.get("next", ())))


class DirTemplate:
    """A template stored as a folder. Implements the module API's `Template` protocol."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.info = parse_info((folder / "template.toml").read_text(encoding="utf-8"), str(folder / "template.toml"))
        self.name = self.info.name
        self.description = self.info.description

    def files(self) -> List[Path]:
        root = self.folder / "files"
        return sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts) if root.is_dir() else []

    def plan(self, destination: Path, project_name: str) -> List[Tuple[Path, Path]]:
        """[(source file, destination file)] for this project name."""
        values = values_for(project_name)
        root = self.folder / "files"
        out = []
        for source in self.files():
            relative = render(real_name(source.relative_to(root).as_posix()), values)
            out.append((source, destination / relative))
        return out

    def generate(self, destination: Path, project_name: str) -> List[Path]:
        values = values_for(project_name)
        plan = self.plan(destination, project_name)
        clashes = [str(target) for _, target in plan if target.exists()]
        if clashes:
            raise ChError("CH4008", template=self.name, files=", ".join(clashes[:5]) + (" ..." if len(clashes) > 5 else ""))
        written: List[Path] = []
        for source, target in plan:
            target.parent.mkdir(parents=True, exist_ok=True)
            data = source.read_bytes()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                target.write_bytes(data)                      # binary files are copied as they are
            else:
                target.write_text(render(text, values), encoding="utf-8", newline="")
            written.append(target)
        return written


def load_all(extra_dir: Optional[Path] = None) -> Dict[str, DirTemplate]:
    """Bundled templates plus a project's `.charpente/templates/*` (which may add, never replace, a bundled name)."""
    found: Dict[str, DirTemplate] = {}
    for base in (bundled_dir(), extra_dir):
        if base is None or not base.is_dir():
            continue
        for folder in sorted(p for p in base.iterdir() if (p / "template.toml").is_file()):
            template = DirTemplate(folder)
            if template.name in found:
                raise ChError("CH6008", path=str(folder), detail=f"a template named {template.name!r} already exists")
            found[template.name] = template
    return found
