"""Reproducibility checks: compare what two builds of the same sources produced, and say why they differ."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class Difference:
    name: str
    size_a: int
    size_b: int
    first_offset: Optional[int]
    hints: List[str] = field(default_factory=list)


def first_difference(a: bytes, b: bytes) -> Optional[int]:
    """Index of the first differing byte (the shorter length when one is a prefix of the other), None when equal."""
    if a == b:
        return None
    limit = min(len(a), len(b))
    low, high = 0, limit
    # Common prefix by bisection over slices: O(n log n) worst case, no Python loop over bytes.
    if a[:limit] == b[:limit]:
        return limit
    while low < high:
        mid = (low + high) // 2
        if a[low:mid + 1] == b[low:mid + 1]:
            low = mid + 1
        else:
            high = mid
    return low


_TIMESTAMPISH = re.compile(rb"\b(?:20[12]\d)[-/]?(?:0[1-9]|1[0-2])[-/]?(?:0[1-9]|[12]\d|3[01])\b")


def explain(name: str, a: bytes, b: bytes, roots: Sequence[str]) -> Difference:
    """A `Difference` with plausible causes: an embedded build path, an embedded date, or a size change."""
    hints: List[str] = []
    for root in roots:
        for variant in {root, root.replace("\\", "/"), root.replace("/", "\\")}:
            if variant and variant.encode("utf-8", "ignore") in (a + b):
                hints.append(f"the output contains the build folder path {variant!r} (a path leaks in: debug info, __FILE__, an assert message)")
                break
    if a.count(b"\x00") != b.count(b"\x00") and len(a) == len(b):
        hints.append("same size but different padding: probably a timestamp or an identifier in a header")
    if _TIMESTAMPISH.search(a) or _TIMESTAMPISH.search(b):
        hints.append("the output contains something that looks like a date (__DATE__, a build timestamp)")
    if len(a) != len(b):
        hints.append("the sizes differ: a path of a different length is embedded, or the code itself differs")
    return Difference(name, len(a), len(b), first_difference(a, b), hints)


@dataclass
class Report:
    identical: List[str] = field(default_factory=list)
    different: List[Difference] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.different and not self.missing and bool(self.identical)


def compare_builds(outputs_a: Mapping[str, Path], outputs_b: Mapping[str, Path], roots: Sequence[str]) -> Report:
    """Compare the outputs of two builds by target name. Files are compared by SHA-256; only differing files are read in full to explain."""
    report = Report()
    for name in sorted(set(outputs_a) | set(outputs_b)):
        path_a, path_b = outputs_a.get(name), outputs_b.get(name)
        if path_a is None or path_b is None or not path_a.is_file() or not path_b.is_file():
            report.missing.append(name)
        elif sha256_file(path_a) == sha256_file(path_b):
            report.identical.append(name)
        else:
            report.different.append(explain(name, path_a.read_bytes(), path_b.read_bytes(), roots))
    return report


def outputs_from_events(lines: Sequence[str]) -> Dict[str, str]:
    """Target name -> its main output (the linked program or the archive) from the JSON lines of `charpente build --output jsonl`."""
    import json

    found: Dict[str, str] = {}
    for line in lines:
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        payload = event.get("payload", {})
        if event.get("type") in ("action.finished", "action.cache_hit") and payload.get("kind") in ("link", "archive") and payload.get("outputs"):
            found[str(payload["target"])] = str(payload["outputs"][0])
    return found
