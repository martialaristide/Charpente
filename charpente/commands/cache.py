"""`charpente cache stats|gc|clear|dir` -- the content cache shared by all workspaces."""
from __future__ import annotations

import argparse
from typing import List

from ..core.cache import LocalCache
from ..units import human_size as human
from ..units import parse_size


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente cache", description="Inspect and maintain the build cache.")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("stats", help="Entries, files and size")
    sub.add_parser("dir", help="Print the cache directory")
    sub.add_parser("clear", help="Delete everything in the cache")
    gc = sub.add_parser("gc", help="Delete the least recently used files until the cache fits")
    gc.add_argument("--max-size", default="5GB", help="Target size (default: 5GB)")
    serve = sub.add_parser("serve", help="Serve a shared cache over HTTP for a team or CI (see docs/shared-cache.md)")
    serve.add_argument("--dir", help="Where the server keeps its files (default: ~/.charpente/cache-server)")
    serve.add_argument("--host", default="127.0.0.1", help="Address to listen on (default: this machine only; anything else needs a token)")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--token-env", default="CHARPENTE_CACHE_SERVER_TOKEN", help="Name of the environment variable holding the bearer token")
    serve.add_argument("--readonly", action="store_true", help="Refuse uploads (a mirror)")
    serve.add_argument("--max-blob", default="1GB", help="Largest file accepted (default: 1GB)")
    sub.add_parser("remote", help="Show the shared cache this machine uses (CHARPENTE_REMOTE_CACHE) and whether it answers")
    parsed = parser.parse_args(args)
    if parsed.action == "serve":
        return _serve(parsed)
    if parsed.action == "remote":
        return _remote_status()

    cache = LocalCache()
    if parsed.action == "dir":
        print(cache.root)
    elif parsed.action == "stats":
        s = cache.stats()
        print(f"{cache.root}\n  {s.entries} entries, {s.blobs} files, {human(s.bytes)}")
    elif parsed.action == "clear":
        cache.clear()
        print(f"Cleared {cache.root}")
    elif parsed.action == "gc":
        freed = cache.gc(parse_size(parsed.max_size))
        print(f"Freed {human(freed)}; now {human(cache.stats().bytes)}.")
    return 0


def _serve(parsed: argparse.Namespace) -> int:
    import os
    from pathlib import Path

    from ..core.cache_server import CacheServer
    from ..dsl.trust import config_dir
    from ._common import CommandError

    token = os.environ.get(parsed.token_env) or None
    try:
        server = CacheServer(Path(parsed.dir) if parsed.dir else config_dir() / "cache-server", host=parsed.host, port=parsed.port, token=token,
                             readonly=parsed.readonly, max_blob=parse_size(parsed.max_blob))
    except ValueError as exc:
        raise CommandError("CH8028", detail=f"{exc}: set the {parsed.token_env} environment variable") from exc
    except OSError as exc:
        raise CommandError("CH8028", detail=f"cannot listen on {parsed.host}:{parsed.port}: {exc}") from exc
    mode = "read-only" if parsed.readonly else "read-write"
    print(f"Charpente cache server ({mode}, {'token required' if token else 'no token'}): {server.url}   files in {server.cache.root}")
    print(f"Clients: CHARPENTE_REMOTE_CACHE={server.url}" + (f" CHARPENTE_REMOTE_CACHE_TOKEN=<the value of {parsed.token_env}>" if token else ""), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(chr(10) + "Stopping.")
    server.shutdown()
    return 0


def _remote_status() -> int:
    import os

    from ..core.remote import REMOTE_ENV, SIGNING_ENV, RemoteCache

    url = os.environ.get(REMOTE_ENV, "").strip()
    if not url:
        print(f"No shared cache: {REMOTE_ENV} is not set (builds use the local cache only).")
        return 0
    remote = RemoteCache(url, token=os.environ.get("CHARPENTE_REMOTE_CACHE_TOKEN") or None)
    health = remote.health()
    print(f"Shared cache: {url}")
    print(f"  answers:  {'yes' if health else 'NO (unreachable, wrong token, or not a Charpente cache)'}")
    if health:
        print(f"  server:   {'read-only' if health.get('readonly') else 'read-write'}")
    print(f"  signing:  {'entries are signed and verified' if os.environ.get(SIGNING_ENV) else 'off (set ' + SIGNING_ENV + ' on every machine)'}")
    print(f"  uploads:  {'disabled (CHARPENTE_REMOTE_CACHE_MODE=readonly)' if os.environ.get('CHARPENTE_REMOTE_CACHE_MODE', '').lower() == 'readonly' else 'enabled'}")
    return 0 if health else 1
