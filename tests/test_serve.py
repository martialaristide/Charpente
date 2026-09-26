"""`charpente serve`: JSON-RPC framing, the dispatcher, the WebSocket transport, and real Build Server Protocol conversations."""
import base64
import io
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from charpente.serve import Dispatcher, RpcError, ServerState, StdioServer, make_dispatcher, rpc, ws
from charpente.serve.state import path_to_uri, severity_to_bsp, uri_to_path

HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++", "cl"))

WORKSPACE = '''from charpente import *

with Workspace("demo", version="1.0.0") as ws:
    ws.configurations(["Debug", "Release"])

    with Target("core") as core:
        core.kind(Kind.STATIC_LIBRARY)
        core.standard("c++17")
        core.sources(["src/core/*.cpp"])
        core.public_include_dirs(["src/core"])

    with Target("app") as app:
        app.kind(Kind.EXECUTABLE)
        app.standard("c++17")
        app.sources(["src/main.cpp"])
        app.uses("core")
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    (tmp_path / "src" / "core").mkdir(parents=True)
    (tmp_path / "demo.charpente").write_text(WORKSPACE, encoding="utf-8")
    (tmp_path / "src" / "core" / "greet.hpp").write_text("#pragma once\nconst char* greet();\n", encoding="utf-8")
    (tmp_path / "src" / "core" / "greet.cpp").write_text('#include "greet.hpp"\nconst char* greet() { return "hello"; }\n', encoding="utf-8")
    (tmp_path / "src" / "main.cpp").write_text('#include <cstdio>\n#include "greet.hpp"\n'
                                               'int main(int argc, char** argv) { std::printf("%s %s\\n", greet(), argc > 1 ? argv[1] : "world"); return 0; }\n',
                                               encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------- framing
def test_encode_and_read_round_trip():
    message = {"jsonrpc": "2.0", "id": 1, "method": "x", "params": {"text": "héllo ✓"}}
    data = rpc.encode_message(message)
    assert data.startswith(b"Content-Length: ")
    header, _, body = data.partition(b"\r\n\r\n")
    assert int(header.split(b":")[1]) == len(body)                     # the length counts bytes, not characters
    assert rpc.read_message(io.BytesIO(data)) == message


def test_read_message_reads_consecutive_messages_and_stops_at_the_end():
    stream = io.BytesIO(rpc.encode_message({"jsonrpc": "2.0", "id": 1, "method": "a"}) + rpc.encode_message({"jsonrpc": "2.0", "id": 2, "method": "b"}))
    assert rpc.read_message(stream)["id"] == 1
    assert rpc.read_message(stream)["id"] == 2
    assert rpc.read_message(stream) is None


def test_read_message_ignores_other_headers():
    body = b'{"jsonrpc":"2.0","id":7,"method":"m"}'
    stream = io.BytesIO(b"Content-Type: application/vscode-jsonrpc; charset=utf-8\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
    assert rpc.read_message(stream)["id"] == 7


@pytest.mark.parametrize("raw", [b"Content-Length: abc\r\n\r\n", b"X-Other: 1\r\n\r\n{}", b"Content-Length: 999999999\r\n\r\n",
                                 b"Content-Length: 5\r\n\r\nnot j", b"Content-Length: 2\r\n\r\n[]"])
def test_garbage_is_a_parse_error_not_a_crash(raw):
    with pytest.raises(RpcError):
        rpc.read_message(io.BytesIO(raw))


def test_a_truncated_body_is_the_end_of_input():
    assert rpc.read_message(io.BytesIO(b"Content-Length: 50\r\n\r\n{}")) is None


# ---------------------------------------------------------------------- dispatcher
def test_dispatcher_routes_requests_and_notifications():
    d = Dispatcher()
    seen = []
    d.add_method("add", lambda p: p["a"] + p["b"])
    d.add_notification("note", lambda p: seen.append(p))
    assert d.handle({"jsonrpc": "2.0", "id": 1, "method": "add", "params": {"a": 1, "b": 2}}) == {"jsonrpc": "2.0", "id": 1, "result": 3}
    assert d.handle({"jsonrpc": "2.0", "method": "note", "params": 5}) is None and seen == [5]
    assert d.handle({"jsonrpc": "2.0", "id": 2, "result": "a response"}) is None


def test_dispatcher_errors():
    d = Dispatcher()

    @d.method("boom")
    def boom(params):
        raise RuntimeError("kaput")

    @d.method("rpc")
    def rpc_error(params):
        raise RpcError(-32000, "busy", {"why": "x"})

    assert d.handle({"jsonrpc": "2.0", "id": 1, "method": "nope"})["error"]["code"] == rpc.METHOD_NOT_FOUND
    assert d.handle({"jsonrpc": "2.0", "id": 2, "method": "boom"})["error"]["code"] == rpc.INTERNAL_ERROR
    assert "kaput" in d.handle({"jsonrpc": "2.0", "id": 2, "method": "boom"})["error"]["message"]
    assert d.handle({"jsonrpc": "2.0", "id": 3, "method": "rpc"})["error"] == {"code": -32000, "message": "busy", "data": {"why": "x"}}
    assert d.handle({"id": 4, "method": "boom"})["error"]["code"] == rpc.INVALID_REQUEST
    assert d.handle({"jsonrpc": "2.0", "id": 5, "method": 12})["error"]["code"] == rpc.INVALID_REQUEST
    d.add_notification("bad", lambda p: 1 / 0)
    assert d.handle({"jsonrpc": "2.0", "method": "bad"}) is None      # a failing notification never propagates


def _frames(data: bytes):
    stream = io.BytesIO(data)
    out = []
    while (message := rpc.read_message(stream)) is not None:
        out.append(message)
    return out


def test_stdio_server_answers_and_stops_at_exit():
    d = Dispatcher()
    d.add_method("echo", lambda p: p)
    stdin = io.BytesIO(b"".join(rpc.encode_message(m) for m in (
        {"jsonrpc": "2.0", "id": 1, "method": "echo", "params": "a"}, {"jsonrpc": "2.0", "method": "build/exit"},
        {"jsonrpc": "2.0", "id": 2, "method": "echo", "params": "never read"})))
    stdout = io.BytesIO()
    server = StdioServer(d, stdin, stdout)
    server.serve_forever()
    assert [m["id"] for m in _frames(stdout.getvalue())] == [1]


def test_stdio_server_reports_a_parse_error_and_keeps_going():
    d = Dispatcher()
    d.add_method("echo", lambda p: p)
    good = rpc.encode_message({"jsonrpc": "2.0", "id": 9, "method": "echo", "params": 1})
    stdout = io.BytesIO()
    StdioServer(d, io.BytesIO(b"Content-Length: nope\r\n\r\n" + good), stdout).serve_forever()
    messages = _frames(stdout.getvalue())
    assert messages[0]["error"]["code"] == rpc.PARSE_ERROR and messages[1]["result"] == 1


# ---------------------------------------------------------------------- WebSocket protocol
def test_accept_key_matches_rfc_6455_example():
    assert ws.accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


@pytest.mark.parametrize("size", [0, 5, 125, 126, 300, 65535, 65536, 70000])
def test_frames_round_trip_for_every_length_form(size):
    payload = bytes(range(256)) * (size // 256 + 1)
    payload = payload[:size]
    frame = ws.encode_frame(ws.OP_TEXT, payload, mask=True, mask_key=b"\x01\x02\x03\x04")
    assert ws.FrameDecoder().feed(frame) == [(ws.OP_TEXT, payload)]


def test_decoder_handles_split_input_and_fragmentation():
    decoder = ws.FrameDecoder()
    frame = ws.encode_frame(ws.OP_TEXT, b"hello world", mask=True, mask_key=b"abcd")
    assert decoder.feed(frame[:3]) == [] and decoder.feed(frame[3:9]) == []
    assert decoder.feed(frame[9:]) == [(ws.OP_TEXT, b"hello world")]
    first = bytes([0x01, 0x80 | 3]) + b"abcd" + bytes(b ^ k for b, k in zip(b"foo", b"abc"))
    last = bytes([0x80, 0x80 | 3]) + b"abcd" + bytes(b ^ k for b, k in zip(b"bar", b"abc"))
    assert decoder.feed(first + last) == [(ws.OP_TEXT, b"foobar")]


@pytest.mark.parametrize("data, message", [
    (bytes([0x81, 0x03]) + b"abc", "masked"),                                   # an unmasked client frame
    (bytes([0xC1, 0x80]) + b"abcd", "reserved"),
    (bytes([0x09, 0x80]) + b"abcd", "control"),                                 # a fragmented ping
    (bytes([0x80, 0x80]) + b"abcd", "continuation"),
])
def test_decoder_rejects_protocol_violations(data, message):
    with pytest.raises(ws.WsError, match=message):
        ws.FrameDecoder().feed(data)


def test_decoder_enforces_the_size_limit():
    frame = ws.encode_frame(ws.OP_TEXT, b"x" * 100, mask=True, mask_key=b"abcd")
    with pytest.raises(ws.WsError) as info:
        ws.FrameDecoder(max_message=50).feed(frame)
    assert info.value.close_code == 1009


def _upgrade_headers(**extra):
    headers = {"upgrade": "websocket", "connection": "Upgrade", "sec-websocket-version": "13", "sec-websocket-key": "abc"}
    headers.update(extra)
    return headers


def test_handshake_checks_token_origin_and_method():
    assert ws.check_upgrade("GET", "/?token=secret", _upgrade_headers(), "secret")[0] == 101
    assert ws.check_upgrade("GET", "/?token=wrong", _upgrade_headers(), "secret")[0] == 401
    assert ws.check_upgrade("GET", "/", _upgrade_headers(), "secret")[0] == 401
    assert ws.check_upgrade("GET", "/?token=secret", _upgrade_headers(origin="https://evil.example"), "secret")[0] == 403
    assert ws.check_upgrade("GET", "/?token=secret", _upgrade_headers(origin="http://localhost:5173"), "secret")[0] == 101
    assert ws.check_upgrade("GET", "/?token=secret", _upgrade_headers(origin="vscode-webview://abc"), "secret")[0] == 101
    assert ws.check_upgrade("POST", "/?token=secret", _upgrade_headers(), "secret")[0] == 405
    assert ws.check_upgrade("GET", "/?token=secret", {}, "secret")[0] == 426
    assert ws.check_upgrade("GET", "/?token=secret", _upgrade_headers(**{"sec-websocket-version": "8"}), "secret")[0] == 400


def test_origin_allowed():
    assert ws.origin_allowed(None) and ws.origin_allowed("http://127.0.0.1:3000") and ws.origin_allowed("tauri://localhost")
    assert not ws.origin_allowed("https://example.com") and not ws.origin_allowed("http://localhost.evil.com")
    assert not ws.origin_allowed("file://")


def test_handshake_response_of_101_has_no_content_length():
    assert b"Content-Length" not in ws.http_response(101, "Switching Protocols", {"Upgrade": "websocket"})
    assert b"Content-Length: 4" in ws.http_response(401, "Unauthorized", body="nope")


def test_parse_request():
    method, target, headers = ws.parse_request(b"GET /?token=x HTTP/1.1\r\nHost: a\r\nUpgrade: websocket\r\n\r\n")
    assert (method, target, headers["upgrade"]) == ("GET", "/?token=x", "websocket")
    with pytest.raises(ws.WsError):
        ws.parse_request(b"hello\r\n\r\n")


class _Client:
    """A minimal WebSocket client for the tests."""

    def __init__(self, port, token, origin=None):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=20)
        extra = f"Origin: {origin}\r\n" if origin else ""
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET /?token={token} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n{extra}\r\n").encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            data += chunk
        head, _, self.rest = data.partition(b"\r\n\r\n")
        self.status = int(head.split(b" ")[1])
        self.head = head.decode("latin-1")
        self.decoder = ws.FrameDecoder(require_mask=False)
        self.pending = []

    def send(self, obj):
        self.sock.sendall(ws.encode_frame(ws.OP_TEXT, json.dumps(obj).encode(), mask=True, mask_key=os.urandom(4)))

    def receive(self):
        while not self.pending:
            data = self.rest or self.sock.recv(65536)
            self.rest = b""
            if not data:
                raise EOFError
            self.pending += self.decoder.feed(data)
        opcode, payload = self.pending.pop(0)
        return opcode, payload

    def receive_json(self):
        opcode, payload = self.receive()
        assert opcode == ws.OP_TEXT
        return json.loads(payload)

    def close(self):
        self.sock.close()


def test_websocket_server_end_to_end():
    received = queue.Queue()
    closed = threading.Event()

    def on_connect(connection):
        def on_message(text):
            received.put(text)
            connection.send_text(text.upper())
        return on_message

    server = ws.WebSocketServer("tok", on_connect, lambda c: closed.set())
    server.start()
    try:
        assert "token=tok" in server.url and server.host == "127.0.0.1"
        client = _Client(server.port, "tok")
        assert client.status == 101 and "Sec-WebSocket-Accept" in client.head
        client.send({"a": 1})
        assert client.receive() == (ws.OP_TEXT, b'{"A": 1}') and json.loads(received.get(timeout=10)) == {"a": 1}
        client.sock.sendall(ws.encode_frame(ws.OP_PING, b"hi", mask=True, mask_key=b"wxyz"))
        assert client.receive() == (ws.OP_PONG, b"hi")
        client.close()
        assert closed.wait(10)
        for token, origin, status in (("bad", None, 401), ("tok", "https://evil.example", 403)):
            rejected = _Client(server.port, token, origin)
            assert rejected.status == status
            rejected.close()
    finally:
        server.shutdown()


# ---------------------------------------------------------------------- state helpers
def test_uri_helpers_round_trip(tmp_path):
    path = tmp_path / "with space" / "é.cpp"
    assert uri_to_path(path_to_uri(path)) == path.resolve()
    with pytest.raises(RpcError):
        uri_to_path("http://example.com/x")


def test_severities():
    assert [severity_to_bsp(s) for s in ("error", "warning", "note", "hint", "other")] == [1, 2, 3, 4, 1]


def test_state_reports_a_missing_workspace_with_charpentes_message(tmp_path):
    state = ServerState(tmp_path)
    with pytest.raises(RpcError) as info:
        state.load()
    assert info.value.code == -32001 and info.value.data["code"].startswith("CH")
    assert state.load_error


def test_state_describes_targets(project):
    state = ServerState(project)
    state.load()
    assert set(state.own_targets()) == {"core", "app"}
    described = state.build_target("app")
    assert described["capabilities"] == {"canCompile": True, "canTest": False, "canRun": True, "canDebug": False}
    assert described["dependencies"] == [{"uri": state.target_id("core")}] and described["languageIds"]
    assert ServerState.target_name(state.target_id("app")) == "app"
    with pytest.raises(RpcError):
        ServerState.target_name("file:///x")
    with pytest.raises(RpcError):
        state.get_target("missing")
    assert [p.name for p in state.sources("core")] == ["greet.cpp"]
    assert state.targets_containing(project / "src" / "main.cpp") == ["app"]
    assert state.targets_containing(project / "src" / "nowhere.cpp") == []
    options = state.cpp_options("app")
    assert any(o.startswith("-I") and Path(o[2:]).is_absolute() and o.endswith("core") for o in options["copts"]) or any(
        "core" in o for o in options["copts"])
    graph = state.graph()
    assert {"from": "app", "to": "core"} in graph["edges"] and graph["order"].index("core") < graph["order"].index("app")
    info = state.info()
    assert info["name"] == "demo" and "Debug" in info["configurations"]


def test_a_workspace_that_fails_to_load_can_be_fixed_and_reloaded(project):
    (project / "demo.charpente").write_text("this is not valid python (", encoding="utf-8")
    state = ServerState(project)
    with pytest.raises(RpcError):
        state.load()
    (project / "demo.charpente").write_text(WORKSPACE, encoding="utf-8")
    assert state.require().name == "demo" and state.load_error is None


# ---------------------------------------------------------------------- the BSP handlers (in process)
class Session:
    """Talks to `make_dispatcher` directly and collects notifications."""

    def __init__(self, state):
        self.notes = []
        self.dispatcher = make_dispatcher(state, lambda method, params: self.notes.append((method, params)))
        self._id = 0

    def call(self, method, params=None):
        self._id += 1
        response = self.dispatcher.handle({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        return response

    def ok(self, method, params=None):
        response = self.call(method, params)
        assert "error" not in response, response
        return response["result"]

    def notes_of(self, method):
        return [p for m, p in self.notes if m == method]


@pytest.fixture
def session(project):
    state = ServerState(project)
    state.load()
    s = Session(state)
    s.state = state
    return s


def test_methods_need_initialize_first(session):
    assert session.call("workspace/buildTargets")["error"]["code"] == rpc.SERVER_NOT_INITIALIZED
    assert "error" not in session.call("charpente/ping")                       # our own methods do not need it


def test_initialize_advertises_the_capabilities(session):
    result = session.ok("build/initialize", {"rootUri": path_to_uri(session.state.root)})
    assert result["displayName"] == "charpente" and result["bspVersion"] == "2.1.0"
    assert result["capabilities"]["compileProvider"]["languageIds"] == ["c", "cpp"]
    assert "charpente/graph" in result["data"]["charpente"]["methods"]


def test_targets_sources_and_options(session):
    session.ok("build/initialize", {})
    targets = session.ok("workspace/buildTargets")["targets"]
    assert sorted(t["displayName"] for t in targets) == ["app", "core"]
    app = next(t for t in targets if t["displayName"] == "app")["id"]
    sources = session.ok("buildTarget/sources", {"targets": [app]})["items"][0]["sources"]
    assert len(sources) == 1 and sources[0]["uri"].endswith("main.cpp") and sources[0]["kind"] == 1
    main = sources[0]["uri"]
    assert session.ok("buildTarget/inverseSources", {"textDocument": {"uri": main}})["targets"] == [app]
    assert session.ok("buildTarget/cppOptions", {"targets": [app]})["items"][0]["copts"][0].startswith(("-std=", "/std:"))
    assert session.call("buildTarget/inverseSources", {})["error"]["code"] == rpc.INVALID_PARAMS
    assert session.call("buildTarget/sources", {"targets": [{"uri": "file:///x"}]})["error"]["code"] == rpc.INVALID_PARAMS


def test_charpente_methods(session):
    assert session.ok("charpente/workspace")["name"] == "demo"
    assert {n["name"] for n in session.ok("charpente/graph")["nodes"]} == {"core", "app"}
    assert session.ok("charpente/ping")["pong"] is True
    assert session.ok("charpente/toolchains")["platforms"]
    assert session.ok("charpente/explain", {"code": "ch1001"})["text"]
    assert session.call("charpente/explain", {"code": "CH9999999"})["error"]["code"] == rpc.INVALID_PARAMS
    assert session.ok("charpente/history") == []
    assert session.call("no/such")["error"]["code"] == rpc.METHOD_NOT_FOUND


def test_event_subscription_and_unsubscription(session):
    ident = session.ok("charpente/subscribe")["subscription"]
    session.state._publish(_Event())
    assert session.notes_of("charpente/event") == [{"type": "x", "payload": {}}]
    session.ok("charpente/unsubscribe", {"subscription": ident})
    session.state._publish(_Event())
    assert len(session.notes_of("charpente/event")) == 1


class _Event:
    def to_dict(self):
        return {"type": "x", "payload": {}}


def test_a_broken_workspace_is_reported_not_fatal(project):
    (project / "demo.charpente").write_text("x = (", encoding="utf-8")
    session = Session(ServerState(project))
    session.ok("build/initialize", {})
    error = session.call("workspace/buildTargets")["error"]
    assert error["code"] == -32001 and "data" in error


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_compile_reports_progress_and_the_run_completes(session):
    session.ok("build/initialize", {})
    app = {"uri": session.state.target_id("app")}
    result = session.ok("buildTarget/compile", {"targets": [app], "originId": "o1"})
    assert result["statusCode"] == 1 and result["originId"] == "o1"
    assert session.notes_of("build/taskStart") and session.notes_of("build/taskFinish")[-1]["status"] == 1
    assert {r["target"] for r in result["data"]} >= {"app", "core"}
    assert session.ok("buildTarget/compile", {"targets": [app]})["statusCode"] == 1     # a second time: up to date


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_compile_errors_become_diagnostics_and_are_cleared_when_fixed(session, project):
    session.ok("build/initialize", {})
    app = {"uri": session.state.target_id("app")}
    main = project / "src" / "main.cpp"
    good = main.read_text(encoding="utf-8")
    main.write_text(good.replace("return 0;", "return missing_symbol;"), encoding="utf-8")
    result = session.ok("buildTarget/compile", {"targets": [app]})
    assert result["statusCode"] == 2
    published = session.notes_of("build/publishDiagnostics")
    assert published and published[-1]["diagnostics"] and published[-1]["diagnostics"][0]["severity"] == 1
    assert published[-1]["textDocument"]["uri"].endswith("main.cpp") and published[-1]["diagnostics"][0]["source"] == "charpente"
    assert session.notes_of("build/taskFinish")[-1]["status"] == 2
    main.write_text(good, encoding="utf-8")
    assert session.ok("buildTarget/compile", {"targets": [app]})["statusCode"] == 1
    assert session.notes_of("build/publishDiagnostics")[-1]["diagnostics"] == []          # cleared


def test_two_builds_at_once_are_refused_not_interleaved(session):
    session.ok("build/initialize", {})
    assert session.state._build_lock.acquire(blocking=False)
    try:
        error = session.call("charpente/build", {"targets": ["app"]})["error"]
    finally:
        session.state._build_lock.release()
    assert error["code"] == -32000 and "already running" in error["message"]


# ---------------------------------------------------------------------- a real server process
class Server:
    """`python -m charpente serve` as a subprocess spoken to over stdio, the way an editor does."""

    def __init__(self, root: Path):
        env = dict(os.environ, CHARPENTE_TRUST_ALL="1")
        self.proc = subprocess.Popen([sys.executable, "-m", "charpente", "serve", "--root", str(root)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.messages: "queue.Queue[dict]" = queue.Queue()
        self._id = 0
        threading.Thread(target=self._pump, daemon=True).start()
        threading.Thread(target=self.proc.stderr.read, daemon=True).start()

    def _pump(self):
        try:
            while (message := rpc.read_message(self.proc.stdout)) is not None:
                self.messages.put(message)
        except Exception as exc:                                              # surfaced by the test that waits for a reply
            self.messages.put({"pump-error": repr(exc)})

    def send(self, method, params=None, *, request=True):
        message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if request:
            self._id += 1
            message["id"] = self._id
        self.proc.stdin.write(rpc.encode_message(message))
        self.proc.stdin.flush()
        return self._id

    def call(self, method, params=None, timeout=240):
        ident = self.send(method, params)
        notes = []
        while True:
            message = self.messages.get(timeout=timeout)
            assert "pump-error" not in message, message
            if message.get("id") == ident:
                return message, notes
            notes.append(message)

    def stop(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def test_a_real_server_process_speaks_bsp_over_stdio(project):
    server = Server(project)
    try:
        init, _ = server.call("build/initialize", {"rootUri": path_to_uri(project)}, timeout=60)
        assert init["result"]["bspVersion"] == "2.1.0"
        server.send("build/initialized", request=False)
        targets, _ = server.call("workspace/buildTargets", timeout=60)
        assert sorted(t["displayName"] for t in targets["result"]["targets"]) == ["app", "core"]
        graph, _ = server.call("charpente/graph", timeout=60)
        assert graph["result"]["order"]
        shutdown, _ = server.call("build/shutdown", timeout=60)
        assert shutdown["result"] is None
        server.send("build/exit", request=False)
        assert server.proc.wait(timeout=30) == 0
    finally:
        server.stop()


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_running_a_program_through_the_server_never_blocks_on_the_protocol_channel(project):
    """Regression: the child process must not inherit the server's stdin, or the reply to `buildTarget/run` never came."""
    server = Server(project)
    try:
        server.call("build/initialize", {}, timeout=60)
        targets, _ = server.call("workspace/buildTargets", timeout=60)
        app = next(t["id"] for t in targets["result"]["targets"] if t["displayName"] == "app")
        reply, notes = server.call("buildTarget/run", {"target": app, "originId": "run-1", "arguments": ["Ada"]})
        assert reply["result"] == {"originId": "run-1", "statusCode": 1}
        logs = [n["params"]["message"] for n in notes if n.get("method") == "build/logMessage"]
        assert any("hello Ada" in line for line in logs), logs
        assert [n["method"] for n in notes if n.get("method") in ("build/taskStart", "build/taskFinish")] == ["build/taskStart", "build/taskFinish"]
        server.call("build/shutdown", timeout=60)
        server.send("build/exit", request=False)
    finally:
        server.stop()


def test_the_server_stops_when_its_client_goes_away(project):
    server = Server(project)
    server.call("build/initialize", {}, timeout=60)
    server.proc.stdin.close()
    assert server.proc.wait(timeout=30) == 0


def test_websocket_mode_prints_its_url_and_serves_json_rpc(project):
    env = dict(os.environ, CHARPENTE_TRUST_ALL="1")
    proc = subprocess.Popen([sys.executable, "-m", "charpente", "serve", "--ws", "--root", str(project)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    threading.Thread(target=proc.stderr.read, daemon=True).start()
    try:
        details = json.loads(proc.stdout.readline())["charpente-server"]
        assert details["url"].startswith("ws://127.0.0.1:") and details["token"] in details["url"] and details["pid"] == proc.pid
        assert _Client(details["port"], "wrong-token").status == 401
        client = _Client(details["port"], details["token"])
        assert client.status == 101
        client.send({"jsonrpc": "2.0", "id": 1, "method": "charpente/workspace"})
        reply = client.receive_json()
        assert reply["id"] == 1 and reply["result"]["name"] == "demo"
        client.send({"jsonrpc": "2.0", "id": 2, "method": "charpente/ping"})
        assert client.receive_json()["result"]["pong"] is True
        client.sock.sendall(ws.encode_frame(ws.OP_TEXT, b"not json", mask=True, mask_key=b"abcd"))
        assert client.receive_json()["error"]["code"] == rpc.PARSE_ERROR
        client.close()
    finally:
        proc.stdin.close()                                                     # closing stdin stops the server
        try:
            assert proc.wait(timeout=30) == 0
        except subprocess.TimeoutExpired:
            proc.kill()
            raise


def test_bsp_install_writes_the_connection_file(project):
    from charpente.commands import serve as serve_cmd

    assert serve_cmd.execute(["--bsp-install", "--root", str(project)]) == 0
    details = json.loads((project / ".bsp" / "charpente.json").read_text(encoding="utf-8"))
    assert details["name"] == "charpente" and details["argv"][-2:] == ["serve", "--stdio"] and details["languages"] == ["c", "cpp"]


# ---------------------------------------------------------------------- later additions
def test_compile_commands_use_the_engines_own_arguments(session):
    entries = session.ok("charpente/compileCommands")["entries"]
    assert sorted(Path(e["file"]).name for e in entries) == ["greet.cpp", "main.cpp"]
    for entry in entries:
        assert Path(entry["file"]).is_absolute() and entry["directory"] == str(session.state.root)
        argv = entry["arguments"]
        assert "-c" in argv or "/c" in argv
        assert any(a.startswith(("-std=", "/std:")) for a in argv)
        assert any(a.startswith(("-I", "/I")) and Path(a[2:]).is_absolute() for a in argv if a[2:]) or entry["file"].endswith("main.cpp")
    main = next(e for e in entries if e["file"].endswith("main.cpp"))
    assert any(a.endswith("core") and a.startswith(("-I", "/I")) for a in main["arguments"])      # the include dir of `core`


def test_a_broken_workspace_error_carries_its_code_in_the_message(project):
    (project / "demo.charpente").write_text("x = (", encoding="utf-8")
    error = Session(ServerState(project)).call("charpente/workspace")["error"]
    assert error["message"].startswith("[CH") and error["data"]["code"].startswith("CH")


def test_a_captured_child_process_never_reads_our_stdin():
    """The server speaks over stdin/stdout: a child that inherited stdin could swallow the protocol."""
    from charpente.core import process

    result = process.run([sys.executable, "-c", "import sys; sys.stdout.write(repr(sys.stdin.read()))"])
    assert result.returncode == 0 and result.stdout == "''"
    fed = process.run([sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"], input="given")
    assert fed.stdout == "given"


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_run_takes_the_program_arguments_and_the_build_options_separately(session):
    session.ok("build/initialize", {})
    app = {"uri": session.state.target_id("app")}
    result = session.ok("buildTarget/run", {"target": app, "arguments": ["Grace"], "dataKind": "charpente/run",
                                            "data": {"config": "Release"}, "originId": "r"})
    assert result["statusCode"] == 1
    logs = [p["message"] for p in session.notes_of("build/logMessage")]
    assert any("hello Grace" in line for line in logs), logs
    assert (session.state.root / "build" / "Release").exists()                  # `data.config` chose the configuration
    assert session.call("buildTarget/run", {"arguments": []})["error"]["code"] == rpc.INVALID_PARAMS
