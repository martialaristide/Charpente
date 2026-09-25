"""Turning compiler output into structured diagnostics.

`file:line:col: error: message [-Wflag]` (GCC, Clang, Apple Clang, MinGW) and
`file(line,col): error C1234: message` (MSVC, clang-cl) are recognised. The
result feeds `diagnostic.emitted` events, which Studio makes clickable and CI
turns into annotations. Pure functions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

# A Windows drive letter ("C:\\dir\\x.cpp") must not be mistaken for the
# 'file:line' separator, hence the explicit optional drive prefix.
_GNU_RE = re.compile(
    r"^(?P<file>(?:[A-Za-z]:)?[^:\r\n]+?):(?P<line>\d+):(?:(?P<col>\d+):)?\s*"
    r"(?P<sev>fatal error|error|warning|note):\s*(?P<msg>.*?)\s*(?:\[(?P<code>-W[^\]]+)\])?$"
)
_MSVC_RE = re.compile(
    r"^(?P<file>(?:[A-Za-z]:)?[^:(\r\n]+?)\((?P<line>\d+)(?:,(?P<col>\d+))?\)\s*:\s*"
    r"(?P<sev>fatal error|error|warning|note)\s*(?P<code>[A-Z]+\d+)?\s*:\s*(?P<msg>.*?)\s*$"
)


@dataclass(frozen=True)
class Diagnostic:
    severity: str            # "error" | "warning" | "note"
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    code: Optional[str] = None


def _severity(raw: str) -> str:
    return "error" if raw in ("fatal error", "error") else raw


def parse_line(line: str) -> Optional[Diagnostic]:
    text = line.rstrip()
    match = _MSVC_RE.match(text) or _GNU_RE.match(text)
    if match is None:
        # Linker/driver messages without a location ("error: ld returned 1",
        # "undefined reference to ...") are still worth reporting.
        bare = re.match(r"^(?:[\w./+-]+:\s*)?(fatal error|error|warning):\s*(.+)$", text)
        if bare:
            return Diagnostic(severity=_severity(bare.group(1)), message=bare.group(2))
        return None
    return Diagnostic(
        severity=_severity(match.group("sev")),
        message=match.group("msg"),
        file=match.group("file").strip(),
        line=int(match.group("line")),
        column=int(match.group("col")) if match.group("col") else None,
        code=match.group("code") or None,
    )


def parse_output(text: str) -> List[Diagnostic]:
    """All diagnostics in `text`, in order. Notes attached to an error are kept
    (they carry the "candidate is:" context)."""
    found: List[Diagnostic] = []
    for line in text.splitlines():
        diag = parse_line(line)
        if diag is not None:
            found.append(diag)
    return found
