"""The module API: what a Charpente module can provide and what it may ask for.

Everything that is not the core is a module -- toolchains, platforms,
languages, package formats, quality checks, notifiers, AI providers, project
templates, commands, event subscribers. Official modules and community modules
use exactly this API.

Versioning: `MODULE_API_VERSION` follows semantic versioning. A module declares
the range it was written for (`api = "^2.0"`) and is refused when this
Charpente is outside it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable

MODULE_API_VERSION = "2.0.0"

MANIFEST_NAME = "charpente-module.toml"
SIGNATURE_NAME = "charpente-module.sig"

# Extension points a module can register, and the manifest key that declares them.
EXTENSION_KINDS: Dict[str, str] = {
    "toolchain": "toolchains",
    "platform": "platforms",
    "language": "languages",
    "kind": "kinds",
    "packager": "packagers",
    "quality_check": "checks",
    "notifier": "notifiers",
    "ai_provider": "ai_providers",
    "template": "templates",
    "command": "commands",
    "event_subscriber": "subscribers",
}

FILESYSTEM_LEVELS = ("none", "workspace", "build", "home")


@dataclass(frozen=True)
class Capabilities:
    """What a module asks to be allowed to do (and, once approved, may do)."""

    #: executable base names it may start through `ctx.process` ("*" = any)
    process: Tuple[str, ...] = ()
    #: none | workspace | build | home
    filesystem: str = "none"
    #: False, True (any host) or an allow-list of host names
    network: Any = False

    def network_hosts(self) -> Tuple[str, ...]:
        if self.network is True:
            return ("*",)
        if isinstance(self.network, (list, tuple)):
            return tuple(str(h) for h in self.network)
        return ()

    def to_dict(self) -> Dict[str, Any]:
        network: Any = list(self.network) if isinstance(self.network, (list, tuple)) else bool(self.network)
        return {"process": list(self.process), "filesystem": self.filesystem, "network": network}

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Capabilities":
        network = data.get("network", False)
        return Capabilities(
            process=tuple(str(p) for p in data.get("process", ())),
            filesystem=str(data.get("filesystem", "none")),
            network=tuple(str(h) for h in network) if isinstance(network, list) else bool(network),
        )

    def covers(self, wanted: "Capabilities") -> bool:
        """True if everything `wanted` asks for is already allowed here."""
        if "*" not in self.process and not set(wanted.process) <= set(self.process):
            return False
        if FILESYSTEM_LEVELS.index(wanted.filesystem) > FILESYSTEM_LEVELS.index(self.filesystem):
            return False
        want_hosts, have_hosts = wanted.network_hosts(), self.network_hosts()
        if want_hosts and "*" not in have_hosts and not set(want_hosts) <= set(have_hosts):
            return False
        return True

    def describe(self) -> List[str]:
        lines: List[str] = []
        if self.process:
            lines.append("run programs: " + ", ".join(self.process))
        if self.filesystem != "none":
            lines.append(f"access files ({self.filesystem})")
        hosts = self.network_hosts()
        if hosts:
            lines.append("use the network" + ("" if hosts == ("*",) else " (" + ", ".join(hosts) + ")"))
        return lines or ["nothing beyond its own code (no programs, files or network)"]


@dataclass(frozen=True)
class Manifest:
    name: str
    version: str
    api: str
    license: str
    description: str
    entry: str
    python: str = ""
    provides: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    capabilities: Capabilities = field(default_factory=Capabilities)
    homepage: str = ""


# --------------------------------------------------------------------- extension protocols
@runtime_checkable
class ToolchainProvider(Protocol):
    """Finds compilers. `detect(host_os, which)` returns `charpente.toolchains.Toolchain` values."""

    name: str

    def detect(self, host_os: Any, which: Callable[[str], Optional[str]]) -> List[Any]: ...


@runtime_checkable
class Command(Protocol):
    """A `charpente <name>` sub-command."""

    name: str
    help: str

    def __call__(self, args: List[str]) -> int: ...


@runtime_checkable
class Notifier(Protocol):
    """Delivers a message to a person or a channel. Opt-in: needs configuration."""

    name: str

    def notify(self, title: str, message: str, *, ok: bool = True, **extra: Any) -> None: ...


@runtime_checkable
class QualityCheck(Protocol):
    """A check of the quality gate (`charpente check`)."""

    name: str
    level: str  # rapide | standard | strict

    def run(self, workspace_root: Path, files: Optional[List[Path]], fix: bool) -> Any: ...


@runtime_checkable
class Packager(Protocol):
    name: str

    def package(self, workspace: Any, target: Any, output: Path, **options: Any) -> Path: ...


@runtime_checkable
class Template(Protocol):
    name: str
    description: str

    def generate(self, destination: Path, project_name: str) -> List[Path]: ...


@runtime_checkable
class EventSubscriber(Protocol):
    """Receives events. `patterns` are fnmatch patterns of event types."""

    name: str
    patterns: List[str]

    def __call__(self, event: Any) -> None: ...
