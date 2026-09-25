"""Validates names that become (part of) an output file path -- target and
workspace names.

Kept as its own tiny module and enforced at the dataclass boundary
(`Target.__post_init__`), not bolted on later at whichever call site
happens to build a path: a name that can't safely become a filename is
rejected the moment it's declared, not the first time some far-away
packaging code happens to concatenate it into a path.
"""
from __future__ import annotations

import re

from .errors import ChValueError

_UNSAFE_RE = re.compile(r"[\\/\x00-\x1f]")


def validate(name: str, field: str = "name") -> str:
    if not name or not name.strip():
        raise ChValueError("CH1011", field=field)
    if ".." in name:
        raise ChValueError("CH1012", field=field, name=name)
    if _UNSAFE_RE.search(name):
        raise ChValueError("CH1013", field=field, name=name)
    return name
