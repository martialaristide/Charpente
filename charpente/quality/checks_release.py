"""Strict-level checks about what you ship: dependency vulnerabilities, licenses, the SBOM."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Set

from ..core import download
from ..errors import ChError
from ..pkg import audit as audit_mod
from ..pkg import lock as lock_mod
from ..pkg.store import PackageStore
from .model import PASSED, Check, CheckContext, CheckResult, Finding

DEFAULT_ALLOWED = ("MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib", "BSL-1.0", "MPL-2.0", "Unlicense",
                   "CC0-1.0", "0BSD", "Python-2.0", "PSF-2.0")


def _lock_and_recipes(ctx: CheckContext) -> Any:
    """(lock, recipes) of the project in `ctx.root`, or None when it has no lock file."""
    from ..commands._common import load
    from ..commands.pkg import _recipes
    from ..workspace_finder import find_workspace_file

    lock = lock_mod.load(ctx.root)
    if lock is None or not lock.packages:
        return None
    workspace = load(str(find_workspace_file(start_dir=ctx.root)), None, materialize_packages=False)
    return lock, _recipes(workspace, PackageStore())


def license_terms(expression: str) -> Set[str]:
    """The identifiers in an SPDX expression (`MIT OR Apache-2.0` -> {MIT, Apache-2.0}); a plain id is itself."""
    cleaned = expression.replace("(", " ").replace(")", " ")
    return {t for t in cleaned.split() if t.upper() not in ("OR", "AND", "WITH") and t}


class AuditCheck(Check):
    name = "audit"
    level = "strict"
    description = "No known vulnerabilities in locked dependencies (OSV; sends only package URLs and versions)."

    def run(self, ctx: CheckContext) -> CheckResult:
        found = _lock_and_recipes(ctx)
        if found is None:
            return self.skipped("no locked dependencies")
        if download.offline():
            return self.skipped("offline mode (CHARPENTE_OFFLINE) forbids the vulnerability lookup")
        lock, recipes = found
        try:
            report = audit_mod.audit(lock, recipes)
        except ChError as exc:
            return self.skipped(f"the vulnerability database could not be reached: {exc}")
        findings = [Finding(f"{f.package} {f.version}: {f.id} {f.summary}".strip(), "charpente.lock", severity="error",
                            code=f.id, fix="upgrade the package (`charpente pkg install --update`) or pin a fixed version")
                    for f in report.findings]
        if findings:
            return self.failed(findings, f"{len(findings)} known vulnerabilit{'y' if len(findings) == 1 else 'ies'}")
        note = f"{report.checked} package(s) checked" + (f"; not checkable: {', '.join(report.unchecked)}" if report.unchecked else "")
        return self.passed(note)


class LicensesCheck(Check):
    name = "licenses"
    level = "strict"
    description = "Every dependency's license is on the project's allow-list."

    def run(self, ctx: CheckContext) -> CheckResult:
        found = _lock_and_recipes(ctx)
        if found is None:
            return self.skipped("no locked dependencies")
        lock, recipes = found
        allowed = set(ctx.option("allow", DEFAULT_ALLOWED))
        findings: List[Finding] = []
        for name in sorted(lock.packages):
            recipe = recipes.get(name)
            if recipe is None:
                findings.append(Finding(f"{name}: recipe not available, license unknown", "charpente.lock",
                                        severity="error", code="license-unknown"))
                continue
            terms = license_terms(recipe.license)
            # An OR expression is satisfied by any allowed alternative; AND needs all of them.
            needs_all = " AND " in recipe.license.upper()
            ok = terms <= allowed if needs_all else bool(terms & allowed)
            if not ok:
                findings.append(Finding(f"{name} {recipe.version} is licensed {recipe.license}, not on the allow-list",
                                        "charpente.lock", severity="error", code="license",
                                        fix="allow it under [checks.licenses] allow = [...] if your policy permits, or replace the package"))
        return self.failed(findings, f"{len(findings)} license problem(s)") if findings else self.passed(
            f"{len(lock.packages)} package(s), all allowed")


class SbomCheck(Check):
    name = "sbom"
    level = "strict"
    description = "A Software Bill of Materials (SPDX and CycloneDX) can be produced for the release."

    def run(self, ctx: CheckContext) -> CheckResult:
        from .checks_build import charpente

        out = ctx.root / "dist"
        result = charpente(ctx, ["sbom", "--output", str(out)])
        if result.returncode != 0:
            return self.failed([Finding((result.output.splitlines() or ["sbom failed"])[-1], severity="error", code="sbom")],
                               "the SBOM could not be produced")
        files: Dict[str, Any] = {}
        for path in sorted(out.glob("*.spdx.json")) + sorted(out.glob("*.cdx.json")):
            try:
                files[path.name] = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                return self.failed([Finding(f"{path.name} is not valid JSON", f"dist/{path.name}", severity="error", code="sbom")])
        return CheckResult(self.name, PASSED, message="wrote " + ", ".join(sorted(files)))
