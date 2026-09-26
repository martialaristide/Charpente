"""Package recipes: a declarative description of a library and how to build it.

A recipe is TOML -- *data, not code* -- so installing or reading one never
executes anything. The build itself is done by Charpente's own engine: a recipe
becomes ordinary targets (header-only or a static library) in your workspace,
compiled with your toolchain, cached like everything else.

    [package]
    name = "fmt"
    version = "10.2.1"
    license = "MIT"
    description = "A modern formatting library"
    homepage = "https://fmt.dev"
    purl = "pkg:github/fmtlib/fmt"          # for the vulnerability audit and the SBOM

    [source]
    url = "https://github.com/fmtlib/fmt/archive/refs/tags/10.2.1.tar.gz"
    sha256 = "1250e4cc58bf06ee631567523f48848dc4596133e163f02615c97f78bab6c811"
    strip_prefix = "fmt-10.2.1"             # the archive's top-level folder

    [build]
    type = "sources"                        # header_only | sources
    language = "cpp"                        # cpp | c
    standard = "c++11"
    sources = ["src/format.cc", "src/os.cc"]
    include_dirs = ["include"]              # public: users get them
    private_include_dirs = []
    defines = []                            # public
    private_defines = []
    compile_flags = []                      # public
    links = []                              # system libraries users must link

    [build.platform."windows-*"]            # merged in when the platform matches
    links = ["ws2_32"]

    [dependencies]
    requires = ["other@^1.2"]

    [[patch]]                               # optional unified diffs applied after extraction
    file = "fix.patch"                      # relative to the recipe file
    sha256 = "..."
"""
from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Set, Tuple

from .. import _toml
from ..errors import ChError
from ..semver import Constraint, Version

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_BUILD_TYPES = ("header_only", "sources")
_LANGUAGES = ("cpp", "c")


@dataclass(frozen=True)
class Source:
    url: str
    sha256: str
    strip_prefix: str = ""


@dataclass(frozen=True)
class Patch:
    file: str
    sha256: str = ""


@dataclass(frozen=True)
class BuildOverride:
    defines: Tuple[str, ...] = ()
    private_defines: Tuple[str, ...] = ()
    compile_flags: Tuple[str, ...] = ()
    links: Tuple[str, ...] = ()
    sources: Tuple[str, ...] = ()
    exclude: Tuple[str, ...] = ()
    include_dirs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Build:
    type: str = "header_only"
    language: str = "cpp"
    standard: str = ""
    sources: Tuple[str, ...] = ()
    exclude: Tuple[str, ...] = ()
    include_dirs: Tuple[str, ...] = ()
    private_include_dirs: Tuple[str, ...] = ()
    defines: Tuple[str, ...] = ()
    private_defines: Tuple[str, ...] = ()
    compile_flags: Tuple[str, ...] = ()
    links: Tuple[str, ...] = ()
    #: file globs (relative to the source root) that a vendored copy must keep; empty = derive
    #: them from include_dirs and sources. Needed when include_dirs is "." (the whole repository).
    keep: Tuple[str, ...] = ()
    platform: Tuple[Tuple[str, BuildOverride], ...] = ()

    def overrides_for(self, platform_name: str) -> List[BuildOverride]:
        return [o for pattern, o in self.platform if fnmatch.fnmatchcase(platform_name.lower(), pattern.lower())]


@dataclass(frozen=True)
class Recipe:
    name: str
    version: str
    license: str
    description: str
    source: Source
    build: Build
    homepage: str = ""
    purl: str = ""
    dependencies: Tuple[str, ...] = ()
    patches: Tuple[Patch, ...] = ()
    #: sha256 of the recipe file's exact bytes (pinned in the lock file)
    digest: str = field(default="", compare=False)
    #: folder the recipe was read from (patches are relative to it); "" if unknown
    directory: str = field(default="", compare=False)

    @property
    def ident(self) -> str:
        return f"{self.name}@{self.version}"


def _strings(value: Any, where: str, path: str) -> Tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return tuple(value)
    raise ChError("CH6008", path=path, detail=f"{where}: expected a list of strings")


def _known(table: Mapping[str, Any], allowed: Set[str], where: str, path: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ChError("CH6008", path=path, detail=f"{where}: unknown key(s) {', '.join(map(repr, unknown))}")


_BUILD_LISTS = ("sources", "exclude", "include_dirs", "private_include_dirs", "defines", "private_defines",
                "compile_flags", "links", "keep")


def parse(text: str, path: str = "<recipe>", directory: str = "") -> Recipe:
    """Parse and validate a recipe. Raises CH6008 with the first problem found."""
    try:
        data = _toml.loads(text)
    except _toml.TOMLDecodeError as exc:
        raise ChError("CH6008", path=path, detail=f"not valid TOML: {exc}") from exc
    _known(data, {"package", "source", "build", "dependencies", "patch"}, "top level", path)

    pkg = data.get("package") or {}
    _known(pkg, {"name", "version", "license", "description", "homepage", "purl"}, "[package]", path)
    for key in ("name", "version", "license"):
        if not isinstance(pkg.get(key), str) or not pkg[key].strip():
            raise ChError("CH6008", path=path, detail=f"[package] {key} is required")
    if not _NAME_RE.match(pkg["name"]):
        raise ChError("CH6008", path=path, detail=f"[package] name {pkg['name']!r} has invalid characters")
    try:
        Version.parse(pkg["version"])
    except ChError as exc:
        raise ChError("CH6008", path=path, detail=f"[package] version: {exc.message}") from exc

    src = data.get("source") or {}
    _known(src, {"url", "sha256", "strip_prefix"}, "[source]", path)
    if not isinstance(src.get("url"), str) or not src["url"]:
        raise ChError("CH6008", path=path, detail="[source] url is required")
    if not isinstance(src.get("sha256"), str) or not _SHA256_RE.match(src["sha256"].lower()):
        raise ChError("CH6008", path=path, detail="[source] sha256 is required (64 hex characters): every "
                                                  "archive is verified before use")
    source = Source(url=src["url"], sha256=src["sha256"].lower(), strip_prefix=str(src.get("strip_prefix", "")))

    build_table = data.get("build") or {}
    _known(build_table, {"type", "language", "standard", "platform", *_BUILD_LISTS}, "[build]", path)
    build_type = str(build_table.get("type", "header_only"))
    if build_type not in _BUILD_TYPES:
        raise ChError("CH6008", path=path, detail=f"[build] type must be one of {', '.join(_BUILD_TYPES)}")
    language = str(build_table.get("language", "cpp"))
    if language not in _LANGUAGES:
        raise ChError("CH6008", path=path, detail=f"[build] language must be one of {', '.join(_LANGUAGES)}")
    lists = {k: _strings(build_table.get(k, []), f"[build] {k}", path) for k in _BUILD_LISTS}
    if build_type == "sources" and not lists["sources"]:
        raise ChError("CH6008", path=path, detail="[build] type = \"sources\" needs sources = [...]")
    overrides: List[Tuple[str, BuildOverride]] = []
    for pattern, table in (build_table.get("platform") or {}).items():
        _known(table, {"defines", "private_defines", "compile_flags", "links", "sources", "exclude", "include_dirs"},
               f"[build.platform.{pattern}]", path)
        overrides.append((pattern, BuildOverride(**{k: _strings(v, f"[build.platform.{pattern}] {k}", path)
                                                    for k, v in table.items()})))
    build = Build(type=build_type, language=language, standard=str(build_table.get("standard", "")),
                  platform=tuple(overrides), **lists)

    deps_table = data.get("dependencies") or {}
    _known(deps_table, {"requires"}, "[dependencies]", path)
    dependencies = _strings(deps_table.get("requires", []), "[dependencies] requires", path)
    for dep in dependencies:
        name, _, constraint = dep.partition("@")
        if not _NAME_RE.match(name):
            raise ChError("CH6008", path=path, detail=f"[dependencies] {dep!r} is not NAME or NAME@CONSTRAINT")
        Constraint.parse(constraint or "*")

    patches: List[Patch] = []
    for raw in data.get("patch", []):
        _known(raw, {"file", "sha256"}, "[[patch]]", path)
        if not isinstance(raw.get("file"), str):
            raise ChError("CH6008", path=path, detail="[[patch]] needs file = \"...\"")
        patches.append(Patch(file=raw["file"], sha256=str(raw.get("sha256", "")).lower()))

    return Recipe(
        name=pkg["name"], version=pkg["version"], license=pkg["license"], description=str(pkg.get("description", "")),
        homepage=str(pkg.get("homepage", "")), purl=str(pkg.get("purl", "")), source=source, build=build,
        dependencies=dependencies, patches=tuple(patches),
        digest=hashlib.sha256(text.encode("utf-8")).hexdigest(), directory=directory,
    )


def load(path: Path) -> Recipe:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise ChError("CH6008", path=str(path), detail=f"cannot be read: {exc}") from exc
    recipe = parse(raw.decode("utf-8"), str(path), str(Path(path).parent))
    # the digest is over the exact bytes, not the decoded text (line endings matter for pinning)
    return Recipe(**{**recipe.__dict__, "digest": hashlib.sha256(raw).hexdigest()})


def constraint_of(spec: str) -> Tuple[str, Constraint]:
    name, _, constraint = spec.partition("@")
    return name, Constraint.parse(constraint or "*")


def describe_build(build: Build) -> Dict[str, Any]:
    """A plain-dict view of the build section (used in SBOMs and diagnostics)."""
    return {"type": build.type, "language": build.language, "standard": build.standard}
