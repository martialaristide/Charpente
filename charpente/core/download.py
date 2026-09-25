"""Downloads that survive bad networks: resumable, verified, budgeted.

Built for places where a connection is slow, metered or drops: an interrupted
transfer continues from where it stopped (HTTP `Range`), every file is checked
against its published SHA-256 before it is used, and a byte budget can refuse
a download that would cost more than the user allowed. `CHARPENTE_OFFLINE=1`
forbids the network entirely (local `file://` sources still work).
"""
from __future__ import annotations

import hashlib
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from ..errors import ChError

OFFLINE_ENV = "CHARPENTE_OFFLINE"
Progress = Callable[[int, Optional[int]], None]
Opener = Callable[..., Any]


def offline() -> bool:
    return os.environ.get(OFFLINE_ENV, "").strip().lower() in ("1", "true", "yes")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(
    url: str,
    dest: Path,
    *,
    sha256: Optional[str] = None,
    max_bytes: Optional[int] = None,
    retries: int = 3,
    timeout: float = 30.0,
    progress: Optional[Progress] = None,
    opener: Optional[Opener] = None,
    backoff: float = 0.5,
) -> Path:
    """Fetch `url` to `dest` (atomically: `dest` only appears once complete and
    verified). Raises CH6001 (transfer failed), CH6002 (checksum mismatch),
    CH6003 (over budget) or CH6004 (offline mode)."""
    parsed = urllib.parse.urlparse(url)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if parsed.scheme in ("http", "https") and offline():
        raise ChError("CH6004", url=url)
    if parsed.scheme not in ("http", "https", "file"):
        raise ChError("CH6001", url=url, detail=f"unsupported scheme {parsed.scheme!r}")

    part = dest.with_name(dest.name + ".part")
    last_error = ""
    for attempt in range(retries + 1):
        try:
            _transfer(url, part, max_bytes, timeout, progress, opener or urllib.request.urlopen)
            break
        except ChError:
            raise
        except (urllib.error.URLError, OSError, TimeoutError, ConnectionError) as exc:
            last_error = str(getattr(exc, "reason", exc))
            if attempt == retries:
                raise ChError("CH6001", url=url, detail=last_error) from exc
            time.sleep(backoff * (2 ** attempt))
    if sha256 is not None:
        actual = sha256_file(part)
        if actual.lower() != sha256.lower():
            try:
                part.unlink()
            except OSError:
                pass
            raise ChError("CH6002", url=url, expected=sha256.lower(), actual=actual)
    os.replace(part, dest)
    return dest


def _transfer(url: str, part: Path, max_bytes: Optional[int], timeout: float,
              progress: Optional[Progress], opener: Opener) -> None:
    have = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "charpente"}
    if have:
        headers["Range"] = f"bytes={have}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        response = opener(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and have:              # asked past the end: the part file is already complete
            return
        raise
    with response:
        status = getattr(response, "status", 200)
        length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
        total_remaining = int(length) if length and length.isdigit() else None
        resumed = status == 206 and have > 0
        if not resumed:
            have = 0                                # the server ignored Range: start again
        total = (have + total_remaining) if total_remaining is not None else None
        if max_bytes is not None and total is not None and total > max_bytes:
            raise ChError("CH6003", url=url, size=total, budget=max_bytes)
        mode = "ab" if resumed else "wb"
        received = have
        with open(part, mode) as out:
            while True:
                block = response.read(1 << 16)
                if not block:
                    break
                received += len(block)
                if max_bytes is not None and received > max_bytes:
                    raise ChError("CH6003", url=url, size=received, budget=max_bytes)
                out.write(block)
                if progress is not None:
                    progress(received, total)
        if total is not None and received < total:
            raise ConnectionError(f"connection closed after {received} of {total} bytes")
