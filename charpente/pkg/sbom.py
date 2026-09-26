"""Software Bills of Materials from the *real* dependency graph: the workspace and
every locked package, with versions, licences, source archives and digests.

Two formats, both JSON: SPDX 2.3 and CycloneDX 1.5. What is described is what
Charpente actually knows -- the packages it resolved and fetched, verified by
SHA-256. It does not (and cannot) discover libraries your own sources vendor by
hand or system libraries linked by name; those are outside the graph.
"""
from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict, List, Optional

from .. import _version
from .lock import Lock
from .recipe import Recipe

_SPDX_NAMESPACE = "https://charpente.dev/spdx"


def _timestamp(now: Optional[datetime.datetime] = None) -> str:
    moment = now or datetime.datetime.now(datetime.timezone.utc)
    return moment.replace(microsecond=0, tzinfo=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _spdx_id(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in ".-" else "-" for c in name)
    return f"SPDXRef-Package-{cleaned}"


def _purl(recipe: Recipe) -> str:
    return f"{recipe.purl}@{recipe.version}" if recipe.purl else ""


def spdx(workspace_name: str, workspace_version: str, lock: Lock, recipes: Dict[str, Recipe],
         *, now: Optional[datetime.datetime] = None, document_id: Optional[str] = None) -> Dict[str, Any]:
    """An SPDX 2.3 document."""
    doc_uuid = document_id or str(uuid.uuid4())
    root_id = "SPDXRef-RootPackage"
    packages: List[Dict[str, Any]] = [{
        "SPDXID": root_id, "name": workspace_name, "versionInfo": workspace_version or "unknown",
        "downloadLocation": "NOASSERTION", "filesAnalyzed": False, "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION", "copyrightText": "NOASSERTION",
        "primaryPackagePurpose": "APPLICATION",
    }]
    relationships: List[Dict[str, str]] = [{"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES",
                                            "relatedSpdxElement": root_id}]
    for name in sorted(lock.packages):
        pkg = lock.packages[name]
        recipe = recipes.get(name)
        sid = _spdx_id(f"{name}-{pkg.version}")
        entry: Dict[str, Any] = {
            "SPDXID": sid, "name": name, "versionInfo": pkg.version, "downloadLocation": pkg.source_url,
            "filesAnalyzed": False,
            "checksums": [{"algorithm": "SHA256", "checksumValue": pkg.source_sha256}],
            "licenseConcluded": "NOASSERTION", "licenseDeclared": recipe.license if recipe else "NOASSERTION",
            "copyrightText": "NOASSERTION", "primaryPackagePurpose": "LIBRARY",
        }
        if recipe and recipe.homepage:
            entry["homepage"] = recipe.homepage
        if recipe and recipe.purl:
            entry["externalRefs"] = [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                                      "referenceLocator": _purl(recipe)}]
        packages.append(entry)
        if pkg.requested_by and "workspace" in pkg.requested_by:
            relationships.append({"spdxElementId": root_id, "relationshipType": "DEPENDS_ON",
                                  "relatedSpdxElement": sid})
    from .recipe import constraint_of

    for name in sorted(lock.packages):
        for dep in lock.packages[name].dependencies:
            dep_name = constraint_of(dep)[0]
            if dep_name in lock.packages:
                relationships.append({
                    "spdxElementId": _spdx_id(f"{name}-{lock.packages[name].version}"),
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": _spdx_id(f"{dep_name}-{lock.packages[dep_name].version}")})
    return {
        "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{workspace_name}-sbom", "documentNamespace": f"{_SPDX_NAMESPACE}/{workspace_name}-{doc_uuid}",
        "creationInfo": {"created": _timestamp(now), "creators": [f"Tool: charpente-{_version.__version__}"]},
        "packages": packages, "relationships": relationships,
    }


def cyclonedx(workspace_name: str, workspace_version: str, lock: Lock, recipes: Dict[str, Recipe],
              *, now: Optional[datetime.datetime] = None, serial: Optional[str] = None) -> Dict[str, Any]:
    """A CycloneDX 1.5 document."""
    from .recipe import constraint_of

    def ref(name: str) -> str:
        return f"pkg:{name}@{lock.packages[name].version}"

    components: List[Dict[str, Any]] = []
    for name in sorted(lock.packages):
        pkg = lock.packages[name]
        recipe = recipes.get(name)
        component: Dict[str, Any] = {
            "type": "library", "bom-ref": ref(name), "name": name, "version": pkg.version,
            "hashes": [{"alg": "SHA-256", "content": pkg.source_sha256}],
            "externalReferences": [{"type": "distribution", "url": pkg.source_url}],
        }
        if recipe:
            component["licenses"] = [{"license": {"name": recipe.license}}]
            if recipe.description:
                component["description"] = recipe.description
            if recipe.purl:
                component["purl"] = _purl(recipe)
            if recipe.homepage:
                component["externalReferences"].append({"type": "website", "url": recipe.homepage})
        components.append(component)
    root_ref = f"app:{workspace_name}"
    dependencies: List[Dict[str, Any]] = [{
        "ref": root_ref,
        "dependsOn": sorted(ref(n) for n, p in lock.packages.items() if "workspace" in p.requested_by),
    }]
    for name in sorted(lock.packages):
        deps = sorted({ref(constraint_of(d)[0]) for d in lock.packages[name].dependencies
                       if constraint_of(d)[0] in lock.packages})
        dependencies.append({"ref": ref(name), "dependsOn": deps})
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": f"urn:uuid:{serial or uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": _timestamp(now),
            "tools": {"components": [{"type": "application", "name": "charpente", "version": _version.__version__}]},
            "component": {"type": "application", "bom-ref": root_ref, "name": workspace_name,
                          "version": workspace_version or "unknown"},
        },
        "components": components, "dependencies": dependencies,
    }
