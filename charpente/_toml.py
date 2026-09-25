"""TOML parsing: the standard library's `tomllib` on Python 3.11+, the
`tomli` backport (a declared dependency) before that. Read-only."""
from __future__ import annotations

import sys
from typing import Any, Dict

if sys.version_info >= (3, 11):
    import tomllib as _toml
else:  # pragma: no cover - exercised on Python 3.9/3.10 CI legs
    import tomli as _toml

TOMLDecodeError = _toml.TOMLDecodeError


def loads(text: str) -> Dict[str, Any]:
    return _toml.loads(text)


def load_file(path: "str | bytes | Any") -> Dict[str, Any]:
    with open(path, "rb") as handle:
        return _toml.load(handle)
