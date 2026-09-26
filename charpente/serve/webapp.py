"""Serving Charpente Studio's static pages: a tiny, strict HTTP handler for the WebSocket server (same port).

Only files inside the Studio folder are served, read-only, with a Content-Security-Policy that lets the page talk to nothing but this
server. The pages carry no secret (the WebSocket token is in the URL the command printed, and only the WebSocket checks it).
"""
from __future__ import annotations

import mimetypes
import urllib.parse
from pathlib import Path
from typing import Callable, Dict, Tuple

from .ws import HttpHandler

WEB_DIR = Path(__file__).resolve().parent.parent / "studio_web"

_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json; charset=utf-8",
          ".ico": "image/x-icon", ".png": "image/png", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}


def content_type(path: Path) -> str:
    return _TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def security_headers(port: int) -> Dict[str, str]:
    return {
        "Content-Security-Policy": ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                                    f"font-src 'self'; connect-src ws://127.0.0.1:{port} ws://localhost:{port}; base-uri 'none'; "
                                    "form-action 'none'; frame-ancestors 'none'"),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }


def resolve(web_dir: Path, target: str) -> Path:
    """The file for a request target, or raise FileNotFoundError (also for anything that would leave `web_dir`)."""
    path = urllib.parse.unquote(urllib.parse.urlparse(target).path)
    if path in ("", "/"):
        path = "/index.html"
    parts = [p for p in path.split("/") if p]
    if any(p in (".", "..") or "\\" in p or ":" in p or p.startswith(".") for p in parts):
        raise FileNotFoundError(target)
    base = web_dir.resolve()
    candidate = base.joinpath(*parts).resolve()
    if base not in candidate.parents or not candidate.is_file():
        raise FileNotFoundError(target)
    return candidate


def make_http_handler(web_dir: Path, port: Callable[[], int]) -> HttpHandler:
    def handle(method: str, target: str, headers: Dict[str, str]) -> Tuple[int, Dict[str, str], bytes]:
        if method not in ("GET", "HEAD"):
            return 405, {"Allow": "GET, HEAD", "Content-Type": "text/plain; charset=utf-8"}, b"Method Not Allowed"
        try:
            file = resolve(web_dir, target)
        except FileNotFoundError:
            return 404, {"Content-Type": "text/plain; charset=utf-8", **security_headers(port())}, b"Not Found"
        return 200, {"Content-Type": content_type(file), **security_headers(port())}, file.read_bytes()
    return handle
