"""Conformance checks: what a module must pass to be a good citizen.

`charpente module check PATH` runs these (module authors and registries use it).

Errors (the module cannot be installed/loaded correctly):
  * invalid manifest, incompatible module API;
  * entry point does not import, or `register` raises;
  * registers something it did not declare, or declares something it never registers;
  * a registered extension does not implement its interface.
Warnings (allowed, but worth knowing):
  * imports `subprocess`, `socket`, `ctypes` or calls `os.system` directly, which
    bypasses the capability system (the guarded `ctx.process` / `ctx.net` exist for this);
  * no signature.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from ..errors import ChError
from . import manifest as manifest_mod
from . import signing
from .api import (
    EXTENSION_KINDS,
    Command,
    EventSubscriber,
    Notifier,
    Packager,
    QualityCheck,
    Template,
    ToolchainProvider,
)
from .capabilities import ModuleContext
from .loader import _purge_foreign
from .registry import ExtensionRegistry

_RISKY_IMPORTS = {"subprocess": "start programs", "socket": "use the network", "ctypes": "call native code",
                  "urllib.request": "use the network", "http.client": "use the network"}
_PROTOCOLS: Dict[str, Any] = {
    "toolchain": ToolchainProvider, "command": Command, "notifier": Notifier, "quality_check": QualityCheck,
    "packager": Packager, "template": Template, "event_subscriber": EventSubscriber,
}


@dataclass(frozen=True)
class Issue:
    level: str          # "error" | "warning"
    message: str


def _scan_risky(folder: Path) -> List[Issue]:
    issues: List[Issue] = []
    for path in sorted(folder.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            issues.append(Issue("error", f"{path.name}: cannot be parsed ({exc})"))
            continue
        for node in ast.walk(tree):
            names: List[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name in _RISKY_IMPORTS:
                    issues.append(Issue("warning", f"{path.name}: imports {name} directly (to "
                                                   f"{_RISKY_IMPORTS[name]}); prefer the guarded ctx services "
                                                   f"so the capability system applies"))
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("system", "popen") and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "os"):
                issues.append(Issue("warning", f"{path.name}: calls os.{node.func.attr}(); use ctx.process"))
    return issues


def check_module(folder: Path) -> List[Issue]:
    folder = Path(folder)
    issues: List[Issue] = []
    try:
        manifest, warnings = manifest_mod.load(folder)
    except ChError as exc:
        return [Issue("error", exc.message)]
    issues.extend(Issue("warning", w) for w in warnings)
    try:
        manifest_mod.check_api(manifest)
    except ChError as exc:
        issues.append(Issue("error", exc.message))
        return issues

    status = signing.check_signature(folder)
    if status.state == "invalid":
        issues.append(Issue("error", f"signature invalid: {status.detail}"))
    elif not status.signed:
        issues.append(Issue("warning", f"not signed by a trusted key ({status.detail})"))

    issues.extend(_scan_risky(folder))
    if any(i.level == "error" for i in issues):
        return issues

    registry = ExtensionRegistry()
    with tempfile.TemporaryDirectory(prefix="charpente-conformance-") as tmp:
        ctx = ModuleContext(manifest, manifest.capabilities, data_dir=Path(tmp), workspace_root=None)
        before = set(sys.modules)
        added = str(folder) not in sys.path
        if added:
            sys.path.insert(0, str(folder))
        try:
            module_name, _, func_name = manifest.entry.partition(":")
            _purge_foreign(module_name, str(folder))
            try:
                register = getattr(importlib.import_module(module_name), func_name)
            except Exception as exc:
                issues.append(Issue("error", f"entry point {manifest.entry!r} cannot be imported: "
                                             f"{type(exc).__name__}: {exc}"))
                return issues
            if not callable(register):
                issues.append(Issue("error", f"entry point {manifest.entry!r} is not callable"))
                return issues
            try:
                params = len(inspect.signature(register).parameters)
            except (TypeError, ValueError):
                params = 2
            try:
                view = registry.for_module(manifest)
                register(view, ctx) if params >= 2 else register(view)
            except ChError as exc:
                issues.append(Issue("error", exc.message))
                return issues
            except Exception as exc:
                issues.append(Issue("error", f"register() raised {type(exc).__name__}: {exc}"))
                return issues
        finally:
            if added and str(folder) in sys.path:
                sys.path.remove(str(folder))
            for name in set(sys.modules) - before:
                module = sys.modules.get(name)
                origin = str(getattr(module, "__file__", "") or "")
                if origin.startswith(str(folder)):
                    del sys.modules[name]

    registered: Dict[str, List[str]] = {}
    for kind, key in EXTENSION_KINDS.items():
        for ext in registry.all(kind):
            registered.setdefault(key, []).append(ext.name)
            protocol = _PROTOCOLS.get(kind)
            if protocol is not None and not isinstance(ext.obj, protocol):
                issues.append(Issue("error", f"{kind} {ext.name!r} does not implement the {protocol.__name__} "
                                             f"interface"))
    for key, names in manifest.provides.items():
        if key == "events":
            continue
        for name in names:
            if name not in registered.get(key, []):
                issues.append(Issue("error", f"declares {key} {name!r} but never registers it"))
    return issues


def has_errors(issues: List[Issue]) -> bool:
    return any(i.level == "error" for i in issues)
