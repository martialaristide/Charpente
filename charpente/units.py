"""Sizes and durations as people write them ("2MB", "90s", "1h30m") and as they are shown."""
from __future__ import annotations

import re

from .errors import ChError

_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgt]?)i?b?\s*$", re.IGNORECASE)
_UNITS = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4}
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|s|m|h)")
_SECONDS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_size(text: str) -> int:
    """'500MB', '2g', '1.5 KiB', '1024' -> bytes."""
    match = _SIZE_RE.match(str(text))
    if not match:
        raise ChError("CH4005", usage=f"Not a size: {text!r} (examples: 500MB, 2G, 1048576)")
    return int(float(match.group(1)) * _UNITS[match.group(2).lower()])


def parse_duration(text: "str | int | float") -> float:
    """'90s', '2m', '1h30m', '500ms', or a bare number of seconds -> seconds."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        if text < 0:
            raise ChError("CH4005", usage=f"Not a duration: {text!r}")
        return float(text)
    raw = str(text).strip().lower()
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return float(raw)
    rest = _DURATION_PART.sub("", raw).strip()
    parts = _DURATION_PART.findall(raw)
    if not parts or rest:
        raise ChError("CH4005", usage=f"Not a duration: {text!r} (examples: 90s, 2m, 1h30m, 500ms)")
    return sum(float(number) * _SECONDS[unit] for number, unit in parts)


def human_size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"


def human_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)} min {rest:.0f} s"
