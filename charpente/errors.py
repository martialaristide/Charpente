"""User-facing errors with stable codes.

Every error the user can meet is a `ChError` carrying a code (`CH1001`,
`CH3002`...). The text is rendered from the catalogue in the user's language;
`charpente explain CHxxxx` prints the long explanation.

Compatibility classes (`ChValueError`, `ChRuntimeError`, `ChFileNotFoundError`)
exist so code written against v0.1.0 -- which raised `ValueError`,
`RuntimeError`, `FileNotFoundError` -- keeps catching what it always caught.
"""
from __future__ import annotations

from typing import Any, Optional

from . import i18n


class ChError(Exception):
    """An error with a stable code, a localised message and a suggested fix."""

    code: str
    params: "dict[str, Any]"

    def __init__(self, code: str, /, **params: Any) -> None:
        self.code = code
        self.params = params
        # args[0] is the English text: stable for logs, pickling and `repr`.
        super().__init__(i18n.render(code, params, lang="en"))

    @property
    def message(self) -> str:
        return i18n.render(self.code, self.params)

    @property
    def cause_text(self) -> str:
        return i18n.render(self.code, self.params, field="cause")

    @property
    def fix(self) -> str:
        return i18n.render(self.code, self.params, field="fix")

    def __str__(self) -> str:
        return self.message

    def format(self, verbose: bool = True) -> str:
        """Multi-line rendering for the terminal."""
        lines = [f"[{self.code}] {self.message}"]
        if verbose:
            fix = self.fix
            if fix:
                lines.append(f"  {i18n.label('fix')}: {fix}")
            lines.append(f"  {i18n.label('more')}: charpente explain {self.code}")
        return "\n".join(lines)


class ChValueError(ChError, ValueError):
    pass


class ChRuntimeError(ChError, RuntimeError):
    pass


class ChFileNotFoundError(ChError, FileNotFoundError):
    # OSError.__new__/__init__ would try to interpret the arguments as
    # (errno, strerror) and reject keyword parameters; bypass both.
    def __new__(cls, code: str, /, **params: Any) -> "ChFileNotFoundError":
        return FileNotFoundError.__new__(cls, code)

    def __init__(self, code: str, /, **params: Any) -> None:
        ChError.__init__(self, code, **params)


def describe(code: str, lang: Optional[str] = None) -> str:
    """Long-form explanation used by `charpente explain`."""
    ent = i18n.entry(code, lang)
    if ent is None:
        return ""
    parts = [f"{code} -- {ent['title']}", "", ent["message"], ""]
    parts.append(f"{i18n.label('cause', lang)}: {ent['cause']}")
    parts.append(f"{i18n.label('fix', lang)}: {ent['fix']}")
    extra = ent.get("explain", "")
    if extra:
        parts += ["", extra]
    return "\n".join(parts)
