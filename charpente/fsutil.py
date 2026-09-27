"""Small file helpers that behave the same on every supported Python (3.9 and later)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union


def write_text(path: Union[str, Path], text: str, *, newline: Optional[str] = None, encoding: str = "utf-8") -> int:
    """`Path.write_text` with control over line endings.

    `Path.write_text(..., newline=...)` only exists from Python 3.10, and Charpente supports 3.9: there it raised TypeError, which surfaced as an internal error (exit
    code 70) in `init --template`, `pkg`, `generate`, the Git hooks and the saving of files in Studio. `newline=""` writes `text` exactly as given; a newline of LF writes LF.
    """
    with open(path, "w", encoding=encoding, newline=newline) as handle:
        return handle.write(text)
