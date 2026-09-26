"""Charpente Studio's web server (static pages, headers, host and token checks) and the front end's Node unit tests."""
import http.client
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_serve import _Client

from charpente.commands.studio import start_studio
from charpente.serve import ServerState, webapp
from charpente.serve.webapp import WEB_DIR, make_http_handler

ROOT = Path(__file__).resolve().parent


@pytest.fixture
def running(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    (tmp_path / "src").mkdir()
    (tmp_path / "demo.charpente").write_text('from charpente import *\nwith Workspace("demo") as ws:\n    with Target("a") as t:\n        t.sources(["src/*.cpp"])\n', encoding="utf-8")
    (tmp_path / "src" / "a.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    state = ServerState(tmp_path)
    state.load()
    server, url = start_studio(state)
    yield server, url, tmp_path
    server.shutdown()


def get(server, path, host=None, method="GET", headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=20)
    connection.putrequest(method, path, skip_host=host is not None)
    if host is not None:
        connection.putheader("Host", host)
    for name, value in (headers or {}).items():
        connection.putheader(name, value)
    connection.endheaders()
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, dict((k.lower(), v) for k, v in response.getheaders()), body


# ---------------------------------------------------------------------- static handler (pure)
def test_resolve_finds_files_and_refuses_everything_else():
    assert webapp.resolve(WEB_DIR, "/").name == "index.html"
    assert webapp.resolve(WEB_DIR, "/index.html?token=abc").name == "index.html"
    assert webapp.resolve(WEB_DIR, "/js/app.js").name == "app.js"
    assert webapp.resolve(WEB_DIR, "/js/panels/git.js").parent.name == "panels"
    for bad in ["/../pyproject.toml", "/js/../../__init__.py", "/%2e%2e/%2e%2e/pyproject.toml", "/js/%2e%2e/%2e%2e/__init__.py", "/..%5c..%5cx", "/.git/config",
                "/js", "/nope.js", "/C:/Windows/win.ini", "//etc/passwd", "/js/.hidden"]:
        with pytest.raises(FileNotFoundError):
            webapp.resolve(WEB_DIR, bad)


def test_content_types():
    assert webapp.content_type(Path("a.js")).startswith("text/javascript")
    assert webapp.content_type(Path("a.html")).startswith("text/html")
    assert webapp.content_type(Path("a.css")).startswith("text/css")
    assert webapp.content_type(Path("a.svg")) == "image/svg+xml"
    assert webapp.content_type(Path("a.unknownext")) == "application/octet-stream"


def test_the_handler_only_serves_get_and_head_with_security_headers():
    handler = make_http_handler(WEB_DIR, lambda: 4242)
    status, headers, body = handler("GET", "/", {})
    assert status == 200 and body.startswith(b"<!doctype html>")
    csp = headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "connect-src ws://127.0.0.1:4242" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-eval" not in csp and "script-src 'self' 'unsafe" not in csp
    assert headers["X-Content-Type-Options"] == "nosniff" and headers["X-Frame-Options"] == "DENY" and headers["Cache-Control"] == "no-store"
    assert handler("POST", "/", {})[0] == 405 and handler("DELETE", "/js/app.js", {})[0] == 405
    assert handler("GET", "/missing", {})[0] == 404


def test_every_file_the_page_needs_exists():
    import re

    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    for ref in re.findall(r'(?:src|href)="([^"#]+)"', html):
        assert (WEB_DIR / ref).is_file(), ref
    for js in (WEB_DIR / "js").rglob("*.js"):
        for imported in re.findall(r'from "(\.[^"]+)"', js.read_text(encoding="utf-8")):
            assert (js.parent / imported).resolve().is_file(), f"{js.name} imports {imported}"


def test_no_inline_scripts_or_remote_resources_in_the_page():
    import re

    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)                      # the CSP would block them anyway: keep it true
    assert not re.search(r'(?:src|href)="https?://', html)                            # nothing is loaded from the network
    for path in list((WEB_DIR / "js").rglob("*.js")) + [WEB_DIR / "studio.css"]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)[\w.-]+\.[a-z]{2,}", text), path.name
        assert "eval(" not in text and "new Function(" not in text and "document.write(" not in text, path.name


# ---------------------------------------------------------------------- the running server
def test_the_page_and_its_scripts_are_served(running):
    server, url, _ = running
    status, headers, body = get(server, "/")
    assert status == 200 and headers["content-type"].startswith("text/html") and b"Charpente Studio" in body
    assert "content-security-policy" in headers
    status, headers, body = get(server, "/js/app.js")
    assert status == 200 and headers["content-type"].startswith("text/javascript") and b"export async function start" in body
    assert get(server, "/js/panels/terminal.js")[0] == 200 and get(server, "/studio.css")[0] == 200 and get(server, "/favicon.svg")[0] == 200
    assert get(server, "/", method="HEAD")[2] == b""


def test_paths_outside_the_studio_folder_are_not_served(running):
    server, _, _ = running
    for path in ["/../pyproject.toml", "/%2e%2e/__init__.py", "/js/../../commands/serve.py", "/.git/config", "/package.json_"]:
        assert get(server, path)[0] == 404, path
    assert get(server, "/", method="POST")[0] == 405


def test_a_request_with_another_host_header_is_refused(running):
    server, _, _ = running                                                            # DNS rebinding: evil.example resolving to 127.0.0.1
    assert get(server, "/", host="evil.example")[0] == 403
    assert get(server, "/", host=f"evil.example:{server.port}")[0] == 403
    assert get(server, "/", host=f"127.0.0.1:{server.port}")[0] == 200
    assert get(server, "/", host=f"localhost:{server.port}")[0] == 200
    assert get(server, "/", host=f"LOCALHOST:{server.port}")[0] == 200


def test_the_websocket_needs_the_token_and_speaks_json_rpc(running):
    server, url, _ = running
    token = url.split("token=")[1]
    assert url.startswith(f"http://127.0.0.1:{server.port}/?token=")
    assert _Client(server.port, "wrong").status == 401
    assert _Client(server.port, token, origin="https://evil.example").status == 403
    client = _Client(server.port, token)
    assert client.status == 101
    client.send({"jsonrpc": "2.0", "id": 1, "method": "charpente/workspace"})
    assert client.receive_json()["result"]["name"] == "demo"
    client.send({"jsonrpc": "2.0", "id": 2, "method": "charpente/files/list", "params": {"path": ""}})
    names = [e["name"] for e in client.receive_json()["result"]["entries"]]
    assert "demo.charpente" in names and "src" in names
    client.close()


def test_start_studio_reports_a_broken_installation(tmp_path, monkeypatch):
    monkeypatch.setattr("charpente.commands.studio.WEB_DIR", tmp_path / "missing")
    from charpente.errors import ChError

    with pytest.raises(ChError) as info:
        start_studio(ServerState(tmp_path))
    assert info.value.code == "CH8019"


def test_the_studio_command_prints_its_address_and_stops_with_its_terminal(tmp_path):
    import os
    import sys

    (tmp_path / "w.charpente").write_text('from charpente import *\nwith Workspace("w") as ws:\n    with Target("a") as t:\n        t.sources(["*.cpp"])\n', encoding="utf-8")
    env = dict(os.environ, CHARPENTE_TRUST_ALL="1")
    proc = subprocess.Popen([sys.executable, "-m", "charpente", "studio", "--no-browser", "--json", "--root", str(tmp_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        info = json.loads(proc.stdout.readline())["charpente-studio"]
        assert info["url"].startswith("http://127.0.0.1:") and "token=" in info["url"] and info["pid"] == proc.pid
        port = int(info["url"].split(":")[2].split("/")[0])
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        connection.request("GET", "/")
        assert connection.getresponse().status == 200
    finally:
        proc.terminate()
        proc.wait(timeout=30)


# ---------------------------------------------------------------------- the front end's own unit tests
@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_front_end_unit_tests_pass():
    result = subprocess.run(["node", "--test", str(ROOT / "studio_js" / "pure.test.mjs"), str(ROOT / "studio_js" / "i18n.test.mjs")], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "fail 0" in result.stdout
