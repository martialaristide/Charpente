"""What the console interface draws. Pure functions: data in, lines of text out, so every screen is tested at several widths, with and without colour and Unicode.

Nothing here reads the terminal or the disk. The text comes from a `tr(key, **values)` function (English or French), the look from a `Style` and `Glyphs`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

from .dashboard import Dashboard
from .term import Glyphs, Style, box, clip, pad, truncate_middle, visible_len

Tr = Callable[..., str]
INLINE_HINT_WIDTH = 72          # below this the hint of the selected row is shown on its own line instead of beside every row
DASHBOARD_MIN_WIDTH = 46


@dataclass(frozen=True)
class Entry:
    key: str
    label: str = ""
    hint: str = ""
    hotkey: str = ""
    kind: str = "item"           # "item" or "group" (a heading, never selectable)
    enabled: bool = True
    reason: str = ""             # why a disabled item is disabled


def group(label: str) -> Entry:
    return Entry(key="", label=label, kind="group")


def with_hotkeys(entries: Sequence[Entry], reserved: str = "qb?") -> List[Entry]:
    """Give every item without a hotkey the next free one: 1 to 9, then letters. Explicit hotkeys keep their place."""
    taken = {e.hotkey.lower() for e in entries if e.hotkey}
    pool = [c for c in "123456789abcdefghijklmnoprstuvwxyz" if c not in taken and c not in reserved]
    out: List[Entry] = []
    for entry in entries:
        if entry.kind == "item" and not entry.hotkey:
            entry = Entry(entry.key, entry.label, entry.hint, pool.pop(0) if pool else "", entry.kind, entry.enabled, entry.reason)
        out.append(entry)
    return out


def selectable(entries: Sequence[Entry]) -> List[int]:
    return [i for i, e in enumerate(entries) if e.kind == "item"]


def ago(seconds: float, tr: Tr) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return tr("ago.seconds", n=seconds)
    if seconds < 3600:
        return tr("ago.minutes", n=seconds // 60)
    if seconds < 86400:
        return tr("ago.hours", n=seconds // 3600)
    return tr("ago.days", n=seconds // 86400)


def banner(tr: Tr, version: str, style: Style, glyphs: Glyphs, width: int) -> List[str]:
    return [clip(f" {style.accent(glyphs.brand + ' Charpente')} {style.bold(version)}   {style.muted(tr('tagline'))}", width)]


def dashboard(dash: Dashboard, cwd: str, config: str, platform: Optional[str], tr: Tr, style: Style, glyphs: Glyphs, width: int,
              now: Optional[float] = None) -> List[str]:
    """The framed summary at the top: where you are, what the project is, how the last build went, what will build it."""
    now = time.time() if now is None else now
    inner = max(10, width - 6)
    machine = platform if platform else f"{tr('dash.native')} ({dash.host})"
    compiler = dash.compiler or style.warn(tr("dash.no_compiler"))
    labels = [tr("dash.folder"), tr("dash.last"), tr("dash.mode"), tr("dash.compiler")]
    lw = max(visible_len(s) for s in labels) + 1

    def row(label: str, value: str) -> str:
        return style.muted(pad(label, lw)) + value

    rows: List[str] = []
    if dash.has_project:
        rows.append(style.bold(dash.name) + "  " + style.muted(dash.file.name if dash.file else "") + (
            "  " + style.muted(f"{glyphs.dot} {tr('dash.targets', n=len(dash.targets))}") if dash.targets else ""))
        rows.append(row(tr("dash.folder"), truncate_middle(str(dash.root), max(10, inner - lw), glyphs.ellipsis)))
        if dash.last is None:
            rows.append(row(tr("dash.last"), style.muted(tr("dash.no_build"))))
        else:
            mark = style.ok(glyphs.dot + " " + tr("dash.succeeded")) if dash.last.ok else style.err(glyphs.dot + " " + tr("dash.failed"))
            rows.append(row(tr("dash.last"), f"{mark} {ago(now - dash.last.when, tr)} {style.muted('(' + dash.last.command + ', ' + f'{dash.last.duration:.1f} s)')}"))
        rows.append(row(tr("dash.mode"), f"{style.bold(config)} {glyphs.dot} {machine}"))
        rows.append(row(tr("dash.compiler"), compiler))
        if dash.state == "untrusted":
            rows.append(style.warn(tr("dash.untrusted")))
        elif dash.state == "error":
            rows.append(style.err(tr("dash.error", detail=" ".join(dash.detail.split())[:400])))
    else:
        rows.append(style.bold(tr("dash.no_project")))
        rows.append(row(tr("dash.folder"), truncate_middle(cwd, max(10, inner - lw), glyphs.ellipsis)))
        rows.append(row(tr("dash.compiler"), compiler))
        if dash.state == "ambiguous":
            rows.append(style.warn(tr("dash.ambiguous", detail=" ".join(dash.detail.split())[:300])))
    return box(rows, width, glyphs, tr("dash.title"), style)


def compact_dashboard(dash: Dashboard, cwd: str, config: str, platform: Optional[str], tr: Tr, style: Style, glyphs: Glyphs, width: int,
                      now: Optional[float] = None) -> List[str]:
    """Two short lines for a small terminal: which project and mode, and how the last build went (or what needs attention)."""
    now = time.time() if now is None else now
    if not dash.has_project:
        if dash.state == "ambiguous":
            second = style.warn(tr("dash.ambiguous", detail=" ".join(dash.detail.split())[:200]))
        else:
            second = style.muted(truncate_middle(cwd, max(10, width - 4), glyphs.ellipsis))
        return [clip(" " + style.bold(tr("dash.no_project")), width), clip(" " + second, width, glyphs.ellipsis)]
    first = f" {style.bold(dash.name)} {glyphs.dot} {style.bold(config)} {glyphs.dot} {platform or tr('dash.native')}"
    if dash.state == "untrusted":
        second = style.warn(tr("dash.untrusted_short"))
    elif dash.state == "error":
        second = style.err(tr("dash.error", detail=" ".join(dash.detail.split())[:200]))
    elif dash.last is None:
        second = style.muted(tr("dash.last") + ": " + tr("dash.no_build"))
    else:
        mark = style.ok(glyphs.dot + " " + tr("dash.succeeded")) if dash.last.ok else style.err(glyphs.dot + " " + tr("dash.failed"))
        second = f"{style.muted(tr('dash.last') + ':')} {mark} {ago(now - dash.last.when, tr)}"
    return [clip(first, width, glyphs.ellipsis), clip(" " + second, width, glyphs.ellipsis)]


def menu(entries: Sequence[Entry], selected: int, style: Style, glyphs: Glyphs, width: int, rows: int) -> Tuple[List[str], int]:
    """The menu as lines, scrolled so the selected row is visible when there are more rows than `rows`. Returns (lines, number of rows hidden)."""
    items = [e for e in entries if e.kind == "item"]
    label_w = max((visible_len(e.label) for e in items), default=0)
    inline = width >= INLINE_HINT_WIDTH
    lines: List[Tuple[int, str]] = []
    for index, entry in enumerate(entries):
        if entry.kind == "group":
            if lines:
                lines.append((index, ""))
            lines.append((index, "  " + style.muted(entry.label.upper())))
            continue
        chosen = index == selected
        marker = style.accent(glyphs.marker) if chosen else " "
        hot = pad(entry.hotkey, 2)
        label = pad(entry.label, label_w)
        if not entry.enabled:
            text = style.muted(label)
            tail = style.muted(entry.reason) if inline and entry.reason else ""
        else:
            text = style.accent(label) if chosen else label
            tail = style.muted(entry.hint) if inline and entry.hint else ""
        line = f"   {marker} {style.bold(hot) if entry.enabled else style.muted(hot)} {text}" + (f"   {tail}" if tail else "")
        lines.append((index, clip(line, width, glyphs.ellipsis).rstrip()))
    if len(lines) <= rows:
        return [text for _, text in lines], 0
    where = next((n for n, (i, _) in enumerate(lines) if i == selected), 0)
    room = max(3, rows - 2)
    start = min(max(0, where - room // 2), len(lines) - room)
    shown = lines[start:start + room]
    above, below = start, len(lines) - start - room
    out = [style.muted(f"   {glyphs.up_down[0]} …" if above else "")] + [text for _, text in shown] + [style.muted(f"   {glyphs.up_down[-1]} …" if below else "")]
    return out, above + below


def detail(entry: Optional[Entry], style: Style, width: int) -> str:
    """The line under the menu: what the selected row does, or why it cannot be used."""
    if entry is None or entry.kind != "item":
        return ""
    if not entry.enabled:
        return clip("   " + style.warn(entry.reason), width)
    return clip("   " + style.muted(entry.hint), width) if entry.hint else ""


def footer(tr: Tr, glyphs: Glyphs, keys: bool, width: int, style: Style) -> str:
    text = tr("footer.keys", ud=glyphs.up_down) if keys else tr("footer.line")
    return clip(" " + style.muted(text), width)


def tip_line(label: str, tip: str, style: Style, width: int, glyphs: Glyphs) -> str:
    return clip(" " + style.muted(label + " " + tip), width, glyphs.ellipsis)
