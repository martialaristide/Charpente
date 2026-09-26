"""The quality gate's data: levels, findings, check results and the context a check runs in."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..core import process

LEVELS = ("rapide", "standard", "strict")           # the spec's French names stay the canonical ones
LEVEL_ALIASES = {"fast": "rapide", "quick": "rapide", "rapide": "rapide", "standard": "standard", "strict": "strict"}

PASSED, FAILED, SKIPPED, FIXED = "passed", "failed", "skipped", "fixed"


def normalise_level(text: str) -> str:
    try:
        return LEVEL_ALIASES[text.strip().lower()]
    except KeyError:
        raise ValueError(f"unknown level {text!r} (use {', '.join(LEVELS)})") from None


def level_at_least(level: str, minimum: str) -> bool:
    return LEVELS.index(level) >= LEVELS.index(minimum)


@dataclass(frozen=True)
class Finding:
    """One located problem. Feeds `diagnostic.emitted` events, CI annotations and the editor's problems panel."""

    message: str
    file: Optional[str] = None          # relative to the workspace root, forward slashes
    line: Optional[int] = None
    column: Optional[int] = None
    severity: str = "error"             # error | warning | note
    code: Optional[str] = None
    fix: Optional[str] = None


@dataclass
class CheckResult:
    name: str
    status: str                          # passed | failed | skipped | fixed
    findings: List[Finding] = field(default_factory=list)
    message: str = ""
    duration: float = 0.0

    @property
    def failed(self) -> bool:
        return self.status == FAILED


@dataclass
class CheckContext:
    """What a check may use. `run` and `which` are injectable so checks can be tested without any tool installed."""

    root: Path
    level: str
    files: Optional[List[Path]] = None   # None = every file; else the changed ones (absolute paths)
    fix: bool = False
    config: Mapping[str, Any] = field(default_factory=dict)      # this check's [checks.NAME] table
    run: Callable[..., process.ProcessResult] = process.run
    which: Callable[[str], Optional[str]] = shutil.which
    platform: Optional[str] = None
    python: str = "python"

    def rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    def selected(self, suffixes: Sequence[str]) -> List[Path]:
        """Files of these suffixes (lower-case, with the dot) among the files being checked."""
        from .files import list_files

        candidates = self.files if self.files is not None else list_files(self.root)
        return [f for f in candidates if f.suffix.lower() in suffixes]

    def option(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)


class Check:
    """Base class of the built-in checks. A check has a name, the lowest level that runs it, and `run`."""

    name = ""
    level = "standard"
    description = ""
    #: When True, `--changed` narrows what it looks at; otherwise it always considers the whole project.
    per_file = False

    def run(self, ctx: CheckContext) -> CheckResult:  # pragma: no cover - interface
        raise NotImplementedError

    # helpers -------------------------------------------------------------
    def passed(self, message: str = "") -> CheckResult:
        return CheckResult(self.name, PASSED, message=message)

    def failed(self, findings: List[Finding], message: str = "") -> CheckResult:
        return CheckResult(self.name, FAILED, findings=findings, message=message)

    def skipped(self, why: str) -> CheckResult:
        return CheckResult(self.name, SKIPPED, message=why)


@dataclass
class GateResult:
    level: str
    results: List[CheckResult]
    changed_only: bool = False
    fixed: bool = False
    duration: float = 0.0
    fail_on_skipped: bool = False

    @property
    def failed(self) -> List[CheckResult]:
        return [r for r in self.results if r.failed]

    @property
    def skipped(self) -> List[CheckResult]:
        return [r for r in self.results if r.status == SKIPPED]

    @property
    def ok(self) -> bool:
        return not self.failed and not (self.fail_on_skipped and self.skipped)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level, "ok": self.ok, "changed_only": self.changed_only, "duration": round(self.duration, 3),
            "results": [{"check": r.name, "status": r.status, "message": r.message, "duration": round(r.duration, 3),
                         "findings": len(r.findings)} for r in self.results],
        }
