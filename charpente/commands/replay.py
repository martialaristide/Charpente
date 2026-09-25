"""`charpente replay [session]` -- replay the events of a past build from its
JSON Lines log, as readable lines or (`--output jsonl`) raw."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..builder import state_dir
from ..errors import ChError
from ..output import read_log
from ._common import load


def _summary(event: Dict[str, Any]) -> str:
    p = event["payload"]
    kind = event["type"]
    if kind.startswith("action."):
        return f"{p.get('action', '')} {p.get('description') or ''}".strip()
    if kind.startswith("target."):
        return str(p.get("target", ""))
    if kind == "diagnostic.emitted":
        return f"{p.get('file') or ''}:{p.get('line') or ''} {p['severity']}: {p['message']}"
    if kind == "session.finished":
        return f"ok={p['ok']} in {p['duration']:.2f}s"
    return json.dumps(p, default=str)[:100]


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente replay", description="Replay a recorded build session.")
    parser.add_argument("session", nargs="?", help="Session id (prefix) or path to a .jsonl log; default: latest")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--output", choices=["plain", "jsonl"], default="plain")
    parsed = parser.parse_args(args)

    log: Optional[Path] = None
    if parsed.session and Path(parsed.session).is_file():
        log = Path(parsed.session)
    else:
        workspace = load(parsed.file)
        directory = state_dir(workspace) / "events"
        logs = sorted(directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if directory.exists() else []
        if parsed.session:
            logs = [p for p in logs if p.stem.startswith(parsed.session)]
        if not logs:
            raise ChError("CH4005", usage="No recorded session found. Run a build first.")
        log = logs[0]

    events = read_log(log)
    first = events[0]["timestamp"] if events else 0.0
    for event in events:
        if parsed.output == "jsonl":
            print(json.dumps(event, separators=(",", ":")))
        else:
            print(f"+{event['timestamp'] - first:7.3f}s  {event['type']:<22} {_summary(event)}")
    return 0
