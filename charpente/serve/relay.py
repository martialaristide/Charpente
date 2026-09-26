"""Relay a child process that speaks `Content-Length`-framed JSON (a language server, a debug adapter) to a client of `charpente serve`.

The child's messages are forwarded, unread, as notifications `{"id": session, "message": {...}}` under a method name the caller chooses
(`charpente/lsp`, `charpente/dap`); the client's messages go to the child's stdin. Nothing is interpreted, so any feature of the protocol
works, and a child that dies (or a client that leaves) is cleaned up.
"""
from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from ..core import process
from ..errors import ChError
from .rpc import INVALID_PARAMS, MessageBuffer, RpcError, encode_message


class Relays:
    def __init__(self, notify: Callable[[str, Any], None], method: str) -> None:
        self._notify = notify
        self._method = method
        self._sessions: Dict[str, process.Duplex] = {}
        self._lock = threading.Lock()

    def start(self, argv: Sequence[str], *, cwd: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> str:
        ident = uuid.uuid4().hex[:12]
        buffer = MessageBuffer()

        def on_data(chunk: bytes) -> None:
            try:
                bodies = buffer.feed(chunk)
            except RpcError:
                return
            for body in bodies:
                try:
                    message = json.loads(body.decode("utf-8"))
                except ValueError:
                    continue
                self._notify(self._method, {"id": ident, "message": message})

        def on_exit(code: int) -> None:
            with self._lock:
                self._sessions.pop(ident, None)
            self._notify(self._method, {"id": ident, "exit": code})

        try:
            duplex = process.Duplex(list(argv), on_data, on_exit, cwd=cwd, env=env)
        except ChError as exc:
            raise RpcError(INVALID_PARAMS, f"[{exc.code}] {exc}", {"code": exc.code}) from exc
        with self._lock:
            self._sessions[ident] = duplex
        return ident

    def send(self, ident: str, message: Any) -> bool:
        with self._lock:
            duplex = self._sessions.get(ident)
        if duplex is None:
            raise RpcError(INVALID_PARAMS, "unknown or finished session")
        if not isinstance(message, dict):
            raise RpcError(INVALID_PARAMS, "message must be a JSON object")
        return duplex.write(encode_message(message))

    def stop(self, ident: str) -> bool:
        with self._lock:
            duplex = self._sessions.pop(ident, None)
        if duplex is not None:
            duplex.stop()
        return duplex is not None

    def close(self) -> None:
        with self._lock:
            sessions, self._sessions = list(self._sessions.values()), {}
        for duplex in sessions:
            duplex.stop()
