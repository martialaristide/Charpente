"""Mirrors: serve packages to a classroom, an incubator or a company LAN.

`charpente pkg mirror populate DIR` copies everything the workspace's lock file
needs (recipes and verified archives) into a folder laid out as a registry:

    DIR/index.json
    DIR/recipes/<name>-<version>.toml
    DIR/archives/<sha256>.<ext>

`charpente pkg mirror serve DIR` serves that folder over HTTP (with `Range`
support, so interrupted downloads resume). Point machines at it with
`charpente pkg registry add http://HOST:PORT/index.json`: they fetch a package
once from the Internet-connected machine and never again from the Internet.
Recipes served this way point at the mirror's own archives, and every archive is
still verified against the SHA-256 in the recipe, so a mirror cannot substitute
different code.
"""
from __future__ import annotations

import http.server
import json
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import fsutil
from ..dsl.model import Workspace
from ..errors import ChError
from . import lock as lock_mod
from . import materialize
from .store import PackageStore, file_sha256


def _repoint_source(text: str, url: str) -> str:
    """The recipe text with its `[source] url` replaced (indentation preserved)."""
    return re.sub(r'(?m)^(\s*)url\s*=\s*".*"\s*$', lambda m: f'{m.group(1)}url = "{url}"', text, count=1)


def populate(workspace: Workspace, store: PackageStore, destination: Path) -> List[str]:
    root = workspace.root
    lock = lock_mod.load(root)
    if lock is None:
        raise ChError("CH6005", name="(run `charpente pkg install` first)")
    (destination / "recipes").mkdir(parents=True, exist_ok=True)
    (destination / "archives").mkdir(parents=True, exist_ok=True)
    index_path = destination / "index.json"
    try:
        index: Dict[str, Any] = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = {"packages": {}}
    added: List[str] = []
    for name in materialize.reachable(lock, workspace.requires):
        pkg = lock.packages[name]
        recipe, _tree = materialize.load_locked_recipe(pkg, root, store)
        archive = store.archive_path(pkg.source_sha256, pkg.source_url)
        if not archive.exists():
            continue                     # installed from a vendor folder: no archive to share
        archive_dest = destination / "archives" / archive.name
        if not archive_dest.exists():
            shutil.copyfile(archive, archive_dest)
        recipe_src, _ = materialize.locate(pkg, root, store)
        text = recipe_src.read_text(encoding="utf-8")
        # Re-point the source at the mirror's copy. Content changes, so this is a *different recipe
        # digest*; the lock file of a client using the mirror pins the mirror's recipe.
        text = _repoint_source(text, f"../archives/{archive.name}")
        recipe_dest = destination / "recipes" / f"{name}-{pkg.version}.toml"
        fsutil.write_text(recipe_dest, text, newline="\n")
        index["packages"].setdefault(name, {"versions": {}})["versions"][pkg.version] = {
            "recipe": f"recipes/{recipe_dest.name}", "sha256": file_sha256(recipe_dest)}
        added.append(f"{name} {pkg.version}")
    index_path.write_text(json.dumps(index, indent=1, sort_keys=True), encoding="utf-8")
    return added


class _RangeHandler(http.server.SimpleHTTPRequestHandler):
    """Static files with HTTP Range support (resumable downloads)."""

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        rng = self.headers.get("Range")
        path = Path(self.translate_path(self.path))
        if not rng or not path.is_file():
            return super().do_GET()
        match = re.match(r"bytes=(\d+)-(\d*)$", rng.strip())
        size = path.stat().st_size
        if not match or int(match.group(1)) >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return
        start = int(match.group(1))
        end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(path, "rb") as handle:
            handle.seek(start)
            self.wfile.write(handle.read(end - start + 1))


def make_server(directory: Path, host: str = "127.0.0.1", port: int = 0) -> http.server.ThreadingHTTPServer:
    """An HTTP server for `directory`. `host` defaults to loopback: serving a LAN is an explicit choice
    (`--host 0.0.0.0`), because the mirror is unauthenticated."""
    handler = lambda *a, **k: _RangeHandler(*a, directory=str(directory), **k)  # noqa: E731
    return http.server.ThreadingHTTPServer((host, port), handler)


def serve_in_background(directory: Path, host: str = "127.0.0.1", port: int = 0) -> "tuple[http.server.ThreadingHTTPServer, str]":
    server = make_server(directory, host, port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://{host}:{server.server_address[1]}/index.json"


def serve_forever(directory: Path, host: str, port: int, announce: Optional[Any] = None) -> None:
    server = make_server(directory, host, port)
    if announce is not None:
        announce(f"http://{host}:{server.server_address[1]}/index.json")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
