"""JSON-RPC 2.0 for `charpente serve`: message framing, a method dispatcher, and the two transports.

* **stdio** uses LSP/BSP framing (`Content-Length: N\\r\\n\\r\\n<json>`): what editors and build-server clients speak.
* **WebSocket** carries one JSON-RPC message per text frame (see ws.py): what Charpente Studio and the VS Code extension use.

Handlers are plain functions `fn(params) -> result` (requests) or `fn(params)` (notifications); raising `RpcError` returns
a JSON-RPC error, any other exception becomes an internal error that never crashes the server.
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import IO, Any, Callable, Dict, List, Optional

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SERVER_NOT_INITIALIZED = -32002
REQUEST_CANCELLED = -32800

MAX_MESSAGE = 16 * 1024 * 1024

Handler = Callable[[Any], Any]


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code, self.message, self.data = code, message, data

    def to_dict(self) -> Dict[str, Any]:
        error: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error


def encode_message(message: Dict[str, Any]) -> bytes:
    """One message with `Content-Length` framing."""
    body = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


def read_message(stream: IO[bytes]) -> Optional[Dict[str, Any]]:
    """The next framed message from `stream`, or None at end of input. Raises RpcError(PARSE_ERROR) on garbage."""
    length: Optional[int] = None
    bad_length = False
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        name, _, value = line.decode("ascii", "replace").partition(":")
        if name.strip().lower() == "content-length":
            try:
                length = int(value.strip())
            except ValueError:
                bad_length = True                       # finish reading the header block so the next message starts cleanly
    if bad_length:
        raise RpcError(PARSE_ERROR, "invalid Content-Length")
    if length is None or length < 0 or length > MAX_MESSAGE:
        raise RpcError(PARSE_ERROR, "missing or oversized Content-Length")
    body = stream.read(length)
    if len(body) != length:
        return None
    try:
        message = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise RpcError(PARSE_ERROR, f"invalid JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise RpcError(INVALID_REQUEST, "a message is a JSON object")
    return message


class Dispatcher:
    """Routes JSON-RPC requests and notifications to handlers."""

    def __init__(self) -> None:
        self._methods: Dict[str, Handler] = {}
        self._notifications: Dict[str, Handler] = {}
        self._closers: List[Callable[[], None]] = []

    def on_close(self, fn: Callable[[], None]) -> None:
        """Run `fn` when the connection ends (stop what this client started: log streams, terminal commands)."""
        self._closers.append(fn)

    def close(self) -> None:
        closers, self._closers = self._closers, []
        for fn in closers:
            try:
                fn()
            except Exception:
                pass

    def method(self, name: str) -> Callable[[Handler], Handler]:
        def register(fn: Handler) -> Handler:
            self._methods[name] = fn
            return fn
        return register

    def notification(self, name: str) -> Callable[[Handler], Handler]:
        def register(fn: Handler) -> Handler:
            self._notifications[name] = fn
            return fn
        return register

    def add_method(self, name: str, fn: Handler) -> None:
        self._methods[name] = fn

    def add_notification(self, name: str, fn: Handler) -> None:
        self._notifications[name] = fn

    @property
    def method_names(self) -> List[str]:
        return sorted(self._methods)

    def handle(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The response for a request (or None for a notification / a response we do not care about)."""
        if message.get("jsonrpc") != "2.0":
            return _error(message.get("id"), RpcError(INVALID_REQUEST, "jsonrpc must be \"2.0\""))
        method = message.get("method")
        if method is None:
            return None                                             # a response to something we sent
        request_id = message.get("id")
        params = message.get("params")
        if not isinstance(method, str):
            return _error(request_id, RpcError(INVALID_REQUEST, "method must be a string"))
        if "id" not in message:
            handler = self._notifications.get(method)
            if handler is not None:
                try:
                    handler(params)
                except Exception:                                   # a notification has nobody to tell
                    pass
            return None
        handler = self._methods.get(method)
        if handler is None:
            return _error(request_id, RpcError(METHOD_NOT_FOUND, f"method not found: {method}"))
        try:
            return {"jsonrpc": "2.0", "id": request_id, "result": handler(params)}
        except RpcError as exc:
            return _error(request_id, exc)
        except Exception as exc:
            return _error(request_id, RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"))


def _error(request_id: Any, error: RpcError) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": error.to_dict()}


class StdioServer:
    """Reads framed messages from `stdin`, dispatches each request on a worker thread (so a long build never blocks the
    reader, and `$/cancelRequest` can arrive while it runs), writes responses and notifications to `stdout`."""

    def __init__(self, dispatcher: Dispatcher, stdin: IO[bytes], stdout: IO[bytes], workers: int = 8) -> None:
        self.dispatcher = dispatcher
        self._in, self._out = stdin, stdout
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rpc")
        self.exited = threading.Event()

    def send(self, message: Dict[str, Any]) -> None:
        data = encode_message(message)
        with self._lock:
            try:
                self._out.write(data)
                self._out.flush()
            except (OSError, ValueError):
                self.exited.set()

    def notify(self, method: str, params: Any) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def _run(self, message: Dict[str, Any]) -> None:
        response = self.dispatcher.handle(message)
        if response is not None:
            self.send(response)

    def serve_forever(self) -> None:
        while not self.exited.is_set():
            try:
                message = read_message(self._in)
            except RpcError as exc:
                self.send(_error(None, exc))
                continue
            if message is None:
                break
            if message.get("method") == "build/exit":              # BSP: stop reading at once
                self.dispatcher.handle(message)
                break
            if "id" in message and "method" in message:
                self._pool.submit(self._run, message)
            else:
                self.dispatcher.handle(message)
        self._pool.shutdown(wait=True)
        self.dispatcher.close()
        self.exited.set()


class MessageBuffer:
    """Incremental `Content-Length` parser for a byte stream that arrives in arbitrary chunks (a language server's stdout).

    `feed(data)` returns the complete message bodies (raw bytes, not decoded) found so far; garbage raises RpcError(PARSE_ERROR)
    and empties the buffer (the stream cannot be resynchronised reliably).
    """

    def __init__(self) -> None:
        self._data = b""

    def feed(self, data: bytes) -> List[bytes]:
        self._data += data
        out: List[bytes] = []
        while True:
            end = self._data.find(b"\r\n\r\n")
            if end < 0:
                if len(self._data) > 8192:
                    self._data = b""
                    raise RpcError(PARSE_ERROR, "header too long")
                return out
            length: Optional[int] = None
            for line in self._data[:end].split(b"\r\n"):
                name, _, value = line.decode("ascii", "replace").partition(":")
                if name.strip().lower() == "content-length":
                    try:
                        length = int(value.strip())
                    except ValueError:
                        length = None
            if length is None or length < 0 or length > MAX_MESSAGE:
                self._data = b""
                raise RpcError(PARSE_ERROR, "missing or invalid Content-Length")
            start = end + 4
            if len(self._data) < start + length:
                return out
            out.append(self._data[start:start + length])
            self._data = self._data[start + length:]
