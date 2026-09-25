"""Reading the build's own data for advice: which headers are expensive, and
what a finished build tells the developer. Pure functions over records/results.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .state import ActionRecord

#: A header change that rebuilt at least this many files deserves a hint.
WIDE_HEADER_THRESHOLD = 20


@dataclass(frozen=True)
class HeaderCost:
    path: str
    includers: int
    rebuild_seconds: float     # total time of the compilations that would rerun if it changed


def header_costs(records: Iterable[Tuple[str, ActionRecord]]) -> List[HeaderCost]:
    """Per header: how many compilations read it and how long they took last
    time. Sorted by rebuild cost, most expensive first."""
    includers: Dict[str, int] = {}
    seconds: Dict[str, float] = {}
    for _aid, record in records:
        for header in record.deps:
            includers[header] = includers.get(header, 0) + 1
            seconds[header] = seconds.get(header, 0.0) + record.duration
    costs = [HeaderCost(h, includers[h], seconds[h]) for h in includers]
    return sorted(costs, key=lambda c: (-c.rebuild_seconds, -c.includers, c.path))


@dataclass(frozen=True)
class Hint:
    code: str
    message: str
    detail: Mapping[str, object]


def hints_from_reasons(reasons_by_action: Mapping[str, List[str]], root: Optional[Path] = None) -> List[Hint]:
    """Advice from *why* the actions of a build ran (the reasons the engine gave)."""
    header_hits: Dict[str, int] = {}
    argv_changed = 0
    for reasons in reasons_by_action.values():
        for reason in reasons:
            if reason.startswith("header changed: "):
                name = reason[len("header changed: "):]
                header_hits[name] = header_hits.get(name, 0) + 1
            elif reason.startswith("command line changed"):
                argv_changed += 1
                break
    hints: List[Hint] = []
    for name, count in sorted(header_hits.items(), key=lambda kv: -kv[1]):
        if count >= WIDE_HEADER_THRESHOLD:
            hints.append(Hint(
                "HINT001",
                f"{count} files were recompiled because {name} changed. A header included this widely is "
                f"expensive to touch: consider forward declarations, splitting it, or a precompiled header. "
                f"`charpente headers` ranks your headers by rebuild cost.",
                {"header": name, "files": count}))
    if argv_changed >= WIDE_HEADER_THRESHOLD:
        hints.append(Hint(
            "HINT002",
            f"{argv_changed} files were recompiled because the compiler command line changed "
            f"(a flag, define or include path). Changing target-wide settings rebuilds everything in the target.",
            {"files": argv_changed}))
    return hints
