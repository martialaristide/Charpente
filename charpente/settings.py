"""The few preferences Charpente remembers between runs (`~/.charpente/settings.json`), written by `charpente setup`.

Only known keys are stored and each has a fixed set of values; an environment variable always wins over the file (`CHARPENTE_LANG` over `lang`), so a script or a CI job is never
changed by what one developer once chose. Nothing secret is ever kept here (tokens and passphrases come from the environment or a prompt, see docs/security.md).
An unreadable or hand-broken file is treated as empty: a preference must never stop a build.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

#: key -> allowed values
KEYS: Dict[str, tuple] = {"lang": ("en", "fr")}  # type: ignore[type-arg]


def path() -> Path:
    from .dsl.trust import config_dir

    return config_dir() / "settings.json"


def load() -> Dict[str, str]:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in KEYS and isinstance(v, str) and v in KEYS[k]}


def get(key: str) -> Optional[str]:
    return load().get(key)


def set_value(key: str, value: str) -> None:
    """Remember `key = value`. Raises ValueError for an unknown key or a value outside the allowed set."""
    if key not in KEYS:
        raise ValueError(f"unknown setting {key!r} (known: {', '.join(KEYS)})")
    if value not in KEYS[key]:
        raise ValueError(f"{value!r} is not valid for {key!r} (choose from {', '.join(KEYS[key])})")
    current = load()
    current[key] = value
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, target)                                      # atomic: a reader never sees a half-written file
