"""Debugging: debugger discovery, the DAP adapter's launch rewriting, and a real gdb session through `charpente debug-adapter`."""
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from dap import DapClient

from charpente import debug
from charpente.cli import main
from charpente.core.process import ProcessResult
from charpente.errors import ChError
from charpente.serve import rpc

HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++"))
GDB = debug.find_debuggers()
HAVE_GDB = any(d["name"] == "gdb" for d in GDB)


def version_run(text):
    def run(argv, **kwargs):
        return ProcessResult(tuple(argv), 0, text)
    return run


# ---------------------------------------------------------------------- discovery
def test_gdb_needs_a_dap_mode_and_lldb_dap_is_preferred():
    which = {"gdb": "/bin/gdb", "lldb-dap": "/bin/lldb-dap"}.get
    found = debug.find_debuggers(which, version_run("GNU gdb (GDB) 15.1\n"))
    assert [d["name"] for d in found] == ["lldb-dap", "gdb"]
    assert found[1]["argv"] == ["/bin/gdb", "-q", "--interpreter=dap"] and found[1]["version"] == "15.1"
    assert [d["name"] for d in debug.find_debuggers({"gdb": "/bin/gdb"}.get, version_run("GNU gdb (Ubuntu 12.1) 12.1\n"))] == []       # too old: no DAP
    assert debug.find_debuggers({}.get, version_run("")) == []
    assert [d["name"] for d in debug.find_debuggers({"lldb-vscode": "/x/lldb-vscode"}.get, version_run(""))] == ["lldb-dap"]


def test_choosing_a_debugger():
    which = {"gdb": "/bin/gdb", "lldb-dap": "/bin/lldb-dap"}.get
    run = version_run("GNU gdb (GDB) 14.2\n")
    assert debug.choose_debugger(None, which, run)["name"] == "lldb-dap"
    assert debug.choose_debugger("gdb", which, run)["name"] == "gdb"
    with pytest.raises(ChError) as info:
        debug.choose_debugger("gdb", {}.get, run)
    assert info.value.code == "CH8023" and "gdb" in info.value.message


# ---------------------------------------------------------------------- launch rewriting (pure)
def launch(arguments, *, names=("app",), build=None, root=Path("/p")):
    said = []
    built = []

    def default_build(target, config):
        built.append((target, config))
        return Path("/p/build/Debug/app.exe")

    result = debug.program_launch(root, arguments, said.append, build or default_build, lambda: list(names))
    return result, said, built


def test_a_target_becomes_a_program_after_a_build():
    result, said, built = launch({"target": "app", "config": "Release", "args": ["--x"], "stopAtBeginningOfMainSubprogram": True, "env": {"A": "1"}})
    assert built == [("app", "Release")]
    assert result == {"args": ["--x"], "stopAtBeginningOfMainSubprogram": True, "env": {"A": "1"}, "program": str(Path("/p/build/Debug/app.exe")), "cwd": str(Path("/p"))}
    assert said[0] == "Building app (Release)..." and "Debugging" in said[1]
    assert "target" not in result and "config" not in result


def test_the_only_program_is_chosen_when_no_target_is_given():
    result, _, built = launch({}, names=("only",))
    assert built == [("only", "Debug")] and result["args"] == []
    for names in ((), ("a", "b")):
        with pytest.raises(debug.LaunchRefused, match="say which target"):
            launch({}, names=names)


def test_an_explicit_program_is_passed_through_without_building():
    result, said, built = launch({"program": "/x/y", "args": ["1"]})
    assert result == {"program": "/x/y", "args": ["1"], "cwd": str(Path("/p"))} and built == [] and said == []
    assert launch({"program": "/x/y", "cwd": "/z"})[0]["cwd"] == "/z"


def test_other_platforms_and_failed_builds_are_refused():
    with pytest.raises(debug.LaunchRefused, match="not supported"):
        launch({"target": "app", "platform": "android-arm64"})

    def failing(target, config):
        raise debug.LaunchRefused("the build failed")

    with pytest.raises(debug.LaunchRefused, match="build failed"):
        launch({"target": "app"}, build=failing)


# ---------------------------------------------------------------------- the proxy with a fake debugger
FAKE = r'''
import json, sys
def read():
    n = 0
    while True:
        line = sys.stdin.buffer.readline()
        if not line: return None
        if line in (b"\r\n", b"\n"): break
        if line.lower().startswith(b"content-length"): n = int(line.split(b":")[1])
    return json.loads(sys.stdin.buffer.read(n))
def send(o):
    b = json.dumps(o).encode(); sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(b) + b); sys.stdout.buffer.flush()
while True:
    m = read()
    if m is None: break
    send({"type": "response", "request_seq": m["seq"], "success": True, "command": m["command"], "seq": 1, "body": {"echo": m.get("arguments")}})
    if m["command"] == "disconnect": break
'''


def run_proxy(messages, prepare, tmp_path):
    script = tmp_path / "fake_debugger.py"
    script.write_text(FAKE, encoding="utf-8")
    stdin = io.BytesIO(b"".join(rpc.encode_message(m) for m in messages))
    stdout = io.BytesIO()
    proxy = debug.DapProxy([sys.executable, str(script)], stdin, stdout, prepare)
    code = proxy.run()
    data = stdout.getvalue()
    out, buffer = [], rpc.MessageBuffer()
    for body in buffer.feed(data):
        out.append(json.loads(body))
    return code, out


def test_the_proxy_forwards_everything_and_rewrites_only_launch(tmp_path):
    seen = []

    def prepare(arguments, say):
        seen.append(arguments)
        say("building")
        return {"program": "/built/app", "args": []}

    code, out = run_proxy([
        {"seq": 1, "type": "request", "command": "initialize", "arguments": {"adapterID": "x"}},
        {"seq": 2, "type": "request", "command": "launch", "arguments": {"target": "app"}},
        {"seq": 3, "type": "request", "command": "threads"},
        {"seq": 4, "type": "request", "command": "disconnect"},
    ], prepare, tmp_path)
    responses = {m["command"]: m for m in out if m["type"] == "response"}
    assert responses["initialize"]["body"]["echo"] == {"adapterID": "x"}                          # untouched
    assert responses["launch"]["body"]["echo"] == {"program": "/built/app", "args": []}            # the debugger saw the rewritten launch
    assert seen == [{"target": "app"}] and "threads" in responses
    assert any(m["type"] == "event" and m["event"] == "output" and "building" in m["body"]["output"] for m in out)
    assert code == 0


def test_a_refused_launch_is_an_error_response_and_the_debugger_never_sees_it(tmp_path):
    def prepare(arguments, say):
        raise debug.LaunchRefused("the build failed:\nmain.cpp:1: error")

    code, out = run_proxy([
        {"seq": 1, "type": "request", "command": "launch", "arguments": {"target": "app"}},
        {"seq": 2, "type": "request", "command": "disconnect"},
    ], prepare, tmp_path)
    refusal = next(m for m in out if m["type"] == "response" and m["command"] == "launch")
    assert refusal["success"] is False and refusal["request_seq"] == 1 and "build failed" in refusal["message"]
    assert refusal["seq"] > debug.EVENT_SEQ_BASE                                                    # our numbers never collide with the debugger's
    assert any(m.get("event") == "terminated" for m in out)
    assert any(m.get("event") == "output" and m["body"]["category"] == "stderr" and "error" in m["body"]["output"] for m in out)
    assert not any(m["type"] == "response" and m["command"] == "launch" and m.get("success") for m in out)


def test_a_missing_debugger_binary_is_reported_to_the_client(tmp_path):
    stdout = io.BytesIO()
    proxy = debug.DapProxy(["definitely-no-debugger-xyz"], io.BytesIO(), stdout, lambda a, s: a)
    assert proxy.run() == 1
    assert "CH2002" in stdout.getvalue().decode("utf-8")


# ---------------------------------------------------------------------- a real debugger
PROGRAM = """#include <cstdio>

int square(int x) {
    int result = x * x;
    return result;
}

int main(int argc, char** argv) {
    int value = 7;
    int answer = square(value);
    std::printf("answer=%d args=%d\\n", answer, argc);
    return 0;
}
"""
WORKSPACE = """from charpente import *

with Workspace("dbg") as ws:
    with Target("prog") as prog:
        prog.kind(Kind.EXECUTABLE)
        prog.standard("c++17")
        prog.sources(["src/main.cpp"])
"""


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "dbg.charpente").write_bytes(WORKSPACE.encode())
    (tmp_path / "src" / "main.cpp").write_bytes(PROGRAM.encode())
    return tmp_path


@pytest.fixture
def adapter(project):
    env = dict(os.environ, CHARPENTE_TRUST_ALL="1")
    client = DapClient([sys.executable, "-m", "charpente", "debug-adapter", "--root", str(project), "--debugger", "gdb"], env=env)
    yield client
    client.close()


def all_variables(adapter, frame_id):
    """The variables of every scope of a frame (gdb splits arguments and locals)."""
    found = []
    for scope in adapter.request("scopes", {"frameId": frame_id})["body"]["scopes"]:
        found += adapter.request("variables", {"variablesReference": scope["variablesReference"]})["body"]["variables"]
    return found


@pytest.mark.skipif(not (HAVE_GDB and HAVE_COMPILER), reason="needs gdb 14+ and a C++ compiler")
def test_a_real_debugging_session_breakpoint_stack_variables_step_and_run_to_the_end(adapter, project):
    source = str(project / "src" / "main.cpp")
    assert adapter.request("initialize", {"adapterID": "charpente", "linesStartAt1": True, "columnsStartAt1": True, "pathFormat": "path"})["success"]
    launch_seq = adapter.send("launch", {"target": "prog", "config": "Debug", "args": ["a", "b"]})            # the adapter builds first
    adapter.event("initialized", timeout=180)
    breakpoints = adapter.request("setBreakpoints", {"source": {"path": source}, "breakpoints": [{"line": 4}, {"line": 11}]})
    assert breakpoints["success"] and len(breakpoints["body"]["breakpoints"]) == 2                          # gdb may still call them pending
    assert adapter.request("configurationDone")["success"]
    assert adapter.response(launch_seq, timeout=60)["success"]
    stopped = adapter.event("stopped", timeout=60)
    assert stopped["body"]["reason"] == "breakpoint"
    thread = stopped["body"]["threadId"]
    stack = adapter.request("stackTrace", {"threadId": thread})["body"]["stackFrames"]
    assert [f["name"] for f in stack][:2] == ["square", "main"] and stack[0]["line"] == 4
    assert Path(stack[0]["source"]["path"]).name == "main.cpp"
    assert {v["name"]: v["value"] for v in all_variables(adapter, stack[0]["id"])}["x"] == "7"
    evaluated = adapter.request("evaluate", {"expression": "x * 2", "frameId": stack[0]["id"], "context": "watch"})
    assert evaluated["success"] and evaluated["body"]["result"] == "14"
    adapter.request("next", {"threadId": thread})
    stepped = adapter.event("stopped", timeout=60)
    assert stepped["body"]["reason"] == "step"
    line = adapter.request("stackTrace", {"threadId": thread})["body"]["stackFrames"][0]["line"]
    assert line == 5                                                                                        # one line further
    adapter.request("continue", {"threadId": thread})
    again = adapter.event("stopped", timeout=60)                                                            # the second breakpoint, in main
    assert again["body"]["reason"] == "breakpoint"
    main_frame = adapter.request("stackTrace", {"threadId": thread})["body"]["stackFrames"][0]
    assert main_frame["name"] == "main" and main_frame["line"] == 11
    values = {v["name"]: v["value"] for v in all_variables(adapter, main_frame["id"])}
    assert values["answer"] == "49" and values["argc"] == "3"                                               # the two program arguments arrived
    adapter.request("continue", {"threadId": thread})
    adapter.event("terminated", timeout=60)
    assert "answer=49 args=3" in adapter.output()
    assert "Building prog (Debug)" in adapter.output()
    adapter.request("disconnect", {})


@pytest.mark.skipif(not (HAVE_GDB and HAVE_COMPILER), reason="needs gdb 14+ and a C++ compiler")
def test_a_broken_build_stops_the_session_with_the_compiler_output(adapter, project):
    (project / "src" / "main.cpp").write_bytes(PROGRAM.replace("int value = 7;", "int value = nope;").encode())
    adapter.request("initialize", {"adapterID": "charpente"})
    seq = adapter.send("launch", {"target": "prog"})
    response = adapter.response(seq, timeout=180)
    assert response["success"] is False and "build failed" in response["message"]
    adapter.event("terminated", timeout=30)
    assert "nope" in adapter.output()


@pytest.mark.skipif(not (HAVE_GDB and HAVE_COMPILER), reason="needs gdb 14+ and a C++ compiler")
def test_debugging_an_existing_program_needs_no_workspace_target(adapter, project, tmp_path_factory):
    exe = tmp_path_factory.mktemp("exe") / ("prog.exe" if sys.platform == "win32" else "prog")
    compiler = shutil.which("g++") or shutil.which("clang++")
    subprocess.run([compiler, "-g", "-O0", str(project / "src" / "main.cpp"), "-o", str(exe)], check=True, capture_output=True)
    adapter.request("initialize", {"adapterID": "charpente"})
    seq = adapter.send("launch", {"program": str(exe), "stopAtBeginningOfMainSubprogram": True})
    adapter.event("initialized", timeout=60)
    adapter.request("configurationDone")
    assert adapter.response(seq, timeout=60)["success"]
    assert adapter.event("stopped", timeout=60)["body"]["reason"] in ("breakpoint", "entry", "step")
    adapter.request("continue", {"threadId": 1})
    adapter.event("terminated", timeout=60)


# ---------------------------------------------------------------------- the commands
def test_debug_list_and_the_error_without_a_debugger(capsys, monkeypatch):
    monkeypatch.setattr(debug, "find_debuggers", lambda *a, **k: [{"name": "gdb", "argv": ["/g", "-q"], "version": "15.1"}])
    assert main(["debug", "--list"]) == 0
    assert "gdb" in capsys.readouterr().out
    monkeypatch.setattr(debug, "find_debuggers", lambda *a, **k: [])
    assert main(["debug", "--list"]) == 1
    assert "gdb 14+" in capsys.readouterr().out
    with pytest.raises(ChError) as info:
        debug.choose_debugger()
    assert info.value.code == "CH8023"


@pytest.mark.skipif(not (HAVE_GDB and HAVE_COMPILER), reason="needs gdb and a C++ compiler")
def test_charpente_debug_builds_and_starts_the_debugger(project, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(project)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return ProcessResult(tuple(argv), 0)

    import types

    monkeypatch.setattr("charpente.commands.debug.process", types.SimpleNamespace(run=fake_run))       # only this command's call, not the build's
    assert main(["debug", "prog", "--", "one", "two"]) == 0
    assert calls[0][1] == "--args" and Path(calls[0][2]).name.startswith("prog") and calls[0][3:] == ["one", "two"]
    assert Path(calls[0][2]).is_file()                                                                     # it really built the program first
