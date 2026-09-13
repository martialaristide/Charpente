"""Consent before executing a .charpente file.

A .charpente file is plain Python, exec()'d with no sandbox (see loader.py)
-- that is a deliberate design choice (a native DSL, not a restricted
config format), not an oversight. This module does not change that; it
makes sure the user is told, once per file per content, before it happens.

Trust is keyed by content hash, stored under the user's config directory
(~/.charpente/trusted_files.json). Editing a trusted file asks again.
CHARPENTE_TRUST_ALL=1 skips the check entirely (CI).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Optional

TRUST_ALL_ENV = "CHARPENTE_TRUST_ALL"


class TrustRequiredError(Exception):
    """The file isn't trusted and this session can't ask (non-interactive,
    no bypass)."""


class TrustDeniedError(Exception):
    """The user was asked and said no."""


def config_dir() -> Path:
    override = os.environ.get("CHARPENTE_CONFIG_DIR") or os.environ.get("CHARPENTE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
    else:
        base = Path.home()
    return base / ".charpente"


def _store_path() -> Path:
    return config_dir() / "trusted_files.json"


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_store() -> dict:
    p = _store_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_store(store: dict) -> None:
    p = _store_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass  # Best effort: worst case, this file gets asked about again next time.


def _trust_all_requested() -> bool:
    return os.environ.get(TRUST_ALL_ENV, "").strip().lower() in ("1", "true", "yes")


def is_trusted(path: Path) -> bool:
    store = _load_store()
    return store.get(str(path.resolve())) == _hash_file(path)


def trust(path: Path) -> None:
    store = _load_store()
    store[str(path.resolve())] = _hash_file(path)
    _save_store(store)


def _interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def ensure_trusted(path: Path, *, kind: str = "workspace", prompt=None) -> None:
    """Raise if `path` cannot be run without asking, and there's nobody to
    ask. `prompt`, if given, is a callable(question: str) -> str used
    instead of `input()` (dependency injection for tests)."""
    if _trust_all_requested():
        return
    if is_trusted(path):
        return

    label = {"workspace": "Charpente workspace file", "include": "included .charpente file"}.get(
        kind, "Charpente file"
    )

    if not _interactive() and prompt is None:
        raise TrustRequiredError(
            f"Refusing to run this {label} without confirmation: {path}\n"
            f"  A .charpente file executes as unrestricted Python code. This "
            f"session cannot ask for confirmation (non-interactive).\n"
            f"  Fix: run `charpente` once interactively to approve it, or "
            f"set {TRUST_ALL_ENV}=1 in this environment (CI) if you trust "
            f"the source of this repository."
        )

    ask = prompt or (lambda q: input(q))
    print(f"\n! {label}: {path}")
    print("  This file will execute as unrestricted Python code (not a sandbox).")
    answer = ask("  Trust and run it? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        raise TrustDeniedError(f"Execution declined by user: {path}")
    trust(path)
