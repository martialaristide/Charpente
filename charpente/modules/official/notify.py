"""charpente-notify: opt-in notifications when a build finishes.

Configure in `.charpente/notify.toml` (secrets only by environment variable
name, never as literal values in the file):

    [[notify]]
    type = "discord"                 # desktop | webhook | discord | slack | telegram | email
    url_env = "CHARPENTE_DISCORD_URL"
    when = "failure"                 # always (default) | failure | success

    [[notify]]
    type = "telegram"
    token_env = "TELEGRAM_TOKEN"
    chat_id = "123456"

    [[notify]]
    type = "email"
    smtp_host = "smtp.example.org"
    smtp_port = 587
    username_env = "SMTP_USER"
    password_env = "SMTP_PASSWORD"
    from = "builds@example.org"
    to = ["me@example.org"]

Nothing is sent unless this file exists and the module is enabled; message
text contains the machine name, configuration and counts -- never source code.
"""
from __future__ import annotations

import os
import platform as _platform
import smtplib
import socket
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ... import _toml
from ...errors import ChError
from ...events import Event
from ..capabilities import ModuleContext
from ..registry import ModuleRegistry

CONFIG_RELATIVE = Path(".charpente") / "notify.toml"
NOTIFIER_TYPES = ("desktop", "webhook", "discord", "slack", "telegram", "email")

_TEXT = {
    "en": {"ok": "Build succeeded", "fail": "Build failed", "line": "{command} {config} on {host}: {summary} ({duration:.1f}s)",
           "failed": "{n} failed action(s)", "fine": "no failures"},
    "fr": {"ok": "Build réussi", "fail": "Build en échec", "line": "{command} {config} sur {host} : {summary} ({duration:.1f}s)",
           "failed": "{n} action(s) en échec", "fine": "aucun échec"},
}


def _lang() -> str:
    from ... import i18n

    return i18n.current_lang()


class NotifyConfigError(ValueError):
    pass


def load_config(root: Optional[Path]) -> List[Dict[str, Any]]:
    """Notifier entries from `<root>/.charpente/notify.toml` (empty if absent)."""
    if root is None:
        return []
    path = root / CONFIG_RELATIVE
    if not path.exists():
        return []
    try:
        data = _toml.load_file(path)
    except (OSError, _toml.TOMLDecodeError) as exc:
        raise NotifyConfigError(f"{path}: {exc}") from exc
    entries = data.get("notify", [])
    if not isinstance(entries, list):
        raise NotifyConfigError(f"{path}: 'notify' must be an array of tables ([[notify]])")
    clean: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") not in NOTIFIER_TYPES:
            raise NotifyConfigError(f"{path}: each [[notify]] needs type = one of {', '.join(NOTIFIER_TYPES)}")
        for key in entry:
            if key.endswith("_env") or key in ("type", "when", "events", "to", "from", "chat_id", "smtp_host",
                                               "smtp_port", "starttls", "api_base", "title"):
                continue
            if key in ("url", "token", "password", "username", "webhook", "secret"):
                raise NotifyConfigError(
                    f"{path}: '{key}' must not be written in the file: use '{key}_env' and set that "
                    f"environment variable instead (secrets never live in a repository).")
        clean.append(entry)
    return clean


def _env(entry: Dict[str, Any], key: str) -> str:
    name = entry.get(f"{key}_env")
    if not name:
        raise NotifyConfigError(f"a {entry['type']} notifier needs {key}_env = \"NAME_OF_ENV_VARIABLE\"")
    value = os.environ.get(str(name), "")
    if not value:
        raise NotifyConfigError(f"environment variable {name} is not set (needed by the {entry['type']} notifier)")
    return value


class _Base:
    name = ""

    def __init__(self, ctx: ModuleContext) -> None:
        self.ctx = ctx
        self.entry: Dict[str, Any] = {}

    def configured(self, entry: Dict[str, Any]) -> "_Base":
        clone = type(self)(self.ctx)
        clone.entry = entry
        return clone

    def notify(self, title: str, message: str, *, ok: bool = True, **extra: Any) -> None:  # pragma: no cover
        raise NotImplementedError


class WebhookNotifier(_Base):
    name = "webhook"

    def notify(self, title: str, message: str, *, ok: bool = True, **extra: Any) -> None:
        url = _env(self.entry, "url")
        self.ctx.net.post_json(url, {"title": title, "message": message, "ok": ok, **extra})


class DiscordNotifier(_Base):
    name = "discord"

    def notify(self, title: str, message: str, *, ok: bool = True, **extra: Any) -> None:
        url = _env(self.entry, "url")
        emoji = "✅" if ok else "❌"
        self.ctx.net.post_json(url, {"content": f"{emoji} **{title}**\n{message}"})


class SlackNotifier(_Base):
    name = "slack"

    def notify(self, title: str, message: str, *, ok: bool = True, **extra: Any) -> None:
        url = _env(self.entry, "url")
        emoji = ":white_check_mark:" if ok else ":x:"
        self.ctx.net.post_json(url, {"text": f"{emoji} *{title}*\n{message}"})


class TelegramNotifier(_Base):
    name = "telegram"

    def notify(self, title: str, message: str, *, ok: bool = True, **extra: Any) -> None:
        token = _env(self.entry, "token")
        base = str(self.entry.get("api_base", "https://api.telegram.org")).rstrip("/")
        chat_id = self.entry.get("chat_id")
        if not chat_id:
            raise NotifyConfigError("a telegram notifier needs chat_id")
        emoji = "✅" if ok else "❌"
        self.ctx.net.post_json(f"{base}/bot{token}/sendMessage",
                               {"chat_id": str(chat_id), "text": f"{emoji} {title}\n{message}"})


class EmailNotifier(_Base):
    name = "email"

    def notify(self, title: str, message: str, *, ok: bool = True, **extra: Any) -> None:
        host = self.entry.get("smtp_host")
        recipients = self.entry.get("to")
        sender = self.entry.get("from")
        if not host or not recipients or not sender:
            raise NotifyConfigError("an email notifier needs smtp_host, from and to")
        if not self.ctx.approved.network_hosts():
            raise ChError("CH7005", module=self.ctx.name, capability=f"network:{host}")
        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = str(sender)
        msg["To"] = ", ".join(str(r) for r in recipients)
        msg.set_content(message)
        port = int(self.entry.get("smtp_port", 587))
        with smtplib.SMTP(str(host), port, timeout=20) as smtp:
            if self.entry.get("starttls", True):
                smtp.starttls()
            if self.entry.get("username_env"):
                smtp.login(_env(self.entry, "username"), _env(self.entry, "password"))
            smtp.send_message(msg)


class DesktopNotifier(_Base):
    name = "desktop"

    def notify(self, title: str, message: str, *, ok: bool = True, **extra: Any) -> None:
        if sys.platform == "win32":
            script = ("Add-Type -AssemblyName System.Windows.Forms; "
                      "$n = New-Object System.Windows.Forms.NotifyIcon; "
                      "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
                      "$n.ShowBalloonTip(5000, $env:CHARPENTE_NOTIFY_TITLE, $env:CHARPENTE_NOTIFY_TEXT, "
                      "[System.Windows.Forms.ToolTipIcon]::None); Start-Sleep -Seconds 6")
            env = dict(os.environ, CHARPENTE_NOTIFY_TITLE=title, CHARPENTE_NOTIFY_TEXT=message)
            self.ctx.process.run(["powershell", "-NoProfile", "-Command", script], env=env, timeout=30)
        elif sys.platform == "darwin":
            script = "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run"
            self.ctx.process.run(["osascript", "-e", script, title, message], timeout=15)
        else:
            self.ctx.process.run(["notify-send", title, message], timeout=15)


_CLASSES = {c.name: c for c in (WebhookNotifier, DiscordNotifier, SlackNotifier, TelegramNotifier,
                                EmailNotifier, DesktopNotifier)}


def compose(summary: Dict[str, Any]) -> "tuple[str, str, bool]":
    """(title, message, ok) for a finished session. Text carries no source code."""
    text = _TEXT[_lang()]
    ok = bool(summary.get("ok", True))
    failed = int(summary.get("failed_actions", 0))
    body = text["line"].format(
        command=summary.get("command", "build"), config=summary.get("config", "") or "",
        host=summary.get("host") or socket.gethostname(),
        summary=text["failed"].format(n=failed) if failed else text["fine"],
        duration=float(summary.get("duration", 0.0)),
    ).replace("  ", " ")
    return text["ok"] if ok else text["fail"], body, ok


class Dispatcher:
    """Sends a composed message to every configured notifier that wants it."""

    def __init__(self, ctx: ModuleContext, entries: List[Dict[str, Any]],
                 on_error: Optional[Callable[[str], None]] = None) -> None:
        self.ctx = ctx
        self.entries = entries
        self.on_error = on_error or (lambda m: print(f"charpente-notify: {m}", file=sys.stderr))

    def send(self, title: str, message: str, ok: bool, *, event: str = "session.finished") -> int:
        sent = 0
        for entry in self.entries:
            when = entry.get("when", "always")
            if (when == "failure" and ok) or (when == "success" and not ok):
                continue
            if event not in entry.get("events", ["session.finished"]):
                continue
            try:
                _CLASSES[entry["type"]](self.ctx).configured(entry).notify(
                    entry.get("title") or title, message, ok=ok, host=socket.gethostname(),
                    system=_platform.system())
                sent += 1
            except (NotifyConfigError, ChError, OSError, smtplib.SMTPException) as exc:
                self.on_error(f"{entry['type']}: {exc}")
        return sent


class SessionSubscriber:
    """Event subscriber: summarises a session and notifies when it finishes."""

    name = "notify-on-session"
    patterns = ["session.started", "session.finished", "action.failed", "test.failed"]

    def __init__(self, ctx: ModuleContext) -> None:
        self.ctx = ctx
        self.failed = 0
        self.command = "build"
        self.config = ""

    def __call__(self, event: Event) -> None:
        if event.type == "session.started":
            self.command = str(event.payload.get("command", "build"))
            self.config = str(event.payload.get("config") or "")
        elif event.type in ("action.failed", "test.failed"):
            self.failed += 1
        elif event.type == "session.finished":
            try:
                entries = load_config(self.ctx.workspace_root)
            except NotifyConfigError as exc:
                print(f"charpente-notify: {exc}", file=sys.stderr)
                return
            if not entries:
                return
            title, body, ok = compose({"ok": event.payload.get("ok", True), "failed_actions": self.failed,
                                       "command": self.command, "config": self.config,
                                       "duration": event.payload.get("duration", 0.0)})
            Dispatcher(self.ctx, entries).send(title, body, ok)


class NotifyCommand:
    name = "notify"
    help = "charpente notify test -- send a test message through the configured notifiers"

    def __init__(self, ctx: ModuleContext) -> None:
        self.ctx = ctx

    def __call__(self, args: List[str]) -> int:
        if args != ["test"]:
            print("usage: charpente notify test")
            return 1
        try:
            entries = load_config(self.ctx.workspace_root)
        except NotifyConfigError as exc:
            print(f"charpente-notify: {exc}", file=sys.stderr)
            return 1
        if not entries:
            print("No notifiers configured. Create .charpente/notify.toml (see `charpente module info charpente-notify`).")
            return 1
        title, body, ok = compose({"ok": True, "failed_actions": 0, "command": "test", "duration": 0.0})
        sent = Dispatcher(self.ctx, entries, on_error=lambda m: print(f"  failed: {m}")).send(title, body, ok)
        print(f"Sent {sent} of {len(entries)} notification(s).")
        return 0 if sent == len(entries) else 1


def register(registry: ModuleRegistry, ctx: ModuleContext) -> None:
    for cls in _CLASSES.values():
        registry.add_notifier(cls(ctx))
    registry.add_command(NotifyCommand(ctx))
    registry.add_subscriber(SessionSubscriber(ctx))

