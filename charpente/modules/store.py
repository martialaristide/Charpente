"""Where modules live and what the user decided about them.

    ~/.charpente/modules/
        modules.json            # installed modules, their state, registries
        packages/<name>/<ver>/  # unpacked module folders
        data/<name>/            # a module's private data folder

`modules.json` is written atomically. Losing it loses only the *decisions*
(enabled/approved), never a module's files.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..dsl.trust import config_dir
from .api import Capabilities


@dataclass
class InstalledModule:
    name: str
    version: str
    path: str                      # "" for bundled modules
    enabled: bool = True
    approved: Dict[str, Any] = field(default_factory=dict)      # Capabilities.to_dict()
    source: str = ""
    digest: str = ""
    signature: str = "unsigned"    # 'signed:<key_id>' | 'unsigned' | 'bundled'
    installed_at: float = field(default_factory=time.time)
    bundled: bool = False

    def approved_caps(self) -> Capabilities:
        return Capabilities.from_dict(self.approved)


class ModuleStore:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else config_dir() / "modules"
        self._file = self.root / "modules.json"

    # ------------------------------------------------------------------ state
    def _read(self) -> Dict[str, Any]:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        return {}

    def _write(self, data: Dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._file)

    def list(self) -> List[InstalledModule]:
        raw = self._read().get("modules", {})
        out: List[InstalledModule] = []
        for name, entry in sorted(raw.items()):
            try:
                out.append(InstalledModule(name=name, **entry))
            except TypeError:
                continue                       # an entry from a future version: ignore, never crash
        return out

    def get(self, name: str) -> Optional[InstalledModule]:
        return next((m for m in self.list() if m.name == name), None)

    def put(self, module: InstalledModule) -> None:
        data = self._read()
        entry = asdict(module)
        entry.pop("name")
        data.setdefault("modules", {})[module.name] = entry
        self._write(data)

    def remove(self, name: str) -> bool:
        data = self._read()
        existed = data.get("modules", {}).pop(name, None) is not None
        if existed:
            self._write(data)
        for sub in ("packages", "data"):
            shutil.rmtree(self.root / sub / name, ignore_errors=True)
        return existed

    def set_enabled(self, name: str, enabled: bool) -> bool:
        module = self.get(name)
        if module is None:
            return False
        module.enabled = enabled
        self.put(module)
        return True

    def set_approved(self, name: str, caps: Capabilities) -> bool:
        module = self.get(name)
        if module is None:
            return False
        module.approved = caps.to_dict()
        self.put(module)
        return True

    # ------------------------------------------------------------------ paths
    def package_dir(self, name: str, version: str) -> Path:
        return self.root / "packages" / name / version

    def data_dir(self, name: str) -> Path:
        return self.root / "data" / name

    def staging_dir(self) -> Path:
        return self.root / "tmp"

    # -------------------------------------------------------------- registries
    def registries(self) -> List[str]:
        raw = self._read().get("registries", [])
        return [str(r) for r in raw] if isinstance(raw, list) else []

    def add_registry(self, url: str) -> None:
        data = self._read()
        regs = [str(r) for r in data.get("registries", [])]
        if url not in regs:
            regs.append(url)
        data["registries"] = regs
        self._write(data)

    def remove_registry(self, url: str) -> bool:
        data = self._read()
        regs = [str(r) for r in data.get("registries", [])]
        if url not in regs:
            return False
        regs.remove(url)
        data["registries"] = regs
        self._write(data)
        return True
