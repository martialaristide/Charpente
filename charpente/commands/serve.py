"""`charpente serve` -- the engine as a server for editors, IDEs and Charpente Studio."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..serve import ServerState, StdioServer, make_dispatcher
from ..serve.bsp import bsp_connection_details
from ..serve.rpc import PARSE_ERROR, Dispatcher, RpcError
from ..serve.ws import Connection, HttpHandler, WebSocketServer
from ._common import find_root, wait_until_interrupted


def install_bsp(root: Path) -> Path:
    """Write `.bsp/charpente.json` so BSP clients (IntelliJ/CLion, Metals-style tools, editors) find this server."""
    folder = root / ".bsp"
    folder.mkdir(exist_ok=True)
    path = folder / "charpente.json"
    path.write_text(json.dumps(bsp_connection_details([sys.executable, "-m", "charpente", "serve", "--stdio"]), indent=2),
                    encoding="utf-8")
    return path


def make_ws_server(state: ServerState, token: str, port: int = 0, http_handler: Optional[HttpHandler] = None) -> WebSocketServer:
    """A (not yet started) WebSocket server that gives every connection its own dispatcher over the shared `state`."""
    pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="ws-rpc")
    connections: Dict[Connection, Tuple[Dispatcher, List[int]]] = {}

    def on_connect(connection: Connection) -> Callable[[str], None]:
        ids: List[int] = []

        def notify(method: str, params: Any) -> None:
            if not connection.closed:
                connection.send_text(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, ensure_ascii=False))

        dispatcher = make_dispatcher(state, notify, track_subscription=ids.append)
        connections[connection] = (dispatcher, ids)

        def handle(text: str) -> None:
            try:
                message = json.loads(text)
            except ValueError:
                connection.send_text(json.dumps({"jsonrpc": "2.0", "id": None, "error": RpcError(PARSE_ERROR, "invalid JSON").to_dict()}))
                return
            if isinstance(message, dict):
                response = dispatcher.handle(message)
                if response is not None:
                    connection.send_text(json.dumps(response, ensure_ascii=False))

        def on_message(text: str) -> None:
            pool.submit(handle, text)

        return on_message

    def on_close(connection: Connection) -> None:
        dispatcher, ids = connections.pop(connection, (None, []))
        for ident in ids:
            state.unsubscribe(ident)
        if dispatcher is not None:
            dispatcher.close()

    return WebSocketServer(token, on_connect, on_close, port=port, http_handler=http_handler)


def wait_for_parent(server: WebSocketServer) -> None:
    """Serve until Ctrl+C or until our stdin closes (a parent that dies, or closes the pipe, takes the server with it)."""
    stop = threading.Event()

    def watch_stdin() -> None:
        try:
            while sys.stdin.buffer.read(4096):
                pass
        except (OSError, ValueError):
            pass
        stop.set()

    threading.Thread(target=watch_stdin, daemon=True, name="stdin-watch").start()
    interrupted = not wait_until_interrupted(stop)
    server.shutdown()
    if interrupted:
        # The stdin watcher is blocked in a read that cannot be interrupted; letting the interpreter shut down while it holds stdin's lock is a fatal error
        # on Windows ("could not acquire lock ... at interpreter shutdown"). Everything is closed by now, so leave directly.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)


def _serve_websocket(state: ServerState, port: int) -> int:
    token = secrets.token_urlsafe(24)
    server = make_ws_server(state, token, port)
    server.start()
    print(json.dumps({"charpente-server": {"url": server.url, "host": server.host, "port": server.port, "token": token,
                                           "pid": os.getpid(), "root": str(state.root)}}), flush=True)
    wait_for_parent(server)
    return 0


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente serve", description="Serve the build engine to editors and Charpente Studio.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--stdio", action="store_true", help="Build Server Protocol over stdin/stdout (the default)")
    mode.add_argument("--ws", action="store_true", help="JSON-RPC over a loopback WebSocket; prints its URL (with a random token) as one JSON line")
    parser.add_argument("--port", type=int, default=0, help="Port for --ws (default: a free one)")
    parser.add_argument("--file", help="The .charpente file (default: found from --root or the current folder)")
    parser.add_argument("--root", help="Project folder (default: found from the current folder)")
    parser.add_argument("--bsp-install", action="store_true", help="Write .bsp/charpente.json for BSP clients, then exit")
    parsed = parser.parse_args(args)

    root = Path(parsed.root).resolve() if parsed.root else find_root()
    if parsed.bsp_install:
        print(f"Wrote {install_bsp(root)}")
        return 0
    state = ServerState(root, parsed.file)
    try:
        state.load()
    except RpcError as exc:                                  # not fatal: the client sees the reason on its first request
        print(f"charpente: warning: {exc.message}", file=sys.stderr)
    if parsed.ws:
        return _serve_websocket(state, parsed.port)

    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    server = StdioServer(Dispatcher(), stdin, stdout)
    server.dispatcher = make_dispatcher(state, server.notify, exit_callback=server.exited.set)
    server.serve_forever()
    return 0

