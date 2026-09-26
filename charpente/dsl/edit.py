"""Small, careful edits of a `.charpente` file and of the saved-options file, for tools (Studio, `kit add`) that change a project.

Nothing here executes the file: edits are text insertions next to a recognisable line, so the rest of the file (comments, formatting,
custom code) is untouched. When the line to anchor on is not found the edit is refused with an error that says what to do by hand.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Mapping

from .. import _toml
from ..errors import ChError

OPTIONS_FILE = Path(".charpente") / "options.toml"
_WITH = re.compile(r"^(?P<indent>[ \t]*)with\s+Workspace\([^\n]*\)\s+as\s+(?P<var>\w+)\s*:[ \t]*(?:#[^\n]*)?$", re.MULTILINE)


def add_workspace_call(text: str, method: str, value: str) -> str:
    """Insert `ws.<method>("<value>")` right after the `with Workspace(...) as ws:` line; unchanged when already present."""
    if re.search(rf"\.{re.escape(method)}\(\s*[\"']{re.escape(value)}[\"']\s*\)", text):
        return text
    match = _WITH.search(text)
    if not match:
        raise ChError("CH4005", usage=f'No `with Workspace(...) as ws:` line to add ws.{method}("{value}") to; add it by hand.')
    inner = match.group("indent") + "    "
    quoted = json.dumps(value)
    return text[:match.end()] + f"\n{inner}{match.group('var')}.{method}({quoted})" + text[match.end():]


def remove_requirement(text: str, spec: str) -> str:
    """Remove a `ws.requires("spec")` line that holds exactly that one spec (a call listing several is left alone: edit it by hand)."""
    pattern = re.compile(rf"^[ \t]*\w+\.requires\(\s*[\"']{re.escape(spec)}[\"']\s*\)[ \t]*\n?", re.MULTILINE)
    if not pattern.search(text):
        raise ChError("CH4005", usage=f'No line `ws.requires("{spec}")` on its own; remove the package by hand.')
    return pattern.sub("", text, count=1)


def load_saved_options(root: Path) -> Dict[str, str]:
    """`.charpente/options.toml` -> {name: value as text}. Missing file: empty. Values are booleans, integers or strings."""
    path = root / OPTIONS_FILE
    if not path.is_file():
        return {}
    try:
        data = _toml.load_file(path)
    except (OSError, _toml.TOMLDecodeError) as exc:
        raise ChError("CH4005", usage=f"{path} is not a valid options file ({exc}); fix or delete it.") from exc
    table = data.get("options", {})
    out: Dict[str, str] = {}
    for name, value in table.items():
        out[str(name)] = ("true" if value else "false") if isinstance(value, bool) else str(value)
    return out


def _toml_value(text: str) -> str:
    if text in ("true", "false"):
        return text
    if re.fullmatch(r"-?\d+", text):
        return text
    return json.dumps(text)                                     # a JSON string is a valid TOML basic string


def render_saved_options(values: Mapping[str, str]) -> str:
    lines = ["# Written by Charpente Studio. `--opt name=value` on the command line overrides these.", "[options]"]
    for name in sorted(values):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name):
            raise ChError("CH4005", usage=f"{name!r} is not a valid option name")
        lines.append(f"{name} = {_toml_value(values[name])}")
    return "\n".join(lines) + "\n"


def save_options(root: Path, values: Mapping[str, str]) -> Path:
    path = root / OPTIONS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_saved_options(values), encoding="utf-8")
    return path
