"""The words of the console style (banner, build lines), in English and French. Both tables have exactly the same keys and the same `{placeholders}`; a test checks it.

Kept apart from the error catalogue (`en.py` / `fr.py`, which holds `CHxxxx` entries): these are short interface phrases, not errors. The language comes from the same
resolution as everything else (`CHARPENTE_LANG`, then the remembered setting, then `LANG`).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

EN: Dict[str, str] = {
    "banner.subtitle": "Multi-platform C/C++ Build System v{version}",
    "banner.components": "Engine · Packages · Kits · Studio",
    "banner.compact.name": "C H A R P E N T E",
    "stage.loading": "Loading the workspace",
    "stage.building": "Building",
    "context.workspace": "workspace",
    "context.config": "config",
    "context.platform": "platform",
    "context.tools": "tools",
    "target.up_to_date": "up to date",
    "target.cached": "served by the cache",
    "target.failed": "build failed",
    "warnings.one": "{target}: 1 warning, see charpente build -v",
    "warnings.many": "{target}: {count} warnings, see charpente build -v",
    "result.title": "Result",
    "result.targets": "targets",
    "result.cache": "cache",
    "result.duration": "duration",
    "result.next": "next",
    "result.ok.one": "1 succeeded",
    "result.ok.many": "{n} succeeded",
    "result.failed.one": "1 failed",
    "result.failed.many": "{n} failed",
    "result.up_to_date": "{n} up to date",
    "result.cache.one": "{cached} action out of {total}",
    "result.cache.many": "{cached} actions out of {total}",
    "result.interrupted": "build interrupted",
    "result.no_targets": "nothing to build",
}

FR: Dict[str, str] = {
    "banner.subtitle": "Système de build C/C++ multiplateforme v{version}",
    "banner.components": "Moteur · Paquets · Kits · Studio",
    "banner.compact.name": "C H A R P E N T E",
    "stage.loading": "Chargement de l'espace de travail",
    "stage.building": "Construction",
    "context.workspace": "espace",
    "context.config": "config",
    "context.platform": "plateforme",
    "context.tools": "outils",
    "target.up_to_date": "à jour",
    "target.cached": "servi par le cache",
    "target.failed": "échec de la construction",
    "warnings.one": "{target} : 1 avertissement, voir charpente build -v",
    "warnings.many": "{target} : {count} avertissements, voir charpente build -v",
    "result.title": "Résultat",
    "result.targets": "cibles",
    "result.cache": "cache",
    "result.duration": "durée",
    "result.next": "suite",
    "result.ok.one": "1 réussie",
    "result.ok.many": "{n} réussies",
    "result.failed.one": "1 échec",
    "result.failed.many": "{n} échecs",
    "result.up_to_date": "{n} à jour",
    "result.cache.one": "{cached} action sur {total}",
    "result.cache.many": "{cached} actions sur {total}",
    "result.interrupted": "construction interrompue",
    "result.no_targets": "rien à construire",
}

TABLES = {"en": EN, "fr": FR}


def plural_key(lang: Optional[str], n: int) -> str:
    """`one` or `many`: French uses the singular for 0 and 1, English only for 1."""
    if lang is None:
        from . import current_lang

        lang = current_lang()
    return "one" if (n in (0, 1) if lang == "fr" else n == 1) else "many"


class _Safe(dict):  # type: ignore[type-arg]
    """A missing placeholder stays visible instead of raising (a wording slip must never break a build)."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def t(key: str, lang: Optional[str] = None, **values: Any) -> str:
    """The text for `key` in `lang` (default: the current language), with `{placeholders}` filled. An unknown key or language falls back to English, then to the key."""
    if lang is None:
        from . import current_lang

        lang = current_lang()
    template = TABLES.get(lang, EN).get(key)
    if template is None:
        template = EN.get(key, key)
    try:
        return template.format_map(_Safe(values))
    except (ValueError, IndexError):                    # a malformed template is shown as written
        return template
