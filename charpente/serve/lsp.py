"""A language server (clangd) for Studio's editor, relayed over the connection Studio already has.

Studio speaks LSP itself; this only starts `clangd` for the project (reading a compilation database written from the engine's own compile
arguments) and relays messages (see relay.py). Nothing is interpreted here, so any LSP feature clangd offers works, and any other server
could be plugged in.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .relay import Relays
from .rpc import INVALID_PARAMS, RpcError


def find_server(which: Callable[[str], Optional[str]] = shutil.which) -> Optional[str]:
    for name in ("clangd", "clangd-18", "clangd-17", "clangd-16", "clangd-15", "clangd-14"):
        found = which(name)
        if found:
            return found
    return None


def write_compile_commands(root: Path, entries: List[Dict[str, Any]]) -> Path:
    """The compilation database clangd reads, kept out of the project root (under the build folder)."""
    folder = root / "build" / "clangd"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "compile_commands.json"
    text = json.dumps(entries, indent=1)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


class LspSessions:
    """The language-server processes one client connection started."""

    def __init__(self, root: Path, notify: Callable[[str, Any], None], which: Callable[[str], Optional[str]] = shutil.which) -> None:
        self.root = root
        self._which = which
        self._relays = Relays(notify, "charpente/lsp")

    def start(self, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        server = find_server(self._which)
        if server is None:
            raise RpcError(INVALID_PARAMS, "clangd is not installed (install LLVM's clangd, or run `charpente doctor`): "
                                           "Studio's editor still works, without completion from the compiler")
        database = write_compile_commands(self.root, entries)
        ident = self._relays.start([server, f"--compile-commands-dir={database.parent}", "--background-index=false", "--log=error"], cwd=str(self.root))
        return {"id": ident, "server": Path(server).name, "compileCommands": str(database)}

    def send(self, ident: str, message: Any) -> bool:
        return self._relays.send(ident, message)

    def stop(self, ident: str) -> bool:
        return self._relays.stop(ident)

    def close(self) -> None:
        self._relays.close()
