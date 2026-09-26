"""A small WebSocket server (RFC 6455, the subset a JSON-RPC client needs) built on the standard library.

Text frames carry one JSON-RPC message each. It listens on the loopback address only, and every connection must present
the server's random token (`ws://127.0.0.1:PORT/?token=...`): other local users' programs and web pages cannot talk to a
build server that can run code. Browsers' `Origin` is checked too (a page from another site cannot connect even if it
guessed the port). No TLS: loopback traffic never leaves the machine.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import socket
import socketserver
import struct
import threading
import urllib.parse
from typing import Callable, Dict, List, Optional, Tuple

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
MAX_MESSAGE = 16 * 1024 * 1024
ALLOWED_ORIGIN_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
ALLOWED_ORIGIN_SCHEMES = {"vscode-webview", "vscode-file", "tauri", "app"}


class WsError(Exception):
    def __init__(self, message: str, close_code: int = 1002) -> None:
        super().__init__(message)
        self.close_code = close_code


def accept_key(client_key: str) -> str:
    return base64.b64encode(hashlib.sha1((client_key + GUID).encode("ascii")).digest()).decode("ascii")


def encode_frame(opcode: int, payload: bytes, *, mask: bool = False, mask_key: bytes = b"\x00\x00\x00\x00") -> bytes:
    """One unfragmented frame. Servers send unmasked frames; `mask=True` builds what a client sends (tests, client code)."""
    head = bytes([0x80 | opcode])
    size = len(payload)
    flag = 0x80 if mask else 0
    if size < 126:
        head += bytes([flag | size])
    elif size < 65536:
        head += bytes([flag | 126]) + struct.pack(">H", size)
    else:
        head += bytes([flag | 127]) + struct.pack(">Q", size)
    if mask:
        return head + mask_key + bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return head + payload


class FrameDecoder:
    """Turns bytes from a client into complete messages `(opcode, payload)`; reassembles fragmented messages."""

    def __init__(self, require_mask: bool = True, max_message: int = MAX_MESSAGE) -> None:
        self._buffer = b""
        self._require_mask = require_mask
        self._max = max_message
        self._fragments: List[bytes] = []
        self._fragment_opcode = 0

    def feed(self, data: bytes) -> List[Tuple[int, bytes]]:
        self._buffer += data
        messages: List[Tuple[int, bytes]] = []
        while True:
            frame = self._take()
            if frame is None:
                return messages
            fin, opcode, payload = frame
            if opcode >= 0x8:                                   # control frames are never fragmented
                if not fin or len(payload) > 125:
                    raise WsError("invalid control frame")
                messages.append((opcode, payload))
                continue
            if opcode == OP_CONT:
                if not self._fragments:
                    raise WsError("continuation without a start")
            elif self._fragments:
                raise WsError("new message inside a fragmented one")
            else:
                self._fragment_opcode = opcode
            self._fragments.append(payload)
            if sum(len(f) for f in self._fragments) > self._max:
                raise WsError("message too big", 1009)
            if fin:
                messages.append((self._fragment_opcode, b"".join(self._fragments)))
                self._fragments = []

    def _take(self) -> Optional[Tuple[bool, int, bytes]]:
        buf = self._buffer
        if len(buf) < 2:
            return None
        fin, opcode = bool(buf[0] & 0x80), buf[0] & 0x0F
        if buf[0] & 0x70:
            raise WsError("reserved bits set")
        masked, size, offset = bool(buf[1] & 0x80), buf[1] & 0x7F, 2
        if self._require_mask and not masked:
            raise WsError("client frames must be masked")
        if size == 126:
            if len(buf) < 4:
                return None
            size, offset = struct.unpack(">H", buf[2:4])[0], 4
        elif size == 127:
            if len(buf) < 10:
                return None
            size, offset = struct.unpack(">Q", buf[2:10])[0], 10
        if size > self._max:
            raise WsError("frame too big", 1009)
        key = b""
        if masked:
            if len(buf) < offset + 4:
                return None
            key, offset = buf[offset:offset + 4], offset + 4
        if len(buf) < offset + size:
            return None
        payload = buf[offset:offset + size]
        if masked:
            payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
        self._buffer = buf[offset + size:]
        return fin, opcode, payload


def parse_request(data: bytes) -> Tuple[str, str, Dict[str, str]]:
    """(method, target, lower-cased headers) of an HTTP/1.1 request head."""
    head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1")
    lines = head.split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) != 3 or not parts[2].startswith("HTTP/1."):
        raise WsError("not an HTTP request")
    headers: Dict[str, str] = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if name:
            headers[name.strip().lower()] = value.strip()
    return parts[0], parts[1], headers


def origin_allowed(origin: Optional[str]) -> bool:
    if not origin:
        return True                                             # not a browser
    parsed = urllib.parse.urlparse(origin)
    return parsed.scheme in ALLOWED_ORIGIN_SCHEMES or (parsed.scheme in ("http", "https") and parsed.hostname in
                                                     {h.strip("[]") for h in ALLOWED_ORIGIN_HOSTS})


def check_upgrade(method: str, target: str, headers: Dict[str, str], token: str) -> Tuple[int, str]:
    """(HTTP status, reason) for a handshake: 101 when acceptable."""
    if method != "GET":
        return 405, "Method Not Allowed"
    if headers.get("upgrade", "").lower() != "websocket" or "upgrade" not in headers.get("connection", "").lower():
        return 426, "Upgrade Required"
    if headers.get("sec-websocket-version") != "13" or not headers.get("sec-websocket-key"):
        return 400, "Bad Request"
    if not origin_allowed(headers.get("origin")):
        return 403, "Forbidden"
    supplied = urllib.parse.parse_qs(urllib.parse.urlparse(target).query).get("token", [""])[0]
    if not hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
        return 401, "Unauthorized"
    return 101, "Switching Protocols"


def http_response(status: int, reason: str, headers: Optional[Dict[str, str]] = None, body: str = "") -> bytes:
    lines = [f"HTTP/1.1 {status} {reason}"]
    if status != 101:                                            # a handshake response has no body and no length
        lines.append("Content-Length: %d" % len(body.encode("utf-8")))
    lines += [f"{k}: {v}" for k, v in (headers or {}).items()]
    return ("\r\n".join(lines) + "\r\n\r\n" + body).encode("utf-8")


class Connection:
    """A connected client: `send_text` is thread-safe."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._lock = threading.Lock()
        self.closed = False

    def send_text(self, text: str) -> None:
        self._send(encode_frame(OP_TEXT, text.encode("utf-8")))

    def send_close(self, code: int = 1000) -> None:
        self._send(encode_frame(OP_CLOSE, struct.pack(">H", code)))
        self.closed = True

    def _send(self, data: bytes) -> None:
        with self._lock:
            try:
                self._sock.sendall(data)
            except OSError:
                self.closed = True


class WebSocketServer:
    """`on_connect(connection)` returns the callback `on_message(text)`; `on_close(connection)` runs at disconnect."""

    def __init__(self, token: str, on_connect: Callable[[Connection], Callable[[str], None]],
                 on_close: Callable[[Connection], None] = lambda c: None, host: str = "127.0.0.1", port: int = 0) -> None:
        outer = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                outer._serve(self.request)

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self._token = token
        self._on_connect, self._on_close = on_connect, on_close
        self._server = Server((host, port), Handler)
        address = self._server.server_address
        self.host, self.port = str(address[0]), int(address[1])
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}/?token={self._token}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="ws-accept")
        self._thread.start()

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _serve(self, sock: socket.socket) -> None:
        sock.settimeout(30)
        data = b""
        try:
            while b"\r\n\r\n" not in data and len(data) < 65536:
                chunk = sock.recv(4096)
                if not chunk:
                    return
                data += chunk
            head, _, rest = data.partition(b"\r\n\r\n")
            method, target, headers = parse_request(head + b"\r\n\r\n")
            status, reason = check_upgrade(method, target, headers, self._token)
            if status != 101:
                sock.sendall(http_response(status, reason, {"Connection": "close"}, reason))
                return
            sock.sendall(http_response(101, reason, {"Upgrade": "websocket", "Connection": "Upgrade",
                                                     "Sec-WebSocket-Accept": accept_key(headers["sec-websocket-key"])}))
        except (OSError, WsError):
            return
        sock.settimeout(None)
        connection = Connection(sock)
        on_message = self._on_connect(connection)
        decoder = FrameDecoder()
        try:
            pending = rest
            while not connection.closed:
                for opcode, payload in decoder.feed(pending):
                    if opcode == OP_TEXT:
                        on_message(payload.decode("utf-8", "replace"))
                    elif opcode == OP_PING:
                        connection._send(encode_frame(OP_PONG, payload))
                    elif opcode == OP_CLOSE:
                        connection.send_close()
                        return
                pending = sock.recv(65536)
                if not pending:
                    return
        except WsError as exc:
            connection.send_close(exc.close_code)
        except OSError:
            pass
        finally:
            connection.closed = True
            self._on_close(connection)
