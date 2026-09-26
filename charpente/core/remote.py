"""The client side of the shared cache: a `RemoteCache` speaking to `charpente cache serve`, and a `TieredCache` that puts it behind the local cache.

Lookup order is local, then remote; a remote hit is copied into the local cache (blobs verified against their digests, entries against the shared signing key
when one is configured), so the second time it is a local hit. Stores go to the local cache first and are pushed to the remote in the background. **Fail open**:
a remote that is down, slow or refusing never fails a build -- it is skipped for a while and the build continues locally, with one warning.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..errors import ChError
from . import hashing
from .cache import CacheEntry, LocalCache

REMOTE_ENV = "CHARPENTE_REMOTE_CACHE"
TOKEN_ENV = "CHARPENTE_REMOTE_CACHE_TOKEN"
SIGNING_ENV = "CHARPENTE_CACHE_SIGNING_KEY"
MODE_ENV = "CHARPENTE_REMOTE_CACHE_MODE"        # "readonly" (default: readwrite)
INSECURE_ENV = "CHARPENTE_REMOTE_CACHE_INSECURE"
BACKOFF_SECONDS = 30.0
LOOPBACK = ("127.0.0.1", "localhost", "::1", "[::1]")


def sign_entry(data: Dict[str, Any], key: str) -> str:
    """HMAC-SHA256 of the entry (without its own signature) under the shared key."""
    payload = json.dumps({k: v for k, v in data.items() if k != "sig"}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def entry_is_valid(data: Dict[str, Any], key: Optional[str]) -> bool:
    if key is None:
        return True
    sig = data.get("sig")
    return isinstance(sig, str) and hmac.compare_digest(sig, sign_entry(data, key))


class RemoteCache:
    def __init__(self, url: str, *, token: Optional[str] = None, signing_key: Optional[str] = None, readonly: bool = False, timeout: float = 10.0) -> None:
        self.url = url.rstrip("/")
        self.token, self.signing_key, self.readonly, self.timeout = token, signing_key, readonly, timeout
        self.down_until = 0.0
        self.warned = False
        self.warnings: List[str] = []
        self.rejected = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ transport
    def _request(self, method: str, kind: str, name: str, body: Optional[bytes] = None) -> Optional[bytes]:
        """The response body, b"" for an empty success, None for 404 and for anything that means "not available" (which also pauses the remote)."""
        if time.monotonic() < self.down_until:
            return None
        url = f"{self.url}/{kind}/{urllib.parse.quote(name.replace(':', '-'), safe='')}"
        request = urllib.request.Request(url, data=body, method=method)
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        if body is not None:
            request.add_header("Content-Type", "application/octet-stream")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read() if method != "HEAD" else b""
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            self._down(f"the shared cache answered {exc.code} {exc.reason}")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self._down(f"the shared cache is unreachable ({getattr(exc, 'reason', exc)})")
        return None

    def _down(self, why: str) -> None:
        with self._lock:
            self.down_until = time.monotonic() + BACKOFF_SECONDS
            if not self.warned:
                self.warned = True
                self.warnings.append(f"{why}: building without it for now")

    def health(self) -> Optional[Dict[str, Any]]:
        request = urllib.request.Request(f"{self.url}/health")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
                return data if isinstance(data, dict) and "charpente-cache" in data else None
        except (urllib.error.URLError, OSError, ValueError):
            return None

    # ------------------------------------------------------------------ entries, manifests, blobs
    def get_entry(self, key: str) -> Optional[Dict[str, Any]]:
        body = self._request("GET", "ac", key)
        if not body:
            return None
        try:
            data = json.loads(body.decode("utf-8"))
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        if not entry_is_valid(data, self.signing_key):
            self.rejected += 1
            with self._lock:
                self.warnings.append(f"a shared-cache entry for {hashing.short(key)} has no valid signature: ignored")
            return None
        return data

    def put_entry(self, key: str, data: Dict[str, Any]) -> bool:
        if self.readonly:
            return False
        signed = dict(data)
        if self.signing_key:
            signed["sig"] = sign_entry(signed, self.signing_key)
        return self._request("PUT", "ac", key, json.dumps(signed).encode("utf-8")) is not None

    def get_manifest(self, key1: str) -> List[List[str]]:
        body = self._request("GET", "mf", key1)
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
            return [list(map(str, deps)) for deps in data.get("header_sets", [])]
        except (ValueError, AttributeError, TypeError):
            return []

    def put_manifest(self, key1: str, sets: Sequence[Sequence[str]]) -> bool:
        return not self.readonly and self._request("PUT", "mf", key1, json.dumps({"header_sets": [list(s) for s in sets]}).encode("utf-8")) is not None

    def has_blob(self, digest: str) -> bool:
        return self._request("HEAD", "cas", digest) is not None

    def get_blob(self, digest: str, destination: Path) -> bool:
        """Download a blob to `destination`, verified against its digest (a corrupt or substituted file is discarded)."""
        body = self._request("GET", "cas", digest)
        if body is None:
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(destination.parent), prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
            if hashing.digest_file(tmp) != digest:
                with self._lock:
                    self.warnings.append(f"the shared cache returned a wrong file for {hashing.short(digest)}: ignored")
                Path(tmp).unlink(missing_ok=True)
                return False
            os.replace(tmp, destination)
            return True
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            return False

    def put_blob(self, digest: str, path: Path) -> bool:
        if self.readonly:
            return False
        try:
            data = path.read_bytes()
        except OSError:
            return False
        return self._request("PUT", "cas", digest, data) is not None


class TieredCache:
    """`LocalCache`'s interface, with a shared cache behind it. See the module docstring."""

    def __init__(self, local: LocalCache, remote: RemoteCache, *, push: Optional[Callable[[Callable[[], None]], None]] = None) -> None:
        self.local = local
        self.remote = remote
        self.root = local.root
        self.remote_hits = 0
        self._remote_keys: set = set()  # type: ignore[type-arg]
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cache-push")
        self._pending: List[Any] = []
        self._lock = threading.Lock()

    # counters the engine and stats read
    @property
    def hits(self) -> int:
        return self.local.hits

    @property
    def misses(self) -> int:
        return self.local.misses

    def origin(self, key: str) -> str:
        with self._lock:
            return "remote" if key in self._remote_keys else "local"

    # ------------------------------------------------------------------ lookup
    def lookup(self, key: str) -> Optional[CacheEntry]:
        entry = self.local.lookup(key)
        if entry is not None:
            return entry
        data = self.remote.get_entry(key)
        if data is None:
            return None
        try:
            outputs = data["outputs"]
            digests = [str(o["digest"]) for o in outputs]
        except (KeyError, TypeError):
            return None
        for digest in digests:
            blob = self.local._blob(digest)
            if not blob.is_file() and not self.remote.get_blob(digest, blob):
                return None
        self.local.write_entry(key, data)
        entry = self.local.lookup(key)
        if entry is not None:
            with self._lock:
                self.remote_hits += 1
                self._remote_keys.add(key)
        return entry

    def restore(self, entry: CacheEntry, destinations: Sequence[Path]) -> bool:
        return self.local.restore(entry, destinations)

    def manifest(self, key1: str) -> List[List[str]]:
        sets = self.local.manifest(key1)
        if sets:
            return sets
        remote = self.remote.get_manifest(key1)
        for deps in reversed(remote):
            self.local.add_to_manifest(key1, deps)
        return remote

    # ------------------------------------------------------------------ store
    def store(self, key: str, outputs: Sequence[Path], stdout: str = "", stderr: str = "", duration: float = 0.0) -> bool:
        stored = self.local.store(key, outputs, stdout=stdout, stderr=stderr, duration=duration)
        if stored and not self.remote.readonly:
            self._submit(lambda: self._push_entry(key))
        return stored

    def add_to_manifest(self, key1: str, deps: Sequence[str]) -> None:
        self.local.add_to_manifest(key1, deps)
        if not self.remote.readonly:
            self._submit(lambda: self._push_manifest(key1))

    def _submit(self, job: Callable[[], None]) -> None:
        future = self._pool.submit(job)
        with self._lock:
            self._pending = [f for f in self._pending if not f.done()] + [future]

    def _push_entry(self, key: str) -> None:
        try:
            data = json.loads(self.local._entry_path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for output in data.get("outputs", []):
            digest = str(output.get("digest", ""))
            if digest and not self.remote.has_blob(digest):
                if not self.remote.put_blob(digest, self.local._blob(digest)):
                    return
        self.remote.put_entry(key, data)

    def _push_manifest(self, key1: str) -> None:
        self.remote.put_manifest(key1, self.local.manifest(key1))

    def flush(self, timeout: float = 120.0) -> None:
        """Wait for background uploads (called when a build ends, so a short-lived process does not drop them)."""
        with self._lock:
            pending = list(self._pending)
        end = time.monotonic() + timeout
        for future in pending:
            try:
                future.result(timeout=max(end - time.monotonic(), 0.0))
            except Exception:
                pass

    # ------------------------------------------------------------------ maintenance passthrough
    def stats(self) -> Any:
        return self.local.stats()

    def gc(self, max_bytes: int) -> int:
        return self.local.gc(max_bytes)

    def clear(self) -> None:
        self.local.clear()


def from_environment(local: LocalCache, env: Optional[Dict[str, str]] = None) -> "LocalCache | TieredCache":
    """`local`, or a `TieredCache` when CHARPENTE_REMOTE_CACHE names a shared cache.

    A plain-HTTP shared cache on another machine is refused unless entries are signed (CHARPENTE_CACHE_SIGNING_KEY) or you accept the risk
    explicitly (CHARPENTE_REMOTE_CACHE_INSECURE=1): without a signature anyone on the path could substitute the outputs of your builds.
    """
    env = dict(os.environ if env is None else env)
    url = env.get(REMOTE_ENV, "").strip()
    if not url:
        return local
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ChError("CH8028", detail=f"{REMOTE_ENV}={url!r} is not an http(s) address")
    signing = env.get(SIGNING_ENV) or None
    if parsed.scheme == "http" and parsed.hostname not in LOOPBACK and not signing and env.get(INSECURE_ENV) != "1":
        raise ChError("CH8028", detail=f"{url} is plain HTTP on another machine and its entries are not signed: set {SIGNING_ENV} (recommended), use https, "
                                       f"or set {INSECURE_ENV}=1 if you accept that anyone on the network path can alter your build outputs")
    remote = RemoteCache(url, token=env.get(TOKEN_ENV) or None, signing_key=signing, readonly=env.get(MODE_ENV, "").lower() == "readonly")
    return TieredCache(local, remote)
