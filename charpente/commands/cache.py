"""`charpente cache stats|gc|clear|dir` -- the content cache shared by all workspaces."""
from __future__ import annotations

import argparse
import re
from typing import List

from ..core.cache import LocalCache
from ..errors import ChError

_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgt]?)b?\s*$", re.IGNORECASE)
_UNITS = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4}


def parse_size(text: str) -> int:
    """'500MB', '2g', '1024' -> bytes."""
    match = _SIZE_RE.match(text)
    if not match:
        raise ChError("CH4005", usage=f"Not a size: {text!r} (examples: 500MB, 2G, 1048576)")
    return int(float(match.group(1)) * _UNITS[match.group(2).lower()])


def human(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente cache", description="Inspect and maintain the build cache.")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("stats", help="Entries, files and size")
    sub.add_parser("dir", help="Print the cache directory")
    sub.add_parser("clear", help="Delete everything in the cache")
    gc = sub.add_parser("gc", help="Delete the least recently used files until the cache fits")
    gc.add_argument("--max-size", default="5GB", help="Target size (default: 5GB)")
    parsed = parser.parse_args(args)

    cache = LocalCache()
    if parsed.action == "dir":
        print(cache.root)
    elif parsed.action == "stats":
        s = cache.stats()
        print(f"{cache.root}\n  {s.entries} entries, {s.blobs} files, {human(s.bytes)}")
    elif parsed.action == "clear":
        cache.clear()
        print(f"Cleared {cache.root}")
    elif parsed.action == "gc":
        freed = cache.gc(parse_size(parsed.max_size))
        print(f"Freed {human(freed)}; now {human(cache.stats().bytes)}.")
    return 0
