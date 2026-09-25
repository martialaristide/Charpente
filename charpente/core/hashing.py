"""Content hashing for action keys and the cache (ADR 0004).

BLAKE3 when the optional `blake3` package is installed, otherwise
`hashlib.blake2b(digest_size=32)`. Every digest carries its algorithm as a
prefix (`b3:` / `b2:`): two machines with different algorithms never mistake
one another's keys, a shared cache simply misses.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Callable, Union

Part = Union[str, bytes]

HASH_ENV = "CHARPENTE_HASH"  # "blake2" forces the standard-library fallback


_SELECTED: "dict[str, tuple[str, Callable[[], Any]]]" = {}


def _select() -> "tuple[str, Callable[[], Any]]":
    """(prefix, factory). Cached per value of CHARPENTE_HASH, so tests can flip it."""
    forced = os.environ.get(HASH_ENV, "").lower()
    cached = _SELECTED.get(forced)
    if cached is not None:
        return cached
    chosen: "tuple[str, Callable[[], Any]]"
    if forced != "blake2":
        try:
            import blake3  # type: ignore[import-not-found,unused-ignore]

            chosen = ("b3", blake3.blake3)
        except ImportError:
            chosen = ("b2", lambda: hashlib.blake2b(digest_size=32))
    else:
        chosen = ("b2", lambda: hashlib.blake2b(digest_size=32))
    _SELECTED[forced] = chosen
    return chosen


def algorithm() -> str:
    """'b3' or 'b2'."""
    return _select()[0]


def new_hasher() -> Any:
    return _select()[1]()


def digest_bytes(data: bytes) -> str:
    prefix, factory = _select()
    h = factory()
    h.update(data)
    return f"{prefix}:{h.hexdigest()}"


def digest_parts(*parts: Part) -> str:
    """Digest of a sequence of strings/bytes. Each part is length-prefixed, so
    `("ab", "c")` and `("a", "bc")` can never collide."""
    prefix, factory = _select()
    h = factory()
    for part in parts:
        raw = part.encode("utf-8") if isinstance(part, str) else part
        h.update(len(raw).to_bytes(8, "little"))
        h.update(raw)
    return f"{prefix}:{h.hexdigest()}"


def digest_file(path: Union[str, Path], chunk: int = 1 << 20) -> str:
    prefix, factory = _select()
    h = factory()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            h.update(block)
    return f"{prefix}:{h.hexdigest()}"


def short(digest: str, n: int = 12) -> str:
    """Human-friendly prefix for messages ('b3:1a2b3c4d5e6f')."""
    head, _, rest = digest.partition(":")
    return f"{head}:{rest[:n]}" if rest else digest[:n]
