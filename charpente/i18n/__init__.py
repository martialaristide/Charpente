"""Message catalogue access: language selection and rendering.

The catalogue itself lives in `en.py` / `fr.py` as plain Python dicts, so it
is always shipped inside the wheel and a test can check it is complete.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional

SUPPORTED = ("en", "fr")
DEFAULT = "en"
LANG_ENV = "CHARPENTE_LANG"

# Keys every catalogue entry must have (checked by tests/test_errors_catalog.py).
ENTRY_KEYS = ("title", "message", "cause", "fix")


class _SafeDict(dict):  # type: ignore[type-arg]
    """str.format_map helper: an unknown placeholder stays visible instead of
    raising, so a rendering mistake can never hide the real error."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def current_lang() -> str:
    explicit = os.environ.get(LANG_ENV, "").strip().lower()
    if explicit[:2] in SUPPORTED:
        return explicit[:2]
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(var, "").strip().lower()
        if value[:2] in SUPPORTED:
            return value[:2]
    return DEFAULT


def _catalog(lang: str) -> Mapping[str, Mapping[str, str]]:
    if lang == "fr":
        from .fr import CATALOG
    else:
        from .en import CATALOG
    return CATALOG


def codes() -> "list[str]":
    from .en import CATALOG
    return sorted(CATALOG)


def entry(code: str, lang: Optional[str] = None) -> Optional[Mapping[str, str]]:
    return _catalog(lang or current_lang()).get(code)


def render(code: str, params: Optional[Mapping[str, Any]] = None,
           lang: Optional[str] = None, field: str = "message") -> str:
    """The text of `field` for `code`, with `{placeholders}` filled from
    `params`. Falls back to English, then to a generic line -- never raises."""
    chosen = lang or current_lang()
    data: Optional[Mapping[str, str]] = _catalog(chosen).get(code) or _catalog(DEFAULT).get(code)
    if data is None:
        return f"Unknown error {code}" if field == "message" else ""
    template = data.get(field) or _catalog(DEFAULT).get(code, {}).get(field, "")
    return template.format_map(_SafeDict(params or {}))


def label(key: str, lang: Optional[str] = None) -> str:
    """Small UI words ('Cause', 'Fix', ...) used when printing an error."""
    chosen = lang or current_lang()
    table: Dict[str, Dict[str, str]] = {
        "cause": {"en": "Cause", "fr": "Cause"},
        "fix": {"en": "Fix", "fr": "Correction"},
        "more": {"en": "More", "fr": "Détails"},
        "error": {"en": "error", "fr": "erreur"},
        "unknown_code": {"en": "Unknown error code", "fr": "Code d'erreur inconnu"},
    }
    return table.get(key, {}).get(chosen) or table.get(key, {}).get("en", key)
