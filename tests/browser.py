"""Drive a real headless Chromium-family browser (Edge or Chrome) through the DevTools protocol, for Studio's end-to-end tests.

Nothing here is a dependency of Charpente: it is test support built on the standard library and the repository's own WebSocket code.
`find_browser()` returns None when no browser is installed, and the tests that need one are skipped (never faked).
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from charpente.serve import ws

CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/microsoft-edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def find_browser() -> Optional[str]:
    for name in ("msedge", "google-chrome", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return None


class Cdp:
    """One page of a headless browser."""

    def __init__(self, executable: str, width: int = 1400, height: int = 900) -> None:
        self.profile = tempfile.mkdtemp(prefix="charpente-browser-")
        self.process = subprocess.Popen(
            [executable, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check",
             "--lang=en-US", "--accept-lang=en-US", "--disable-gpu", "--disable-extensions", "--disable-background-networking", "--disable-sync", f"--window-size={width},{height}", "about:blank"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = Path(self.profile) / "DevToolsActivePort"
        deadline = time.time() + 40
        while not port_file.exists():
            if time.time() > deadline or self.process.poll() is not None:
                self.close()
                raise RuntimeError("the browser did not start")
            time.sleep(0.1)
        self.port = int(port_file.read_text().split()[0])
        target = None
        while target is None and time.time() < deadline:
            listing = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=10).read())
            pages = [t for t in listing if t.get("type") == "page"]
            target = pages[0] if pages else None
            time.sleep(0.1)
        if target is None:
            self.close()
            raise RuntimeError("no page in the browser")
        self._open(target["webSocketDebuggerUrl"])
        self.next_id = 1
        self.events: List[Dict[str, Any]] = []
        self.console: List[str] = []
        self.exceptions: List[str] = []
        self.dialogs: List[str] = []
        for domain in ("Page.enable", "Runtime.enable", "Log.enable"):
            self.send(domain)

    def _open(self, url: str) -> None:
        rest = url.split("://", 1)[1]
        host, _, path = rest.partition("/")
        self.sock = socket.create_connection((host.split(":")[0], int(host.split(":")[1])), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET /{path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        data = b""
        while b"\r\n\r\n" not in data:
            data += self.sock.recv(4096)
        head, _, self.buffer = data.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise RuntimeError(f"DevTools refused the connection: {head[:100]!r}")
        self.decoder = ws.FrameDecoder(require_mask=False, max_message=64 * 1024 * 1024)
        self.pending: List[Any] = []

    def _read(self, timeout: float) -> Optional[Dict[str, Any]]:
        end = time.time() + timeout
        while not self.pending:
            remaining = end - time.time()
            if remaining <= 0:
                return None
            self.sock.settimeout(remaining)
            try:
                data = self.buffer or self.sock.recv(1 << 20)
            except socket.timeout:
                return None
            self.buffer = b""
            if not data:
                raise EOFError("the browser closed the connection")
            self.pending += self.decoder.feed(data)
        opcode, payload = self.pending.pop(0)
        return json.loads(payload) if opcode == ws.OP_TEXT else {}

    def _record(self, message: Dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params", {})
        if method == "Runtime.consoleAPICalled":
            self.console.append(" ".join(str(a.get("value", a.get("description", ""))) for a in params.get("args", [])))
        elif method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails", {})
            self.exceptions.append(details.get("exception", {}).get("description") or details.get("text", ""))
        elif method == "Log.entryAdded" and params.get("entry", {}).get("level") == "error":
            self.console.append("LOG ERROR: " + params["entry"].get("text", ""))
        elif method == "Page.javascriptDialogOpening":
            self.dialogs.append(params.get("message", ""))
            self.send("Page.handleJavaScriptDialog", accept=True)               # a leave-page prompt must not freeze the next test
        self.events.append(message)

    def send(self, method: str, **params: Any) -> Dict[str, Any]:
        ident = self.next_id if hasattr(self, "next_id") else 1
        self.next_id = ident + 1
        self.sock.sendall(ws.encode_frame(ws.OP_TEXT, json.dumps({"id": ident, "method": method, "params": params}).encode(), mask=True, mask_key=os.urandom(4)))
        while True:
            message = self._read(60)
            if message is None:
                raise TimeoutError(f"no answer to {method}")
            if message.get("id") == ident:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})
            self._record(message)

    def pump(self, seconds: float = 0.05) -> None:
        end = time.time() + seconds
        while time.time() < end:
            message = self._read(max(end - time.time(), 0.01))
            if message:
                self._record(message)

    def navigate(self, url: str, timeout: float = 60) -> None:
        """Go to `url` and return when the page has loaded. The command's own reply is not waited for: a page that rewrites its address at
        once (Studio removes the token from the URL) can leave that reply pending in Chromium, while the load itself completes normally."""
        ident = self.next_id
        self.next_id = ident + 1
        self.sock.sendall(ws.encode_frame(ws.OP_TEXT, json.dumps({"id": ident, "method": "Page.navigate", "params": {"url": url}}).encode(), mask=True,
                                          mask_key=os.urandom(4)))
        seen = len(self.events)
        end = time.time() + timeout
        while time.time() < end:
            message = self._read(0.2)
            if message is None:
                continue
            self._record(message)
            if message.get("id") == ident and message.get("result", {}).get("errorText"):
                raise RuntimeError(f"navigation to {url} failed: {message['result']['errorText']}")
            if any(e.get("method") == "Page.loadEventFired" for e in self.events[seen:]):
                return
        raise TimeoutError(f"{url} did not finish loading")

    def evaluate(self, expression: str, *, await_promise: bool = True) -> Any:
        result = self.send("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=await_promise)
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            raise RuntimeError(details.get("exception", {}).get("description") or details.get("text", "evaluation failed"))
        return result["result"].get("value")

    def wait_for(self, expression: str, timeout: float = 30, message: str = "") -> Any:
        end = time.time() + timeout
        last = None
        while time.time() < end:
            try:
                last = self.evaluate(expression, await_promise=False)
            except RuntimeError as exc:
                last = str(exc)
            if last:
                return last
            self.pump(0.1)
        raise TimeoutError(f"timed out waiting for {message or expression!r} (last value: {last!r}; console: {self.console[-5:]}; exceptions: {self.exceptions[-3:]})")

    def click(self, selector: str) -> None:
        self.evaluate(f"document.querySelector({json.dumps(selector)}).click()")

    def type_text(self, selector: str, text: str) -> None:
        """Type into an input/textarea like a user: focus, then real key events for each character."""
        self.evaluate(f"document.querySelector({json.dumps(selector)}).focus()")
        for ch in text:
            self.send("Input.dispatchKeyEvent", type="keyDown", text=ch, key=ch if ch != "\n" else "Enter", unmodifiedText=ch)
            self.send("Input.dispatchKeyEvent", type="keyUp", key=ch if ch != "\n" else "Enter")

    def press(self, key: str, code: str = "", modifiers: int = 0, windows_virtual_key_code: int = 0) -> None:
        self.send("Input.dispatchKeyEvent", type="rawKeyDown", key=key, code=code or key, modifiers=modifiers, windowsVirtualKeyCode=windows_virtual_key_code)
        self.send("Input.dispatchKeyEvent", type="keyUp", key=key, code=code or key, modifiers=modifiers, windowsVirtualKeyCode=windows_virtual_key_code)

    def screenshot(self, path: Path) -> None:
        data = self.send("Page.captureScreenshot", format="png")["data"]
        Path(path).write_bytes(base64.b64decode(data))

    def close(self) -> None:
        try:
            self.send("Browser.close")
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        shutil.rmtree(self.profile, ignore_errors=True)
