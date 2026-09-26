"""Budgets: limits a build must stay under (binary size, build time), checked after `charpente build`.

Declared in the workspace file:

    ws.budget(build_time="90s", total_size="40MB")      # the whole build
    t.budget(size="2MB")                                # the output of one target (a program, a library, a firmware image)

A budget that is exceeded fails the build (exit code 1) and emits `budget.exceeded`; `--no-budget` turns the check off. Sizes are of the file the
build produced (a stripped Release build is what mobile and XR budgets are about); a target that was not built in this run is not measured.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from .dsl.model import Workspace
from .errors import ChError
from .units import human_duration, human_size, parse_duration, parse_size

TARGET_KEYS = ("size",)
WORKSPACE_KEYS = ("build_time", "total_size")


def parse_target_budget(values: Mapping[str, Any]) -> Dict[str, int]:
    """`t.budget(size="2MB")` -> {"size": bytes}. Unknown keys are errors: a typo must not silently mean "no budget"."""
    out: Dict[str, int] = {}
    for key, value in values.items():
        if key not in TARGET_KEYS:
            raise ChError("CH1026", detail=f"unknown target budget {key!r} (known: {', '.join(TARGET_KEYS)})")
        if value is None:
            continue
        try:
            out[key] = value if isinstance(value, int) and not isinstance(value, bool) else parse_size(value)
        except ChError as exc:
            raise ChError("CH1026", detail=exc.message) from exc
        if out[key] <= 0:
            raise ChError("CH1026", detail=f"{key} must be greater than zero")
    return out


def parse_workspace_budget(values: Mapping[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for key, value in values.items():
        if key not in WORKSPACE_KEYS:
            raise ChError("CH1026", detail=f"unknown workspace budget {key!r} (known: {', '.join(WORKSPACE_KEYS)})")
        if value is None:
            continue
        try:
            out[key] = float(parse_duration(value)) if key == "build_time" else float(value if isinstance(value, int) and not isinstance(value, bool) else parse_size(value))
        except ChError as exc:
            raise ChError("CH1026", detail=exc.message) from exc
        if out[key] <= 0:
            raise ChError("CH1026", detail=f"{key} must be greater than zero")
    return out


@dataclass(frozen=True)
class Finding:
    scope: str            # "workspace" or a target name
    kind: str             # "size", "build_time", "total_size"
    limit: float
    actual: float

    @property
    def ok(self) -> bool:
        return self.actual <= self.limit

    def describe(self) -> str:
        if self.kind == "build_time":
            limit, actual = human_duration(self.limit), human_duration(self.actual)
        else:
            limit, actual = human_size(int(self.limit)), human_size(int(self.actual))
        what = {"size": "size", "build_time": "build time", "total_size": "total size"}[self.kind]
        verdict = "within" if self.ok else "OVER"
        return f"{self.scope}: {what} {actual} ({verdict} the budget of {limit})"


def evaluate(workspace: Workspace, outputs: Mapping[str, Path], duration: float,
             size_of: Callable[[Path], Optional[int]] = lambda p: p.stat().st_size if p.is_file() else None) -> List[Finding]:
    """Findings for every budget that can be measured: target sizes of what was built, the build time, the total size of the built outputs."""
    findings: List[Finding] = []
    total = 0
    measured_any = False
    for name, target in workspace.targets.items():
        path = outputs.get(name)
        size = size_of(path) if path is not None else None
        if size is not None:
            total += size
            measured_any = True
        limit = target.budgets.get("size")
        if limit is not None and size is not None:
            findings.append(Finding(name, "size", float(limit), float(size)))
    limits = workspace.budgets
    if "build_time" in limits:
        findings.append(Finding("workspace", "build_time", limits["build_time"], duration))
    if "total_size" in limits and measured_any:
        findings.append(Finding("workspace", "total_size", limits["total_size"], float(total)))
    return findings
