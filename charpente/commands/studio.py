"""`charpente studio` -- Charpente Studio, the workspace UI, served from this machine and opened in your browser."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import webbrowser
from pathlib import Path
from typing import List

from ..errors import ChError
from ..serve import ServerState
from ..serve.rpc import RpcError
from ..serve.webapp import WEB_DIR, make_http_handler
from ._common import CommandError, find_root
from .serve import make_ws_server


def start_studio(state: ServerState, port: int = 0) -> "tuple[object, str]":
    """(server, URL with token). The server is started; the caller decides how long it lives."""
    if not (WEB_DIR / "index.html").is_file():
        raise CommandError("CH8019", detail=f"{WEB_DIR / 'index.html'} is missing (a broken installation?)")
    token = secrets.token_urlsafe(24)
    holder: "dict[str, int]" = {}
    server = make_ws_server(state, token, port, make_http_handler(WEB_DIR, lambda: holder["port"]))
    holder["port"] = server.port
    server.allowed_hosts = {f"127.0.0.1:{server.port}", f"localhost:{server.port}"}
    server.start()
    return server, f"http://127.0.0.1:{server.port}/?token={token}"


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente studio", description="Open Charpente Studio (a local web app) for this project.")
    parser.add_argument("--root", help="Project folder (default: found from the current folder)")
    parser.add_argument("--file", help="The .charpente file (default: found from --root or the current folder)")
    parser.add_argument("--port", type=int, default=0, help="Port to listen on, on 127.0.0.1 only (default: a free one)")
    parser.add_argument("--no-browser", action="store_true", help="Only print the address; do not open a browser")
    parser.add_argument("--json", action="store_true", help="Print the address as one JSON line (for tools that launch Studio)")
    parsed = parser.parse_args(args)

    state = ServerState(Path(parsed.root).resolve() if parsed.root else find_root(), parsed.file)
    try:
        state.load()
    except RpcError as exc:                                  # not fatal: Studio shows the reason and lets you fix the file
        print(f"charpente: warning: {exc.message}", file=sys.stderr)
    try:
        server, url = start_studio(state, parsed.port)
    except (OSError, ChError) as exc:
        if isinstance(exc, ChError):
            raise
        raise CommandError("CH8019", detail=str(exc)) from exc
    if parsed.json:
        print(json.dumps({"charpente-studio": {"url": url, "pid": os.getpid(), "root": str(state.root)}}), flush=True)
    else:
        print(f"Charpente Studio: {url}\nThe address contains a private token: anyone who has it can build and run code in this project.\n"
              "Press Ctrl+C to stop.", flush=True)
    if not parsed.no_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nStopping Studio.")
    server.shutdown()                                        # type: ignore[attr-defined]
    return 0
