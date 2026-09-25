"""Reading and validating `charpente-module.toml`.

    [module]
    name = "charpente-shaders"
    version = "1.2.0"
    api = "^2.0"                 # module API range this module was written for
    license = "Apache-2.0"
    description = "Compilation GLSL/HLSL vers SPIR-V"
    entry = "charpente_shaders:register"     # package.module:function

    [provides]
    commands = ["shaders"]

    [capabilities]
    process = ["glslangValidator"]
    filesystem = "workspace"
    network = false
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .. import _toml
from ..errors import ChError, ChValueError
from ..semver import Constraint, Version
from .api import EXTENSION_KINDS, FILESYSTEM_LEVELS, MANIFEST_NAME, MODULE_API_VERSION, Capabilities, Manifest

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ENTRY_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")
_KNOWN_MODULE_KEYS = {"name", "version", "api", "license", "description", "entry", "python", "homepage"}


def parse(data: Dict[str, Any], source: str = MANIFEST_NAME) -> Tuple[Manifest, List[str]]:
    """(manifest, warnings). Raises CH7003 listing *every* problem at once."""
    problems: List[str] = []
    warnings: List[str] = []
    module = data.get("module")
    if not isinstance(module, dict):
        raise ChValueError("CH7003", path=source, detail="missing [module] table")

    def text(key: str, required: bool = True) -> str:
        value = module.get(key, "")
        if not isinstance(value, str) or (required and not value.strip()):
            problems.append(f"[module] {key}: required, a non-empty string")
            return ""
        return value.strip()

    name, version, api = text("name"), text("version"), text("api")
    license_, description, entry = text("license"), text("description"), text("entry")
    python = text("python", required=False)
    homepage = text("homepage", required=False)

    if name and not _NAME_RE.match(name):
        problems.append(f"[module] name {name!r}: use lowercase letters, digits, '-', '_' and '.'")
    if version:
        try:
            Version.parse(version)
        except ChValueError:
            problems.append(f"[module] version {version!r}: not a semantic version")
    if api:
        try:
            Constraint.parse(api)
        except ChValueError:
            problems.append(f"[module] api {api!r}: not a valid version constraint")
    if python:
        try:
            Constraint.parse(python)
        except ChValueError:
            problems.append(f"[module] python {python!r}: not a valid version constraint")
    if entry and not _ENTRY_RE.match(entry):
        problems.append(f"[module] entry {entry!r}: expected 'package.module:function'")
    for key in module:
        if key not in _KNOWN_MODULE_KEYS:
            warnings.append(f"[module] unknown key {key!r} ignored")

    provides: Dict[str, Tuple[str, ...]] = {}
    raw_provides = data.get("provides", {})
    if not isinstance(raw_provides, dict):
        problems.append("[provides] must be a table")
        raw_provides = {}
    known = set(EXTENSION_KINDS.values()) | {"events"}
    for key, value in raw_provides.items():
        if key not in known:
            warnings.append(f"[provides] unknown key {key!r} ignored")
            continue
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            problems.append(f"[provides] {key}: a list of strings")
            continue
        provides[key] = tuple(value)

    caps = Capabilities()
    raw_caps = data.get("capabilities", {})
    if not isinstance(raw_caps, dict):
        problems.append("[capabilities] must be a table")
    else:
        process = raw_caps.get("process", [])
        filesystem = raw_caps.get("filesystem", "none")
        network = raw_caps.get("network", False)
        if not isinstance(process, list) or not all(isinstance(p, str) for p in process):
            problems.append("[capabilities] process: a list of program names")
            process = []
        if filesystem not in FILESYSTEM_LEVELS:
            problems.append(f"[capabilities] filesystem {filesystem!r}: one of {', '.join(FILESYSTEM_LEVELS)}")
            filesystem = "none"
        if not (isinstance(network, bool) or (isinstance(network, list) and all(isinstance(h, str) for h in network))):
            problems.append("[capabilities] network: true, false, or a list of host names")
            network = False
        for key in raw_caps:
            if key not in ("process", "filesystem", "network"):
                warnings.append(f"[capabilities] unknown key {key!r} ignored")
        caps = Capabilities(process=tuple(process), filesystem=str(filesystem),
                            network=tuple(network) if isinstance(network, list) else bool(network))

    if problems:
        raise ChValueError("CH7003", path=source, detail="; ".join(problems))
    return Manifest(name=name, version=version, api=api, license=license_, description=description,
                    entry=entry, python=python, provides=provides, capabilities=caps,
                    homepage=homepage), warnings


def loads(text: str, source: str = MANIFEST_NAME) -> Tuple[Manifest, List[str]]:
    try:
        data = _toml.loads(text)
    except _toml.TOMLDecodeError as exc:
        raise ChValueError("CH7003", path=source, detail=f"not valid TOML: {exc}") from exc
    return parse(data, source)


def load(directory: Path) -> Tuple[Manifest, List[str]]:
    path = Path(directory) / MANIFEST_NAME
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ChValueError("CH7003", path=str(path), detail="cannot read the manifest") from exc
    return loads(text, str(path))


def check_api(manifest: Manifest) -> None:
    """Raise CH7004 if this Charpente's module API is outside the module's range."""
    if not Constraint.parse(manifest.api).matches(MODULE_API_VERSION):
        raise ChError("CH7004", name=manifest.name, required=manifest.api, provided=MODULE_API_VERSION)
