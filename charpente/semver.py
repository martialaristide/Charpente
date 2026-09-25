"""Semantic versions and version constraints (`^1.2`, `~1.2.3`, `>=1,<2`, `*`).

Used for the module API compatibility check and, later, by the package manager.
Small and strict: an unparsable version or constraint is an error, never a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering
from typing import List, Optional, Tuple

from .errors import ChValueError

_VERSION_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)(?:\.(?P<minor>0|[1-9]\d*))?(?:\.(?P<patch>0|[1-9]\d*))?"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)


@total_ordering
@dataclass(frozen=True)
class Version:
    major: int
    minor: int = 0
    patch: int = 0
    pre: Tuple[str, ...] = ()

    @staticmethod
    def parse(text: str) -> "Version":
        match = _VERSION_RE.match(text.strip())
        if not match:
            raise ChValueError("CH7001", value=text)
        pre = tuple(match.group("pre").split(".")) if match.group("pre") else ()
        return Version(int(match.group("major")), int(match.group("minor") or 0),
                       int(match.group("patch") or 0), pre)

    def _key(self) -> Tuple[Tuple[int, int, int], int, Tuple[Tuple[int, object], ...]]:
        # A pre-release sorts before the release; numeric identifiers before text.
        ident = tuple((0, int(p)) if p.isdigit() else (1, p) for p in self.pre)
        return ((self.major, self.minor, self.patch), 0 if self.pre else 1, ident)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return base + ("-" + ".".join(self.pre) if self.pre else "")


@dataclass(frozen=True)
class _Clause:
    op: str
    version: Version
    #: how many components the user wrote (`^1.2` vs `^1.2.3`): matters for `~` and `=`.
    parts: int = 3

    def matches(self, v: Version) -> bool:
        if self.op == "=":
            if self.parts == 1:
                return v.major == self.version.major
            if self.parts == 2:
                return (v.major, v.minor) == (self.version.major, self.version.minor)
            return v == self.version
        if self.op == ">=":
            return v >= self.version
        if self.op == ">":
            return v > self.version
        if self.op == "<=":
            return v <= self.version
        if self.op == "<":
            return v < self.version
        if self.op == "!=":
            return v != self.version
        if self.op == "^":
            return self.version <= v < _caret_upper(self.version)
        if self.op == "~":
            return self.version <= v < _tilde_upper(self.version, self.parts)
        raise AssertionError(self.op)


def _caret_upper(v: Version) -> Version:
    """`^1.2.3` := <2.0.0; `^0.2.3` := <0.3.0; `^0.0.3` := <0.0.4 (semver caret rules)."""
    if v.major > 0:
        return Version(v.major + 1)
    if v.minor > 0:
        return Version(0, v.minor + 1)
    return Version(0, 0, v.patch + 1)


def _tilde_upper(v: Version, parts: int) -> Version:
    """`~1.2.3` := <1.3.0; `~1.2` := <1.3.0; `~1` := <2.0.0."""
    if parts == 1:
        return Version(v.major + 1)
    return Version(v.major, v.minor + 1)


@dataclass(frozen=True)
class Constraint:
    clauses: Tuple[_Clause, ...]
    text: str

    @staticmethod
    def parse(text: str) -> "Constraint":
        raw = text.strip()
        if raw in ("", "*"):
            return Constraint((), raw or "*")
        clauses: List[_Clause] = []
        for piece in raw.split(","):
            piece = piece.strip()
            match = re.match(r"^(\^|~|>=|<=|!=|>|<|=)?\s*(.+)$", piece)
            if not match:
                raise ChValueError("CH7002", value=text)
            op = match.group(1) or "^"          # a bare version means "compatible with", as in Cargo
            body = match.group(2).strip()
            if body.count(".") > 2:
                raise ChValueError("CH7002", value=text)
            try:
                version = Version.parse(body)
            except ChValueError as exc:
                raise ChValueError("CH7002", value=text) from exc
            parts = len(body.split("-")[0].split("."))
            clauses.append(_Clause(op, version, parts))
        return Constraint(tuple(clauses), raw)

    def matches(self, version: "Version | str") -> bool:
        v = Version.parse(version) if isinstance(version, str) else version
        if v.pre and not any(c.version.pre for c in self.clauses):
            return False       # a pre-release only satisfies a constraint that names one
        return all(c.matches(v) for c in self.clauses)

    def best(self, candidates: "List[str]") -> Optional[str]:
        """Highest candidate that satisfies the constraint, or None."""
        ok = [(Version.parse(c), c) for c in candidates if self.matches(c)]
        return max(ok, key=lambda pair: pair[0])[1] if ok else None

    def __str__(self) -> str:
        return self.text
