"""The guarded services a module receives: `ctx.process`, `ctx.fs`, `ctx.net`.

A module declares what it needs in its manifest, the user approves it at
installation, and these services check every call against the approved set.

An honest limit (also stated in docs/modules.md and docs/security.md):
**this is a contract, not a sandbox.** A module is Python code running in
the same process; nothing prevents it from importing `subprocess` or `socket`
itself. The capability system makes the honest path explicit, auditable and
enforced for modules that use the provided APIs, and lets the user see and
refuse what a module claims. Trust in a module comes from its signature and
its author, not from these checks.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..core import process
from ..errors import ChError
from ..events import EventBus
from .api import Capabilities, Manifest


def _base(program: str) -> str:
    name = os.path.basename(program)
    return name[:-4] if name.lower().endswith(".exe") else name


class GuardedProcess:
    def __init__(self, module: str, caps: Capabilities) -> None:
        self._module = module
        self._caps = caps

    def allowed(self, program: str) -> bool:
        return "*" in self._caps.process or _base(program) in self._caps.process

    def run(self, argv: Sequence[str], **kwargs: Any) -> process.ProcessResult:
        if not argv or not self.allowed(str(argv[0])):
            raise ChError("CH7005", module=self._module, capability=f"process:{argv[0] if argv else ''}")
        return process.run(list(argv), **kwargs)


class GuardedFS:
    def __init__(self, module: str, caps: Capabilities, workspace_root: Optional[Path], data_dir: Path) -> None:
        self._module = module
        self._data_dir = data_dir.resolve()
        roots: List[Path] = [self._data_dir]           # a module always owns its own data folder
        if caps.filesystem in ("workspace", "build", "home") and workspace_root is not None:
            roots.append((workspace_root / "build").resolve() if caps.filesystem == "build"
                         else workspace_root.resolve())
        if caps.filesystem == "home":
            roots.append(Path.home().resolve())
        self._roots = roots

    def _check(self, path: "str | Path") -> Path:
        resolved = Path(path).resolve()
        for root in self._roots:
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue
        raise ChError("CH7005", module=self._module, capability=f"filesystem:{resolved}")

    def read_text(self, path: "str | Path", encoding: str = "utf-8") -> str:
        return self._check(path).read_text(encoding=encoding)

    def read_bytes(self, path: "str | Path") -> bytes:
        return self._check(path).read_bytes()

    def write_text(self, path: "str | Path", text: str, encoding: str = "utf-8") -> None:
        target = self._check(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding=encoding)

    def exists(self, path: "str | Path") -> bool:
        return self._check(path).exists()

    def listdir(self, path: "str | Path") -> List[str]:
        return sorted(p.name for p in self._check(path).iterdir())


class GuardedNet:
    def __init__(self, module: str, caps: Capabilities, opener: Optional[Callable[..., Any]] = None) -> None:
        self._module = module
        self._hosts = caps.network_hosts()
        self._opener = opener or urllib.request.urlopen

    def allowed(self, url: str) -> bool:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        return bool(self._hosts) and ("*" in self._hosts or host in {h.lower() for h in self._hosts})

    def request(self, method: str, url: str, *, data: Optional[bytes] = None,
                headers: Optional[Mapping[str, str]] = None, timeout: float = 15.0) -> Tuple[int, bytes]:
        """(status, body). Only http/https; only hosts the module was approved for."""
        scheme = urllib.parse.urlparse(url).scheme
        if scheme not in ("http", "https") or not self.allowed(url):
            raise ChError("CH7005", module=self._module, capability=f"network:{url}")
        request = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
        try:
            with self._opener(request, timeout=timeout) as response:
                return int(response.status), bytes(response.read())
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read()

    def post_json(self, url: str, payload: Mapping[str, Any], timeout: float = 15.0) -> Tuple[int, bytes]:
        import json

        return self.request("POST", url, data=json.dumps(payload).encode("utf-8"),
                            headers={"Content-Type": "application/json"}, timeout=timeout)


class ModuleContext:
    """What `register(registry, ctx)` and every extension of a module receives."""

    def __init__(self, manifest: Manifest, approved: Capabilities, *, data_dir: Path,
                 workspace_root: Optional[Path] = None, bus: Optional[EventBus] = None,
                 opener: Optional[Callable[..., Any]] = None) -> None:
        self.manifest = manifest
        self.name = manifest.name
        self.approved = approved
        self.data_dir = data_dir
        self.workspace_root = workspace_root
        self._bus = bus
        self.process = GuardedProcess(manifest.name, approved)
        self.fs = GuardedFS(manifest.name, approved, workspace_root, data_dir)
        self.net = GuardedNet(manifest.name, approved, opener)
        self.config: Dict[str, Any] = {}

    def set_workspace_root(self, root: Optional[Path]) -> None:
        """Bind the workspace once a command knows it (modules are loaded before that)."""
        self.workspace_root = root
        self.fs = GuardedFS(self.name, self.approved, root, self.data_dir)

    def emit(self, event_type: str, **payload: Any) -> None:
        """Emit an event the module declared in `[provides] events`."""
        if event_type not in self.manifest.provides.get("events", ()):
            raise ChError("CH7005", module=self.name, capability=f"emit:{event_type}")
        if self._bus is not None:
            self._bus.emit(event_type, **payload)
