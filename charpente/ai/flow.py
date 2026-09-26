"""The rules every AI request follows, in one place: opt-in, visible, confirmed, never automatic.

`review_and_confirm` shows what would be sent (a summary, or the full text with `show_full`), and returns only when the user agreed
(`assume_yes`, or an interactive answer). It never sends anything itself. `dry_run` stops after showing.
"""
from __future__ import annotations

import sys
from typing import Callable, Optional

from ..errors import ChError
from .context import Context
from .provider import AIProvider


class NotConfirmed(Exception):
    """The user declined, or the session is not interactive and did not pass --yes."""


def ask_yes_no(question: str, default: bool = False, *, read: Optional[Callable[[str], str]] = None) -> bool:
    answer = (read or input)(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    return default if not answer else answer in ("y", "yes", "o", "oui")


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def require_provider(provider: AIProvider) -> None:
    """CH8020-free honesty: an unconfigured provider is not an error of the project, but the command cannot do its job."""
    if not provider.is_available():
        raise ChError("CH8020", detail=provider.complete("").strip())


def review_and_confirm(context: Context, provider: AIProvider, *, show_full: bool, assume_yes: bool, dry_run: bool,
                       say: Callable[[str], None] = print, read: Optional[Callable[[str], str]] = None,
                       is_interactive: Optional[bool] = None) -> bool:
    """Show the context. True when the request should now be sent; False for a dry run. Raises NotConfirmed when declined."""
    say(f"Charpente will send this to {provider.name}:")
    say(context.summary())
    if context.redactions:
        say(f"  ({context.redactions} probable secret(s) were replaced before sending.)")
    if show_full or dry_run:
        say("--- exactly what is sent ---")
        say(context.render())
        say("--- end ---")
    if dry_run:
        say("Dry run: nothing was sent.")
        return False
    if assume_yes:
        return True
    if not (interactive() if is_interactive is None else is_interactive):
        raise NotConfirmed("this session is not interactive; pass --yes to allow sending the context shown above")
    if not ask_yes_no("Send it?", False, read=read):
        raise NotConfirmed("nothing was sent")
    return True
