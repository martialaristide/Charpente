"""The declarative workspace: `charpente.toml`.

For simple projects, and for repositories you do not trust: a TOML file holds
*data only*, so loading it executes nothing and needs no approval. It maps
one-to-one onto the DSL:

    [workspace]
    name = "Demo"
    version = "1.0.0"
    configurations = ["Debug", "Release"]
    requires = ["fmt@^10"]

    [options.fast_math]
    default = false
    help = "Enable -ffast-math"

    [[target]]
    name = "engine"
    kind = "static_library"          # executable | static_library | shared_library | test | header_only | ...
    standard = "c++20"
    sources = ["engine/**/*.cpp"]
    public_include_dirs = ["engine/include"]

    [[target]]
    name = "app"
    uses = ["engine", "fmt"]
    sources = ["app/**/*.cpp"]

      [[target.when]]                # conditional settings
      config = "Release"             # also: platform = "linux-*", toolchain = "gcc", option = "fast_math=true"
      compile_flags = ["-ffast-math"]

    [[rule]]
    name = "version"
    command = ["python", "tools/gen_version.py"]
    inputs = ["VERSION"]
    outputs = ["gen/version.h"]

Unknown keys are errors (a typo must not be silently ignored).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set

from .. import _toml
from ..errors import ChError
from .api import parse_option_value
from .model import Kind, Language, OptionSpec, Overlay, Rule, Target, Workspace

_WORKSPACE_KEYS = {"name", "version", "configurations", "platforms", "requires"}
_TARGET_LISTS = {
    "sources": "source_patterns", "exclude": "exclude_patterns", "include_dirs": "include_dirs",
    "defines": "define_macros", "links": "link_libraries", "depends_on": "depends_on",
    "compile_flags": "extra_compile_flags", "link_flags": "extra_link_flags", "uses": "uses",
    "uses_public": "uses_public", "public_include_dirs": "public_include_dirs",
    "interface_include_dirs": "interface_include_dirs", "public_defines": "public_define_macros",
    "interface_defines": "interface_define_macros", "public_compile_flags": "public_compile_flags",
    "public_links": "public_link_libraries", "rules": "rules", "assets": "assets",
}
_TARGET_SCALARS = {"name", "kind", "language", "standard", "shader_target", "platforms", "when"}
_WHEN_LISTS = {
    "sources": "source_patterns", "exclude": "exclude_patterns", "include_dirs": "include_dirs",
    "defines": "define_macros", "links": "link_libraries", "depends_on": "depends_on",
    "compile_flags": "extra_compile_flags", "link_flags": "extra_link_flags", "uses": "uses",
    "public_include_dirs": "public_include_dirs", "public_defines": "public_define_macros",
}
_WHEN_CONDITIONS = {"config", "platform", "toolchain", "option"}
_RULE_KEYS = {"name", "command", "inputs", "outputs", "description"}
_OPTION_KEYS = {"default", "help", "choices"}
_KINDS = {k.value: k for k in Kind}
_LANGUAGES = {lang.value: lang for lang in Language}


def _fail(path: str, detail: str) -> ChError:
    return ChError("CH1025", path=path, detail=detail)


def _strings(path: str, where: str, value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    raise _fail(path, f"{where}: expected a string or a list of strings")


def _check_keys(path: str, where: str, table: Mapping[str, Any], allowed: Set[str]) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise _fail(path, f"{where}: unknown key(s) {', '.join(map(repr, unknown))}; "
                          f"valid keys: {', '.join(sorted(allowed))}")


def load_toml_workspace(file_path: Path, option_overrides: Optional[Dict[str, str]] = None) -> Workspace:
    """Parse `file_path` into a Workspace. Raises CH1025 listing what is wrong."""
    shown = str(file_path)
    try:
        data = _toml.load_file(file_path)
    except _toml.TOMLDecodeError as exc:
        raise _fail(shown, f"not valid TOML: {exc}") from exc
    except OSError as exc:
        raise _fail(shown, f"cannot be read: {exc}") from exc

    _check_keys(shown, "top level", data, {"workspace", "options", "target", "rule"})
    head = data.get("workspace")
    if not isinstance(head, dict) or not isinstance(head.get("name"), str):
        raise _fail(shown, "[workspace] name = \"...\" is required")
    _check_keys(shown, "[workspace]", head, _WORKSPACE_KEYS)

    ws = Workspace(name=head["name"], location=file_path.parent, version=str(head.get("version", "")))
    if "configurations" in head:
        ws.configurations = _strings(shown, "[workspace] configurations", head["configurations"])
    if "platforms" in head:
        ws.platforms = _strings(shown, "[workspace] platforms", head["platforms"])
    requires = head.get("requires", [])
    if isinstance(requires, dict):
        requires = [f"{name}@{constraint}" if constraint not in ("", "*") else name
                    for name, constraint in requires.items()]
    from .api import Workspace as ApiWorkspace

    api_ws = ApiWorkspace.__new__(ApiWorkspace)
    api_ws._model = ws
    api_ws.requires(*_strings(shown, "[workspace] requires", requires))

    overrides = dict(option_overrides or {})
    for name, spec in (data.get("options") or {}).items():
        if not isinstance(spec, dict):
            raise _fail(shown, f"[options.{name}] must be a table")
        _check_keys(shown, f"[options.{name}]", spec, _OPTION_KEYS)
        default = spec.get("default")
        choices = spec.get("choices")
        kind = "enum" if choices else "bool" if isinstance(default, bool) else "int" if isinstance(default, int) \
            else "string"
        opt = OptionSpec(name=name, default=default, help=str(spec.get("help", "")),
                         choices=tuple(choices) if choices else None, kind=kind)
        ws.options[name] = opt
        ws.option_values[name] = parse_option_value(opt, overrides.pop(name)) if name in overrides else default
    if overrides:
        raise ChError("CH1022", name=sorted(overrides)[0], known=", ".join(sorted(ws.options)) or "(none)")

    for raw in data.get("rule", []):
        _check_keys(shown, "[[rule]]", raw, _RULE_KEYS)
        name = raw.get("name")
        command = raw.get("command")
        if not isinstance(name, str) or not isinstance(command, list) or not raw.get("outputs"):
            raise _fail(shown, "[[rule]] needs name, command = [...] (a list, never a shell string) and outputs")
        ws.rules[name] = Rule(name=name, argv=[str(c) for c in command],
                              inputs=_strings(shown, f"rule {name} inputs", raw.get("inputs", [])),
                              outputs=_strings(shown, f"rule {name} outputs", raw["outputs"]),
                              description=str(raw.get("description", "")))

    for raw in data.get("target", []):
        ws.add_target(_target(shown, raw, ws))
    return ws


def _target(shown: str, raw: Mapping[str, Any], ws: Workspace) -> Target:
    if not isinstance(raw.get("name"), str):
        raise _fail(shown, "every [[target]] needs name = \"...\"")
    name = raw["name"]
    where = f"[[target]] {name}"
    _check_keys(shown, where, raw, set(_TARGET_LISTS) | _TARGET_SCALARS)
    target = Target(name=name, location=ws.location)
    if "kind" in raw:
        if raw["kind"] not in _KINDS:
            raise _fail(shown, f"{where}: kind {raw['kind']!r} is not one of {', '.join(sorted(_KINDS))}")
        target.kind = _KINDS[raw["kind"]]
    if "language" in raw:
        if raw["language"] not in _LANGUAGES:
            raise _fail(shown, f"{where}: language must be one of {', '.join(sorted(_LANGUAGES))}")
        target.language = _LANGUAGES[raw["language"]]
    if "standard" in raw:
        target.standard = str(raw["standard"])
    if "shader_target" in raw:
        target.shader_target = str(raw["shader_target"])
    if "platforms" in raw:
        target.platforms = _strings(shown, f"{where} platforms", raw["platforms"])
    for key, attr in _TARGET_LISTS.items():
        if key in raw:
            getattr(target, attr).extend(_strings(shown, f"{where} {key}", raw[key]))
    for cond in raw.get("when", []):
        _check_keys(shown, f"{where} [[when]]", cond, _WHEN_CONDITIONS | set(_WHEN_LISTS))
        overlay = Overlay()
        for dim in ("config", "platform", "toolchain"):
            if dim in cond:
                overlay.when[dim] = str(cond[dim])
        if "option" in cond:
            opt_name, _, opt_value = str(cond["option"]).partition("=")
            overlay.when[f"option:{opt_name}"] = opt_value or "true"
        for key, attr in _WHEN_LISTS.items():
            if key in cond:
                getattr(overlay, attr).extend(_strings(shown, f"{where} [[when]] {key}", cond[key]))
        target.overlays.append(overlay)
    return target
