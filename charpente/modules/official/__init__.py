"""Official modules that ship inside the Charpente package.

They use exactly the same API and capability system as any third-party module,
but need no download. They are **disabled until you enable them**
(`charpente module enable NAME`, which shows what they ask for and asks for
approval): being bundled does not mean being on.
"""
from __future__ import annotations

from typing import Dict, List

from ..api import Manifest
from ..manifest import loads

NOTIFY_MANIFEST = """
[module]
name = "charpente-notify"
version = "1.0.0"
api = "^2.0"
license = "Apache-2.0"
description = "Tell you when a build finishes: desktop notification, webhook, Discord, Slack, Telegram, e-mail"
entry = "charpente.modules.official.notify:register"

[provides]
notifiers = ["desktop", "webhook", "discord", "slack", "telegram", "email"]
commands = ["notify"]
subscribers = ["notify-on-session"]

[capabilities]
process = ["notify-send", "osascript", "powershell"]
filesystem = "workspace"
network = true
"""

_MANIFESTS: Dict[str, str] = {"charpente-notify": NOTIFY_MANIFEST}


def bundled_names() -> List[str]:
    return sorted(_MANIFESTS)


def bundled_manifest(name: str) -> Manifest:
    return loads(_MANIFESTS[name], f"<bundled {name}>")[0]


def is_bundled(name: str) -> bool:
    return name in _MANIFESTS
