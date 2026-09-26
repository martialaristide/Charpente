"""A shared build-cache server: the same content-addressed layout as the local cache, over HTTP, for a team's LAN or a CI fleet.

    GET|HEAD /cas/<digest>   a file, named by its digest (the body must hash to the name: checked on upload)
    GET|PUT  /ac/<key>       what an action key produced (a small JSON record)
    GET|PUT  /mf/<key>       the header sets seen for an action
    GET      /health         {"charpente-cache": 1, "readonly": ...}

Security, by default: it listens on the loopback address only; to serve other machines you must give `--host` and a token (a bearer token read from an environment
variable, never from a file or the command line). Uploads are size-limited and content-checked, names are restricted to safe characters, nothing outside the cache
folder can be reached. There is **no TLS**: on an untrusted network put it behind a TLS proxy, and set `CHARPENTE_CACHE_SIGNING_KEY` on the clients so an entry a
stranger wrote (or a man in the middle altered) is rejected. A cache server is trusted with build outputs: a compromised one can serve wrong binaries for keys
whose entries are not signed.
"""
from __future__ import annotations

import hmac
import json
import re
import socketserver
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional, Tuple

from .cache import LocalCache

MAX_ENTRY_BYTES = 1 << 20
MAX_BLOB_BYTES = 1 << 30
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_KINDS = ("ac", "cas", "mf")


def digest_for(prefix: str, data: bytes) -> Optional[str]:
    """`data`'s digest with the algorithm named by `prefix` ('b3' or 'b2'), or None when this machine lacks that algorithm."""
    import hashlib

    if prefix == "b2":
        return "b2:" + hashlib.blake2b(data, digest_size=32).hexdigest()
    if prefix == "b3":
        try:
            import blake3  # type: ignore[import-not-found,unused-ignore]
        except ImportError:
            return None
        return "b3:" + blake3.blake3(data).hexdigest()
    return None


class CacheServer:
    def __init__(self, root: Path, *, host: str = "127.0.0.1", port: int = 0, token: Optional[str] = None, readonly: bool = False,
                 max_blob: int = MAX_BLOB_BYTES) -> None:
        if host not in ("127.0.0.1", "localhost", "::1") and not token:
            raise ValueError("a cache server that listens beyond this machine needs a token")
        self.cache = LocalCache(root)
        self.token, self.readonly, self.max_blob = token, readonly, max_blob
        self.requests = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "charpente-cache"
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                pass

            def do_GET(self) -> None:
                outer._handle(self, "GET")

            def do_HEAD(self) -> None:
                outer._handle(self, "HEAD")

            def do_PUT(self) -> None:
                outer._handle(self, "PUT")

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self._server: socketserver.BaseServer = Server((host, port), Handler)
        self.host, self.port = str(self._server.server_address[0]), int(self._server.server_address[1])
        self._thread: Optional[threading.Thread] = None
        self._serving = False
        self._closed = False

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="cache-server")
        self._thread.start()

    def serve_forever(self) -> None:
        self._serving = True
        self._server.serve_forever()

    def shutdown(self) -> None:
        """Stop serving (if it ever started) and release the port. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        if self._thread is not None or self._serving:
            self._server.shutdown()
        self._server.server_close()

    # ------------------------------------------------------------------ requests
    def _reply(self, handler: BaseHTTPRequestHandler, status: int, body: bytes = b"", content_type: str = "text/plain", head: bool = False) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        if not head and body:
            handler.wfile.write(body)

    def _authorised(self, handler: BaseHTTPRequestHandler) -> bool:
        if self.token is None:
            return True
        header = handler.headers.get("Authorization", "")
        supplied = header[7:] if header.lower().startswith("bearer ") else ""
        return hmac.compare_digest(supplied.encode("utf-8"), self.token.encode("utf-8"))

    def _path_for(self, kind: str, name: str) -> Path:
        cache = self.cache
        return {"cas": cache._blob, "ac": cache._entry_path, "mf": cache._manifest_path}[kind](name)

    def _handle(self, handler: BaseHTTPRequestHandler, method: str) -> None:
        self.requests += 1
        head = method == "HEAD"
        parsed = urllib.parse.urlparse(handler.path)
        parts = [urllib.parse.unquote(p) for p in parsed.path.split("/") if p]
        length = int(handler.headers.get("Content-Length") or 0)
        try:
            if not self._authorised(handler):
                handler.rfile.read(min(length, 1 << 16))
                self._reply(handler, 401, b"unauthorized", head=head)
                return
            if parts == ["health"]:
                self._reply(handler, 200, json.dumps({"charpente-cache": 1, "readonly": self.readonly}).encode(), "application/json", head)
                return
            if len(parts) != 2 or parts[0] not in _KINDS or not _NAME.match(parts[1]):
                handler.rfile.read(min(length, 1 << 16))
                self._reply(handler, 404, b"not found", head=head)
                return
            kind, name = parts
            if method in ("GET", "HEAD"):
                self._get(handler, kind, name, head)
            else:
                self._put(handler, kind, name, length)
        except (ConnectionError, OSError):
            return

    def _get(self, handler: BaseHTTPRequestHandler, kind: str, name: str, head: bool) -> None:
        path = self._path_for(kind, name)
        try:
            data = path.read_bytes()
        except OSError:
            self._reply(handler, 404, b"not found", head=head)
            return
        if kind == "cas" and not head:
            self.cache._touch(path)                                       # recency drives eviction
        self._reply(handler, 200, data, "application/octet-stream" if kind == "cas" else "application/json", head)
        if head:
            pass

    def _put(self, handler: BaseHTTPRequestHandler, kind: str, name: str, length: int) -> None:
        limit = self.max_blob if kind == "cas" else MAX_ENTRY_BYTES
        if self.readonly:
            handler.rfile.read(min(length, 1 << 16))
            self._reply(handler, 403, b"this cache is read-only")
            return
        if length <= 0 or length > limit:
            handler.rfile.read(min(length, 1 << 16))
            self._reply(handler, 413 if length > limit else 411, b"bad size")
            return
        body = handler.rfile.read(length)
        if len(body) != length:
            self._reply(handler, 400, b"truncated body")
            return
        if kind == "cas":
            prefix = name.split("-", 1)[0].split(":", 1)[0]
            actual = digest_for(prefix, body)
            if actual is None:
                self._reply(handler, 415, b"unsupported digest algorithm")
                return
            if actual.replace(":", "-") != name.replace(":", "-"):
                self._reply(handler, 400, b"the body does not hash to its name")
                return
        else:
            try:
                data = json.loads(body.decode("utf-8"))
            except ValueError:
                self._reply(handler, 400, b"not JSON")
                return
            if not isinstance(data, dict):
                self._reply(handler, 400, b"not an object")
                return
        path = self._path_for(kind, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
        try:
            with open(fd, "wb") as handle:
                handle.write(body)
            Path(tmp).replace(path)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            self._reply(handler, 500, b"cannot store")
            return
        self._reply(handler, 201, b"stored")


def parse_bind(text: str) -> Tuple[str, int]:
    host, _, port = text.rpartition(":")
    return (host or "127.0.0.1"), int(port)
