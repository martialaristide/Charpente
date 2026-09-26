"""The quality gate: choose the checks for a level, run them, report, remember.

`charpente check` is what Git hooks, `charpente commit`/`push`/`pr`/`release` and CI all call, so a check that passes
on your machine is the check CI runs. Configuration is `.charpente/quality.toml`, versioned with the project.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .. import _toml
from ..core import process
from ..errors import ChError
from ..events import EventBus
from . import files as files_mod
from .checks_build import (
    BuildCheck,
    CoverageCheck,
    CppcheckCheck,
    PlatformsCheck,
    SanitizersCheck,
    TestsCheck,
    TidyCheck,
    WarningsCheck,
)
from .checks_release import AuditCheck, LicensesCheck, SbomCheck
from .checks_static import DslLintCheck, FileSizeCheck, FormatCheck, SecretsCheck
from .model import (
    FAILED,
    FIXED,
    LEVELS,
    PASSED,
    SKIPPED,
    Check,
    CheckContext,
    CheckResult,
    Finding,
    GateResult,
    level_at_least,
    normalise_level,
)

CONFIG_PATH = Path(".charpente") / "quality.toml"
RECORD_PATH = Path("build") / ".charpente" / "gate.json"
LOG_PATH = Path("build") / ".charpente" / "gate-log.json"

#: Execution order matters: the build first (it writes compile_commands.json the analyzers read).
BUILTIN_CHECKS: List[Check] = [
    BuildCheck(), FormatCheck(), DslLintCheck(), SecretsCheck(), FileSizeCheck(),
    WarningsCheck(), TidyCheck(), CppcheckCheck(), TestsCheck(),
    SanitizersCheck(), CoverageCheck(), PlatformsCheck(), AuditCheck(), LicensesCheck(), SbomCheck(),
]

DEFAULT_CONFIG = """# Charpente quality gate -- versioned with the project. `charpente check --level rapide|standard|strict`.
[gate]
level = "standard"          # what `charpente check` runs without --level
fail_on_skipped = false     # true: a check whose tool is missing counts as a failure (use it in CI)

# Every check can be tuned or switched off:  [checks.NAME]  enabled = false
[checks.file-size]
max_kb = 1024

[checks.secrets]
allow = []                  # globs of files to leave alone, e.g. ["tests/fixtures/*"]

[checks.coverage]
minimum = 70

[checks.licenses]
allow = ["MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib", "BSL-1.0", "MPL-2.0"]

[checks.platforms]
platforms = []              # e.g. ["linux-arm64", "wasm32-wasi"]: built when a toolchain is available
"""


@dataclass
class QualityConfig:
    level: str = "standard"
    fail_on_skipped: bool = False
    checks: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def for_check(self, name: str) -> Dict[str, Any]:
        return self.checks.get(name, {})

    def enabled(self, name: str) -> bool:
        return bool(self.for_check(name).get("enabled", True))


def load_config(root: Path) -> QualityConfig:
    path = root / CONFIG_PATH
    if not path.is_file():
        return QualityConfig()
    try:
        data = _toml.load_file(path)
    except (OSError, _toml.TOMLDecodeError) as exc:
        raise ChError("CH8012", path=str(CONFIG_PATH), detail=str(exc)) from exc
    gate = data.get("gate", {})
    unknown = sorted(set(data) - {"gate", "checks"})
    if unknown:
        raise ChError("CH8012", path=str(CONFIG_PATH), detail=f"unknown section(s): {', '.join(unknown)}")
    try:
        level = normalise_level(str(gate.get("level", "standard")))
    except ValueError as exc:
        raise ChError("CH8012", path=str(CONFIG_PATH), detail=str(exc)) from exc
    checks = data.get("checks", {})
    if not isinstance(checks, dict) or any(not isinstance(v, dict) for v in checks.values()):
        raise ChError("CH8012", path=str(CONFIG_PATH), detail="[checks.NAME] must be tables")
    return QualityConfig(level=level, fail_on_skipped=bool(gate.get("fail_on_skipped", False)), checks=checks)


# ------------------------------------------------------------------ external (module) checks
class ExternalCheck(Check):
    """Adapts a module's check (`run(workspace_root, files, fix)`) to the gate."""

    def __init__(self, obj: Any) -> None:
        self.obj = obj
        self.name = str(getattr(obj, "name", "external"))
        self.level = str(getattr(obj, "level", "standard"))
        self.description = str(getattr(obj, "description", ""))

    def run(self, ctx: CheckContext) -> CheckResult:
        raw = self.obj.run(ctx.root, ctx.files, ctx.fix)
        if isinstance(raw, CheckResult):
            return raw
        if isinstance(raw, bool):
            return CheckResult(self.name, PASSED if raw else FAILED)
        findings: List[Finding] = []
        for item in raw or []:
            findings.append(item if isinstance(item, Finding) else Finding(str(item)))
        return CheckResult(self.name, FAILED if findings else PASSED, findings=findings)


def all_checks(registry: Any = None) -> List[Check]:
    """The built-in checks followed by those contributed by enabled modules."""
    checks = list(BUILTIN_CHECKS)
    if registry is None:
        from ..modules.runtime import get_registry

        registry = get_registry()
    names = {c.name for c in checks}
    for extension in registry.all("quality_check"):
        if extension.name in names or isinstance(extension.obj, Check):
            continue
        names.add(extension.name)
        checks.append(ExternalCheck(extension.obj))
    return checks


def select(checks: Sequence[Check], level: str, config: QualityConfig, only: Sequence[str] = (),
           skip: Sequence[str] = ()) -> List[Check]:
    chosen = []
    for check in checks:
        if only and check.name not in only:
            continue
        if check.name in skip or not config.enabled(check.name):
            continue
        if not only and not level_at_least(level, check.level):
            continue
        chosen.append(check)
    unknown = [n for n in [*only, *skip] if n not in {c.name for c in checks}]
    if unknown:
        raise ChError("CH8012", path="--only/--skip", detail=f"no such check: {', '.join(unknown)} "
                                                              f"(known: {', '.join(c.name for c in checks)})")
    return chosen


# ------------------------------------------------------------------ running
def run_gate(root: Path, *, level: Optional[str] = None, changed: bool = False, fix: bool = False,
             only: Sequence[str] = (), skip: Sequence[str] = (), bus: Optional[EventBus] = None,
             platform: Optional[str] = None, run: Callable[..., process.ProcessResult] = process.run,
             which: Callable[[str], Optional[str]] = shutil.which, python: Optional[str] = None,
             checks: Optional[Sequence[Check]] = None, config: Optional[QualityConfig] = None,
             say: Callable[[str], None] = lambda text: None) -> GateResult:
    root = root.resolve()
    config = config or load_config(root)
    level = normalise_level(level) if level else config.level
    chosen = select(checks if checks is not None else all_checks(), level, config, only, skip)
    files: Optional[List[Path]] = None
    if changed:
        files = files_mod.changed_files(root, run, which)
        if files is None:
            say("not a Git repository (or Git is missing): checking everything")
    begun = time.monotonic()
    results: List[CheckResult] = []

    def context(check: Check, fix_now: bool) -> CheckContext:
        return CheckContext(root=root, level=level, files=files if (files is not None and check.per_file) else None,
                            fix=fix_now, config=config.for_check(check.name), run=run, which=which, platform=platform,
                            python=python or sys.executable)

    if fix:                                              # phase 1: safe automatic corrections
        for check in chosen:
            if check.name in ("format", "clang-tidy"):
                _execute(check, context(check, True), bus, say, emit_events=False)
    for check in chosen:                                 # phase 2 (or the only phase): verify
        results.append(_execute(check, context(check, False), bus, say))
    gate = GateResult(level=level, results=results, changed_only=changed and files is not None,
                      duration=time.monotonic() - begun, fail_on_skipped=config.fail_on_skipped, fixed=fix)
    if bus is not None and not gate.ok:
        why = ", ".join(r.name for r in gate.failed) or "skipped checks (fail_on_skipped)"
        bus.emit("gate.blocked", reason=why)
    return gate


def _execute(check: Check, ctx: CheckContext, bus: Optional[EventBus], say: Callable[[str], None],
             emit_events: bool = True) -> CheckResult:
    if bus is not None and emit_events:
        bus.emit("gate.check_started", check=check.name, level=ctx.level)
    begun = time.monotonic()
    try:
        result = check.run(ctx)
    except ChError as exc:
        result = CheckResult(check.name, FAILED, [Finding(str(exc), severity="error", code=exc.code)], str(exc))
    except Exception as exc:                            # a crashing check is a failed check, never a silent pass
        result = CheckResult(check.name, FAILED, [Finding(f"the check crashed: {type(exc).__name__}: {exc}", severity="error",
                                                          code="check-crashed")], "the check crashed")
    result.duration = time.monotonic() - begun
    if bus is not None and emit_events:
        for finding in result.findings:
            bus.emit("diagnostic.emitted", file=finding.file, line=finding.line, column=finding.column,
                     severity=finding.severity, code=finding.code, message=finding.message, action=check.name,
                     fix=finding.fix)
        if result.status == FAILED:
            bus.emit("gate.check_failed", check=check.name, reason=result.message or "failed")
        elif result.status != SKIPPED:
            bus.emit("gate.check_passed", check=check.name, duration=result.duration)
    return result


# ------------------------------------------------------------------ remembering
def write_record(root: Path, result: GateResult, tree: Optional[str] = None) -> None:
    """Store the last gate run (for `charpente status`) and, when the Git tree is known, that this tree passed."""
    record = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **result.to_dict()}
    try:
        (root / RECORD_PATH).parent.mkdir(parents=True, exist_ok=True)
        (root / RECORD_PATH).write_text(json.dumps(record, indent=1), encoding="utf-8")
        if tree and result.ok:
            remember_tree(root, tree, result.level)
    except OSError:
        pass


def remember_tree(root: Path, tree: str, level: str) -> None:
    """Note that the Git tree `tree` passed the gate at `level` (what `charpente pr` checks commits against)."""
    try:
        log = read_log(root)
        log[tree] = {"level": level, "when": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        (root / LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
        (root / LOG_PATH).write_text(json.dumps(log, indent=1, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def read_record(root: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads((root / RECORD_PATH).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def read_log(root: Path) -> Dict[str, Any]:
    try:
        data = json.loads((root / LOG_PATH).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def index_tree(root: Path, run: Callable[..., process.ProcessResult] = process.run,
               which: Callable[[str], Optional[str]] = shutil.which) -> Optional[str]:
    """The Git tree hash of what is staged (what a commit would contain), or None."""
    out = files_mod._git(root, ["write-tree"], run, which)
    return out[0] if out else None


def render(result: GateResult) -> str:
    """The human report."""
    icons = {PASSED: "PASS", FAILED: "FAIL", SKIPPED: "SKIP", FIXED: "FIXED"}
    lines = [f"Quality gate ({result.level}{', changed files only' if result.changed_only else ''}):"]
    for r in result.results:
        lines.append(f"  [{icons.get(r.status, r.status):<5}] {r.name:<11} {r.message}".rstrip())
        for finding in r.findings[:15]:
            where = f"{finding.file}:{finding.line}" if finding.file and finding.line else (finding.file or "")
            lines.append(f"           {where + ': ' if where else ''}{finding.severity}: {finding.message}")
            if finding.fix and r.failed:
                lines.append(f"             fix: {finding.fix}")
        if len(r.findings) > 15:
            lines.append(f"           ... {len(r.findings) - 15} more")
    verdict = "OK" if result.ok else "BLOCKED"
    skipped = f", {len(result.skipped)} skipped" if result.skipped else ""
    lines.append(f"{verdict}: {len(result.results) - len(result.failed) - len(result.skipped)} passed, "
                 f"{len(result.failed)} failed{skipped} in {result.duration:.1f}s")
    if result.skipped and not result.fail_on_skipped:
        lines.append("  (skipped checks did not run: their tool or data is missing; set fail_on_skipped = true to require them)")
    return "\n".join(lines)


def levels() -> Mapping[str, str]:
    return {level: ", ".join(c.name for c in BUILTIN_CHECKS if c.level == level) for level in LEVELS}
