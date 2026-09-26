"""`charpente pkg audit`: check the locked packages against the OSV vulnerability
database (https://osv.dev).

Network use is explicit (you ran `audit`), and what is sent is only each
package's `purl` and version -- no source, no paths. The honest limit: OSV's
coverage of C/C++ libraries is partial (many are only tracked by commit or by
CVE feeds), so **no finding does not mean no vulnerability**; a package without
a `purl` in its recipe cannot be checked at all and is reported as such.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ..errors import ChError
from .lock import Lock
from .recipe import Recipe

OSV_URL = "https://api.osv.dev/v1/query"


@dataclass(frozen=True)
class Finding:
    package: str
    version: str
    id: str
    summary: str
    severity: str = ""
    aliases: "tuple[str, ...]" = ()


@dataclass
class AuditReport:
    findings: List[Finding]
    unchecked: List[str]          # packages that could not be checked (no purl)
    checked: int = 0


def audit(lock: Lock, recipes: Dict[str, Recipe], *, opener: Optional[Callable[..., Any]] = None,
          url: str = OSV_URL, timeout: float = 20.0) -> AuditReport:
    opener = opener or urllib.request.urlopen
    findings: List[Finding] = []
    unchecked: List[str] = []
    checked = 0
    for name in sorted(lock.packages):
        pkg = lock.packages[name]
        recipe = recipes.get(name)
        purl = recipe.purl if recipe else ""
        if not purl:
            unchecked.append(f"{name} {pkg.version}")
            continue
        body = json.dumps({"version": pkg.version, "package": {"purl": purl}}).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json", "User-Agent": "charpente"})
        try:
            with opener(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            raise ChError("CH6001", url=url, detail=str(getattr(exc, "reason", exc))) from exc
        checked += 1
        for vuln in data.get("vulns", []) or []:
            severity = ""
            for sev in vuln.get("severity", []) or []:
                severity = str(sev.get("score", ""))
                break
            findings.append(Finding(package=name, version=pkg.version, id=str(vuln.get("id", "?")),
                                    summary=str(vuln.get("summary") or vuln.get("details", ""))[:160],
                                    severity=severity, aliases=tuple(str(a) for a in vuln.get("aliases", []) or [])))
    return AuditReport(findings=findings, unchecked=unchecked, checked=checked)
