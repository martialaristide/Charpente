"""The methods Charpente Studio's panels call (`serve/studio.py`) and the pure helpers under them."""
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from charpente.core import process
from charpente.dsl import edit as dsl_edit
from charpente.errors import ChError
from charpente.serve import ServerState, insight, make_dispatcher, rpc
from charpente.serve import studio as studio_mod

HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++", "cl"))
HAVE_GIT = shutil.which("git") is not None

WORKSPACE = '''from charpente import *

with Workspace("demo", version="1.0.0") as ws:
    ws.option("fast", default=False, help="Skip the slow paths")
    ws.option("mode", default="a", choices=["a", "b"], help="Mode")
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
    (tmp_path / "src" / "main.cpp").write_text('#include <cstdio>\n#include "greet.hpp"\nint main() { std::puts(greet()); return 0; }\n', encoding="utf-8")
    return tmp_path


class Client:
    def __init__(self, root):
        self.state = ServerState(root)
        self.state.load()
        self.notes = []
        self.dispatcher = make_dispatcher(self.state, lambda m, p: self.notes.append((m, p)))
        self.n = 0

    def call(self, method, params=None):
        self.n += 1
        return self.dispatcher.handle({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})

    def ok(self, method, params=None):
        response = self.call(method, params)
        assert "error" not in response, response
        return response["result"]

    def error(self, method, params=None):
        response = self.call(method, params)
        assert "error" in response, response
        return response["error"]


@pytest.fixture
def client(project):
    c = Client(project)
    yield c
    c.dispatcher.close()


# ---------------------------------------------------------------------- pure helpers
def test_critical_path_picks_the_heaviest_chain():
    deps = {"app": ["core", "net"], "core": ["base"], "net": [], "base": []}
    cost = {"app": 1.0, "core": 2.0, "net": 10.0, "base": 3.0}
    assert insight.critical_path(deps, cost) == (["net", "app"], 11.0)          # 10 + 1 beats 3 + 2 + 1
    assert insight.critical_path(deps, {**cost, "net": 0.5}) == (["base", "core", "app"], 6.0)


def test_critical_path_edge_cases():
    assert insight.critical_path({}, {}) == ([], 0.0)
    assert insight.critical_path({"a": []}, {}) == (["a"], 0.0)
    assert insight.critical_path({"a": ["missing"]}, {"a": 2.0}) == (["a"], 2.0)      # unknown dependency names are ignored
    assert insight.critical_path({"a": ["b"], "b": ["a"]}, {"a": 1.0, "b": 1.0})[1] > 0   # a cycle terminates


def test_target_costs_group_by_kind():
    rows = [{"target": "a", "kind": "compile", "duration": 1.5}, {"target": "a", "kind": "link", "duration": 0.5},
            {"target": "b", "kind": "compile", "duration": None}, {"target": "", "kind": "x", "duration": 9}]
    assert insight.target_costs(rows) == {"a": {"total": 2.0, "compile": 1.5, "link": 0.5}, "b": {"total": 0.0, "compile": 0.0}}


def test_dsl_schema_lists_what_an_editor_can_complete(client):
    schema = client.ok("charpente/dsl/schema")
    names = {m["name"] for m in schema["classes"]["Target"]}
    assert {"sources", "kind", "uses", "standard"} <= names
    assert "requires" in {m["name"] for m in schema["classes"]["Workspace"]}
    assert "EXECUTABLE" in schema["enums"]["Kind"] and schema["enums"]["Language"]
    sources = next(m for m in schema["classes"]["Target"] if m["name"] == "sources")
    assert sources["signature"] == "(patterns: Strings)"


def test_add_workspace_call_and_remove_requirement():
    text = 'from charpente import *\n\nwith Workspace("x") as ws:\n    ws.configurations(["Debug"])\n'
    added = dsl_edit.add_workspace_call(text, "requires", "fmt@^10")
    assert added.splitlines()[3] == '    ws.requires("fmt@^10")'
    assert dsl_edit.add_workspace_call(added, "requires", "fmt@^10") == added                 # idempotent
    assert dsl_edit.remove_requirement(added, "fmt@^10") == text
    with pytest.raises(ChError):
        dsl_edit.add_workspace_call("print('no workspace here')\n", "requires", "fmt")
    with pytest.raises(ChError):
        dsl_edit.remove_requirement(text, "fmt")
    assert 'ws2.requires("glm")' in dsl_edit.add_workspace_call('with Workspace("x", version="1") as ws2:  # comment\n    pass\n', "requires", "glm")


def test_saved_options_round_trip(tmp_path):
    assert dsl_edit.load_saved_options(tmp_path) == {}
    dsl_edit.save_options(tmp_path, {"fast": "true", "mode": "b", "level": "3", "label": 'say "hi"'})
    assert dsl_edit.load_saved_options(tmp_path) == {"fast": "true", "mode": "b", "level": "3", "label": 'say "hi"'}
    with pytest.raises(ChError):
        dsl_edit.render_saved_options({"bad name": "x"})
    (tmp_path / ".charpente" / "options.toml").write_text("not = [valid", encoding="utf-8")
    with pytest.raises(ChError):
        dsl_edit.load_saved_options(tmp_path)


# ---------------------------------------------------------------------- safe paths and files
@pytest.mark.parametrize("bad", ["../x", "a/../../x", "/etc/passwd", "C:/Windows", "C:\\x", "a\\..\\..\\b"])
def test_paths_outside_the_project_are_refused(client, bad):
    assert client.error("charpente/files/read", {"path": bad})["code"] == rpc.INVALID_PARAMS
    assert client.error("charpente/files/write", {"path": bad, "text": "x"})["code"] == rpc.INVALID_PARAMS


def test_a_symlink_out_of_the_project_is_refused(client, project, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    try:
        os.symlink(outside, project / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symbolic links here")
    assert client.error("charpente/files/read", {"path": "link/secret.txt"})["code"] == rpc.INVALID_PARAMS
    assert client.error("charpente/files/write", {"path": "link/new.txt", "text": "x"})["code"] == rpc.INVALID_PARAMS


def test_git_internals_cannot_be_written(client):
    assert "Git" in client.error("charpente/files/write", {"path": ".git/config", "text": "x"})["message"]
    assert client.error("charpente/files/write", {"path": "a/.GIT/x", "text": "x"})["code"] == rpc.INVALID_PARAMS


def test_files_list_hides_build_output(client, project):
    (project / "build").mkdir()
    (project / ".git").mkdir()
    (project / "node_modules").mkdir()
    root = client.ok("charpente/files/list", {})
    names = [e["name"] for e in root["entries"]]
    assert names[0] == "src" and "demo.charpente" in names and not {"build", ".git", "node_modules"} & set(names)
    demo = next(e for e in root["entries"] if e["name"] == "demo.charpente")
    assert demo["language"] == "charpente" and not demo["dir"] and demo["size"] > 0
    src = client.ok("charpente/files/list", {"path": "src"})
    assert src["path"] == "src" and [e["path"] for e in src["entries"]] == ["src/core", "src/main.cpp"]
    assert client.error("charpente/files/list", {"path": "demo.charpente"})["code"] == rpc.INVALID_PARAMS


def test_read_write_and_conflict_detection(client, project):
    opened = client.ok("charpente/files/read", {"path": "src/main.cpp"})
    assert opened["language"] == "cpp" and "greet" in opened["text"] and len(opened["sha256"]) == 64
    saved = client.ok("charpente/files/write", {"path": "src/main.cpp", "text": "int main() { return 0; }\n", "expected": opened["sha256"]})
    assert (project / "src" / "main.cpp").read_text(encoding="utf-8") == "int main() { return 0; }\n"
    assert saved["sha256"] != opened["sha256"] and not list((project / "src").glob("*.charpente-tmp"))
    (project / "src" / "main.cpp").write_text("changed elsewhere\n", encoding="utf-8")            # someone else edits meanwhile
    conflict = client.error("charpente/files/write", {"path": "src/main.cpp", "text": "mine", "expected": saved["sha256"]})
    assert conflict["code"] == studio_mod.CONFLICT and "sha256" in conflict["data"]
    assert (project / "src" / "main.cpp").read_text(encoding="utf-8") == "changed elsewhere\n"      # not overwritten
    client.ok("charpente/files/write", {"path": "src/main.cpp", "text": "forced"})                    # no `expected`: a deliberate overwrite
    assert (project / "src" / "main.cpp").read_text(encoding="utf-8") == "forced"


def test_write_preserves_line_endings_and_unicode(client, project):
    client.ok("charpente/files/write", {"path": "src/u.cpp", "text": "// héllo ✓\r\nint x;\r\n"})
    assert (project / "src" / "u.cpp").read_bytes() == "// héllo ✓\r\nint x;\r\n".encode("utf-8")
    assert client.ok("charpente/files/read", {"path": "src/u.cpp"})["text"] == "// héllo ✓\r\nint x;\r\n"


def test_binary_and_huge_files_are_not_opened(client, project):
    (project / "blob.bin").write_bytes(b"\xff\xfe\x00\x01")
    (project / "huge.txt").write_bytes(b"x" * (studio_mod.MAX_TEXT_BYTES + 1))
    assert client.error("charpente/files/read", {"path": "blob.bin"})["code"] == studio_mod.NOT_TEXT
    assert client.error("charpente/files/read", {"path": "huge.txt"})["code"] == studio_mod.NOT_TEXT
    assert client.error("charpente/files/write", {"path": "x.txt", "text": 5})["code"] == rpc.INVALID_PARAMS


def test_create_refuses_to_overwrite(client, project):
    client.ok("charpente/files/create", {"path": "docs/notes.md"})
    assert (project / "docs" / "notes.md").exists()
    client.ok("charpente/files/create", {"path": "assets", "dir": True})
    assert (project / "assets").is_dir()
    assert client.error("charpente/files/create", {"path": "docs/notes.md"})["code"] == studio_mod.CONFLICT
    assert client.error("charpente/files/write", {"path": "gone.txt", "text": "x", "expected": "abc"})["code"] == studio_mod.CONFLICT


# ---------------------------------------------------------------------- options and packages
def test_options_are_validated_saved_and_used_by_the_commands(client, project):
    info = client.ok("charpente/options/set", {"values": {"fast": True, "mode": "b"}})
    assert info["options"]["fast"]["value"] == "true" and info["options"]["mode"]["value"] == "b"
    assert dsl_edit.load_saved_options(project) == {"fast": "true", "mode": "b"}
    assert 'fast = true' in (project / ".charpente" / "options.toml").read_text(encoding="utf-8")
    assert client.error("charpente/options/set", {"values": {"nope": 1}})["code"] == rpc.INVALID_PARAMS
    assert client.error("charpente/options/set", {"values": {"mode": "zzz"}})["code"] == rpc.INVALID_PARAMS
    assert client.error("charpente/options/set", {"values": {}})["code"] == rpc.INVALID_PARAMS
    assert dsl_edit.load_saved_options(project) == {"fast": "true", "mode": "b"}            # a refused value saved nothing
    from charpente.commands._common import load

    cwd = os.getcwd()
    os.chdir(project)
    try:
        assert load(None).option_values["mode"] == "b"                                      # the command line reads the saved file too
        assert load(None, ["mode=a"]).option_values["mode"] == "a"                          # and --opt wins
    finally:
        os.chdir(cwd)


def test_packages_search_add_and_remove(client, project):
    found = client.ok("charpente/packages/search", {"text": "fm"})["packages"]
    assert any(p["name"] == "fmt" and p["versions"] for p in found)
    assert client.error("charpente/packages/add", {"spec": "definitely-not-a-package"})["code"] == rpc.INVALID_PARAMS
    added = client.ok("charpente/packages/add", {"spec": "fmt"})
    assert "fmt" in added["requires"]
    assert "CH6005" in client.ok("charpente/workspace")["notice"]                              # declared but not installed: shown, not fatal
    refused = client.error("charpente/build", {"targets": ["app"]})
    assert refused["data"]["code"] == "CH6005" and "install" in refused["message"]
    assert 'ws.requires("fmt")' in (project / "demo.charpente").read_text(encoding="utf-8")
    assert client.ok("charpente/packages/list")["requires"] == ["fmt"]
    assert client.ok("charpente/packages/remove", {"spec": "fmt"})["requires"] == []
    assert (project / "demo.charpente").read_text(encoding="utf-8") == WORKSPACE
    assert client.error("charpente/packages/remove", {"spec": "fmt"})["code"] == rpc.INVALID_PARAMS


# ---------------------------------------------------------------------- Git
@pytest.fixture
def repo(project):
    if not HAVE_GIT:
        pytest.skip("needs git")

    def git(*args):
        return subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True, text=True).stdout

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Tester")
    git("config", "commit.gpgsign", "false")
    (project / ".gitignore").write_text("build/\n.charpente/\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "chore: initial")
    return git


def test_git_status_diff_stage_and_commit(client, project, repo):
    status = client.ok("charpente/git/status")
    assert status["branch"] and status["staged"] == [] and status["modified"] == []
    (project / "src" / "main.cpp").write_text("int main() { return 1; }\n", encoding="utf-8")
    (project / "notes.txt").write_text("new\n", encoding="utf-8")
    status = client.ok("charpente/git/status")
    assert status["modified"] == ["src/main.cpp"] and status["untracked"] == ["notes.txt"]
    diff = client.ok("charpente/git/diff", {"path": "src/main.cpp"})["diff"]
    assert "+int main() { return 1; }" in diff and "-#include <cstdio>" in diff
    assert client.ok("charpente/git/diff", {"path": "src/main.cpp", "staged": True})["diff"] == ""
    assert client.error("charpente/git/diff", {"path": "../x"})["code"] == rpc.INVALID_PARAMS
    client.ok("charpente/git/stage", {"paths": ["src/main.cpp"]})
    assert client.ok("charpente/git/status")["staged"] == ["src/main.cpp"]
    assert "return 1" in client.ok("charpente/git/diff", {"staged": True})["diff"]
    client.ok("charpente/git/stage", {"paths": ["src/main.cpp"], "unstage": True})
    assert client.ok("charpente/git/status")["staged"] == []
    client.ok("charpente/git/stage", {"paths": ["src/main.cpp"]})
    assert client.error("charpente/git/commit", {"message": " "})["code"] == rpc.INVALID_PARAMS
    bad = client.ok("charpente/git/commit", {"message": "not conventional", "noVerify": True})
    assert bad["ok"] is False and "CH8014" in bad["output"]                                  # the message discipline applies
    done = client.ok("charpente/git/commit", {"message": "fix: return one", "noVerify": True})
    assert done["ok"] is True
    assert client.ok("charpente/git/log", {"limit": 5})["commits"][0]["subject"] == "fix: return one"


def test_a_single_hunk_can_be_staged(client, project, repo):
    lines = [f"line {i}\n" for i in range(1, 41)]
    (project / "long.txt").write_text("".join(lines), encoding="utf-8")
    repo("add", "long.txt")
    repo("commit", "-q", "-m", "chore: add long")
    changed = list(lines)
    changed[1] = "line two\n"
    changed[38] = "line thirty-nine\n"
    (project / "long.txt").write_text("".join(changed), encoding="utf-8")
    diff = client.ok("charpente/git/diff", {"path": "long.txt"})["diff"]
    head, first, second = diff.split("\n@@")[0], "@@" + diff.split("\n@@")[1], "@@" + diff.split("\n@@")[2]
    assert "line two" in first and "thirty-nine" in second
    client.ok("charpente/git/apply", {"patch": head + "\n" + first})
    staged = client.ok("charpente/git/diff", {"path": "long.txt", "staged": True})["diff"]
    assert "line two" in staged and "thirty-nine" not in staged
    assert "thirty-nine" in client.ok("charpente/git/diff", {"path": "long.txt"})["diff"]      # the other hunk is still unstaged
    client.ok("charpente/git/apply", {"patch": head + "\n" + first, "unstage": True})
    assert client.ok("charpente/git/diff", {"path": "long.txt", "staged": True})["diff"] == ""
    assert client.error("charpente/git/apply", {"patch": ""})["code"] == rpc.INVALID_PARAMS


def test_git_methods_explain_a_folder_that_is_not_a_repository(client, project):
    if not HAVE_GIT:
        pytest.skip("needs git")
    if subprocess.run(["git", "-C", str(project), "rev-parse"], capture_output=True).returncode == 0:
        pytest.skip("the temporary folder is inside a repository")
    error = client.error("charpente/git/status")
    assert error["code"] == rpc.INVALID_PARAMS and "CH8013" in error["message"]


# ---------------------------------------------------------------------- devices, logs, terminal
def test_devices_report_what_is_missing_instead_of_failing(client):
    result = client.ok("charpente/devices")
    assert isinstance(result["devices"], list) and isinstance(result["notes"], list)
    for device in result["devices"]:
        assert {"id", "platform", "state", "name"} <= set(device)


def test_device_logs_need_a_known_platform(client):
    assert "no log source" in client.error("charpente/devices/logs", {"id": "x", "platform": "amiga"})["message"]


def _wait(check, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


def _stream_lines(client, ident):
    return [p["line"] for m, p in client.notes if m == "charpente/stream" and p["id"] == ident and "line" in p]


def test_the_terminal_streams_output_and_reports_the_exit_code(client):
    ident = client.ok("charpente/terminal/run", {"argv": [sys.executable, "-c", "print('one'); print('two'); raise SystemExit(3)"]})["id"]
    assert _wait(lambda: any(m == "charpente/stream" and p["id"] == ident and p.get("exit") == 3 for m, p in client.notes))
    assert _stream_lines(client, ident) == ["one", "two"]
    assert client.notes[0][1]["started"]                                                         # the client hears when it started


def test_the_terminal_runs_in_the_project_environment(client, project):
    code = "import os; print(os.environ['CHARPENTE_SHELL']); print(os.getcwd())"
    ident = client.ok("charpente/terminal/run", {"argv": [sys.executable, "-c", code]})["id"]
    assert _wait(lambda: any(p.get("exit") == 0 for m, p in client.notes if p.get("id") == ident))
    lines = _stream_lines(client, ident)
    assert lines[0] == "1" and Path(lines[1]).resolve() == project.resolve()


def test_the_terminal_refuses_command_lines_and_unknown_programs(client):
    assert client.error("charpente/terminal/run", {"argv": "ls -l"})["code"] == rpc.INVALID_PARAMS       # a string is not an argv
    assert client.error("charpente/terminal/run", {"argv": []})["code"] == rpc.INVALID_PARAMS
    assert client.error("charpente/terminal/run", {"argv": ["no-such-program-xyz"]})["code"] == rpc.INVALID_PARAMS


def test_a_running_command_can_be_stopped_and_dies_with_its_connection(client):
    slow = [sys.executable, "-c", "import time; print('up', flush=True); time.sleep(60)"]
    first = client.ok("charpente/terminal/run", {"argv": slow})["id"]
    assert _wait(lambda: "up" in _stream_lines(client, first))
    assert client.ok("charpente/stream/stop", {"id": first}) == {"stopped": True}
    assert _wait(lambda: any(p.get("exit") is not None for m, p in client.notes if p.get("id") == first))
    assert client.ok("charpente/stream/stop", {"id": first}) == {"stopped": False}
    second = client.ok("charpente/terminal/run", {"argv": slow})["id"]
    assert _wait(lambda: _stream_lines(client, second) == ["up"])
    client.dispatcher.close()                                                                    # the connection ends
    assert _wait(lambda: any(p.get("exit") is not None for m, p in client.notes if p.get("id") == second))


# ---------------------------------------------------------------------- profile and headers
@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_profile_and_headers_after_a_real_build(client, project):
    assert client.ok("charpente/profile")["session"] is None                                     # nothing built yet
    run = subprocess.run([sys.executable, "-m", "charpente", "build"], cwd=project, capture_output=True, text=True,
                         env=dict(os.environ, CHARPENTE_TRUST_ALL="1"))
    assert run.returncode == 0, run.stdout + run.stderr
    profile = client.ok("charpente/profile")
    assert profile["session"]["ok"] is True and profile["actions"]
    assert set(profile["targets"]) >= {"core", "app"}
    assert profile["criticalPath"][-1] == "app" and "core" in profile["criticalPath"] and profile["criticalSeconds"] > 0
    assert all({"action", "target", "kind", "status", "duration"} <= set(a) for a in profile["actions"])
    headers = client.ok("charpente/headers")["headers"]
    assert any(h["path"].endswith("greet.hpp") and h["includedBy"] >= 2 for h in headers)


# ---------------------------------------------------------------------- the process layer's line streams
def test_line_stream_delivers_lines_and_the_exit_code():
    lines, codes = [], []
    stream = process.LineStream([sys.executable, "-c", "import sys; print('a'); print('b', file=sys.stderr); raise SystemExit(4)"],
                                lines.append, codes.append)
    assert stream.wait(30) == 4
    assert sorted(lines) == ["a", "b"] and codes == [4]


def test_line_stream_has_no_stdin_and_can_be_stopped_twice():
    lines = []
    stream = process.LineStream([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], lines.append)
    stream.wait(30)
    assert lines == ["''"]
    slow = process.LineStream([sys.executable, "-c", "import time; time.sleep(60)"], lines.append)
    slow.stop()
    slow.stop()
    assert slow.wait(5) is not None


def test_line_stream_errors_are_coded():
    with pytest.raises(ChError) as info:
        process.LineStream(["no-such-program-xyz"], lambda line: None)
    assert info.value.code == "CH2002"
    with pytest.raises(ChError):
        process.LineStream("a string", lambda line: None)


def test_a_failing_consumer_does_not_stop_the_reader():
    seen = []

    def bad(line):
        seen.append(line)
        raise RuntimeError("consumer bug")

    stream = process.LineStream([sys.executable, "-c", "print('x'); print('y')"], bad)
    assert stream.wait(30) == 0 and seen == ["x", "y"]


def test_threads_are_not_left_behind(client):
    before = threading.active_count()
    ident = client.ok("charpente/terminal/run", {"argv": [sys.executable, "-c", "print(1)"]})["id"]
    assert _wait(lambda: any(p.get("exit") == 0 for m, p in client.notes if p.get("id") == ident))
    assert _wait(lambda: threading.active_count() <= before + 1)


# ---------------------------------------------------------------------- formatting and the language server
HAVE_CLANGD = shutil.which("clangd") is not None
HAVE_FORMAT = shutil.which("clang-format") is not None


def test_format_reports_a_missing_clang_format_instead_of_pretending(client, monkeypatch):
    monkeypatch.setattr(studio_mod.shutil, "which", lambda name, **kw: None)
    result = client.ok("charpente/format", {"path": "src/main.cpp", "text": "int  x ;"})
    assert result["available"] is False and result["text"] == "int  x ;" and "not installed" in result["reason"]
    assert client.error("charpente/format", {"text": 5})["code"] == rpc.INVALID_PARAMS
    assert client.error("charpente/format", {"path": "../x.cpp", "text": "x"})["code"] == rpc.INVALID_PARAMS


@pytest.mark.skipif(not HAVE_FORMAT, reason="needs clang-format")
def test_format_uses_the_project_style(client, project):
    (project / ".clang-format").write_text("BasedOnStyle: LLVM\nIndentWidth: 4\n", encoding="utf-8")
    result = client.ok("charpente/format", {"path": "src/main.cpp", "text": "int main(){if(1){return 0;}}\n"})
    assert result["available"] is True and "error" not in result
    assert "    if (1) {" in result["text"] and result["text"].endswith("}\n")


def test_lsp_start_explains_a_missing_server(client, monkeypatch):
    monkeypatch.setattr("charpente.serve.lsp.find_server", lambda which=None: None)
    error = client.error("charpente/lsp/start")
    assert error["code"] == rpc.INVALID_PARAMS and "clangd is not installed" in error["message"]
    assert client.error("charpente/lsp/send", {"id": "nope", "message": {}})["code"] == rpc.INVALID_PARAMS
    assert client.ok("charpente/lsp/stop", {"id": "nope"}) == {"stopped": False}


def test_message_buffer_reassembles_split_and_joined_messages():
    a, b = rpc.encode_message({"a": 1}), rpc.encode_message({"b": "é"})
    both = a + b
    for cut in range(1, len(both)):
        buffer = rpc.MessageBuffer()
        got = buffer.feed(both[:cut]) + buffer.feed(both[cut:])
        assert [__import__("json").loads(x) for x in got] == [{"a": 1}, {"b": "é"}], cut
    with pytest.raises(rpc.RpcError):
        rpc.MessageBuffer().feed(b"Content-Length: nope\r\n\r\n")
    with pytest.raises(rpc.RpcError):
        rpc.MessageBuffer().feed(b"x" * 9000)


def _lsp_wait(client, predicate, timeout=60):
    return _wait(lambda: any(m == "charpente/lsp" and predicate(p) for m, p in client.notes), timeout)


@pytest.mark.skipif(not HAVE_CLANGD or not HAVE_COMPILER, reason="needs clangd and a C++ compiler")
def test_a_real_clangd_session_through_the_relay(client, project):
    import json

    started = client.ok("charpente/lsp/start")
    ident = started["id"]
    assert started["server"].lower().startswith("clangd") and Path(started["compileCommands"]).is_file()
    database = json.loads(Path(started["compileCommands"]).read_text(encoding="utf-8"))
    assert {Path(e["file"]).name for e in database} == {"greet.cpp", "main.cpp"}

    def send(message):
        assert client.ok("charpente/lsp/send", {"id": ident, "message": message})["sent"] is True

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"processId": None, "rootUri": project.as_uri(), "capabilities": {}}})
    assert _lsp_wait(client, lambda p: p.get("message", {}).get("id") == 1)
    send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
    main = project / "src" / "main.cpp"
    text = '#include <cstdio>\n#include "greet.hpp"\nint main() { int unused = missing_name; std::puts(greet()); return 0; }\n'
    main.write_text(text, encoding="utf-8")
    send({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {"uri": main.as_uri(), "languageId": "cpp", "version": 1, "text": text}}})
    assert _lsp_wait(client, lambda p: p.get("message", {}).get("method") == "textDocument/publishDiagnostics"
                     and any("missing_name" in d["message"] for d in p["message"]["params"]["diagnostics"]))
    send({"jsonrpc": "2.0", "id": 2, "method": "textDocument/completion",
          "params": {"textDocument": {"uri": main.as_uri()}, "position": {"line": 2, "character": 41}}})
    assert _lsp_wait(client, lambda p: p.get("message", {}).get("id") == 2)
    assert client.ok("charpente/lsp/stop", {"id": ident}) == {"stopped": True}
    assert _lsp_wait(client, lambda p: "exit" in p)


@pytest.mark.skipif(not HAVE_CLANGD, reason="needs clangd")
def test_a_language_server_dies_with_its_connection(client):
    started = client.ok("charpente/lsp/start")
    assert started["id"]
    client.dispatcher.close()
    assert _lsp_wait(client, lambda p: "exit" in p)


def test_clang_cl_is_offered_only_when_it_can_really_compile(monkeypatch):
    from charpente import toolchains

    calls = []

    class Result:
        def __init__(self, code):
            self.returncode = code

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return Result(1 if "bad" in argv[0] else 0)

    monkeypatch.setattr("charpente.core.process.run", fake_run)
    monkeypatch.setattr(toolchains, "_CLANG_CL_PROBES", {})
    assert toolchains.clang_cl_works("good/clang-cl") is True
    assert toolchains.clang_cl_works("bad/clang-cl") is False
    assert toolchains.clang_cl_works("bad/clang-cl") is False and len(calls) == 2                # each answer is remembered
    assert calls[0][1:3] == ["/nologo", "/c"]


# ---------------------------------------------------------------------- the assistant panel's methods
from charpente.ai.provider import AIProvider  # noqa: E402

AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


class Fake(AIProvider):
    name = "fake"

    def __init__(self, *answers, available=True):
        self.answers, self.available, self.prompts = list(answers), available, []

    def is_available(self):
        return self.available

    def complete(self, prompt, *, system=None):
        if not self.available:
            return "AI features are not configured."
        self.prompts.append(prompt)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def fake_ai(monkeypatch, *answers, available=True):
    provider = Fake(*answers, available=available)
    monkeypatch.setattr("charpente.serve.ai_api.select_provider", lambda: provider)
    return provider


def test_ai_status_says_how_to_enable_it(project, monkeypatch):
    fake_ai(monkeypatch, "x", available=False)
    c = Client(project)
    status = c.ok("charpente/ai/status")
    assert status["available"] is False and "ANTHROPIC_API_KEY" in status["howTo"]
    fake_ai(monkeypatch, "x")
    assert Client(project).ok("charpente/ai/status") == {"available": True, "provider": "fake", "howTo": None}


def test_a_context_is_shown_before_anything_is_sent(project, monkeypatch):
    provider = fake_ai(monkeypatch, "answer")
    c = Client(project)
    (project / "src" / "main.cpp").write_text(f'const char* k = "{AWS_KEY}";\nint x = oops;\n', encoding="utf-8")
    context = c.ok("charpente/ai/context", {"kind": "error", "text": "src/main.cpp:2:9: error: oops was not declared"})
    assert provider.prompts == []                                                                  # building a context sends nothing
    assert [i["label"] for i in context["items"]] == ["workspace", "build output", "src/main.cpp:2"]
    assert context["redactions"] == 1 and AWS_KEY not in context["text"] and "int x = oops;" in context["text"]
    assert context["provider"] == "fake" and context["total"] > 0


def test_send_explains_a_context_the_user_has_seen(project, monkeypatch):
    provider = fake_ai(monkeypatch, "The name is not declared; declare it.")
    c = Client(project)
    context = c.ok("charpente/ai/context", {"kind": "question", "text": "why is main slow?"})
    answer = c.ok("charpente/ai/send", {"id": context["id"], "mode": "ask"})
    assert answer == {"mode": "ask", "answer": "The name is not declared; declare it."}
    assert "why is main slow?" in provider.prompts[0] and "Answer the question" in provider.prompts[0]
    assert c.error("charpente/ai/send", {"id": "unknown"})["code"] == rpc.INVALID_PARAMS             # only contexts the user saw
    assert c.error("charpente/ai/send", {"id": context["id"], "mode": "nonsense"})["code"] == rpc.INVALID_PARAMS


def test_send_needs_a_configured_provider_and_never_crashes_on_provider_errors(project, monkeypatch):
    fake_ai(monkeypatch, "x", available=False)
    c = Client(project)
    context = c.ok("charpente/ai/context", {"kind": "question", "text": "hi"})
    error = c.error("charpente/ai/send", {"id": context["id"]})
    assert error["data"]["code"] == "CH8020" and "not configured" in error["message"]

    class Broken(Fake):
        def complete(self, prompt, *, system=None):
            raise ConnectionError("network down")

    monkeypatch.setattr("charpente.serve.ai_api.select_provider", lambda: Broken("x"))
    other = Client(project)
    seen = other.ok("charpente/ai/context", {"kind": "question", "text": "q"})
    error = other.error("charpente/ai/send", {"id": seen["id"]})
    assert "network down" in error["message"] and "ConnectionError" in error["message"]


def test_selection_context_refuses_secret_files_and_redacts(project, monkeypatch):
    fake_ai(monkeypatch, "x")
    c = Client(project)
    assert "secrets file" in c.error("charpente/ai/context", {"kind": "selection", "path": ".env", "selection": "A=1"})["message"]
    context = c.ok("charpente/ai/context", {"kind": "selection", "path": "src/main.cpp", "selection": f'k = "{AWS_KEY}"', "text": "what is this?"})
    assert AWS_KEY not in context["text"] and [i["label"] for i in context["items"]] == ["workspace", "src/main.cpp (selection)", "question"]
    assert c.error("charpente/ai/context", {"kind": "mystery"})["code"] == rpc.INVALID_PARAMS


FIX_DIFF = """--- a/src/main.cpp
+++ b/src/main.cpp
@@ -1,3 +1,3 @@
 #include <cstdio>
-#include "greet.hpp"
+#include "greet.hpp"  // fixed
 int main() { std::puts(greet()); return 0; }
"""


def test_a_proposed_fix_is_a_reviewable_diff_and_changes_nothing_until_applied(project, monkeypatch):
    fake_ai(monkeypatch, "Add a comment.\n```diff\n" + FIX_DIFF + "```")
    c = Client(project)
    before = (project / "src" / "main.cpp").read_bytes()
    context = c.ok("charpente/ai/context", {"kind": "error", "text": "src/main.cpp:2: error"})
    sent = c.ok("charpente/ai/send", {"id": context["id"], "mode": "fix"})
    assert sent["files"] == ["src/main.cpp"] and "+#include" in sent["diff"] and sent["explanation"] == "Add a comment."
    assert (project / "src" / "main.cpp").read_bytes() == before
    assert c.error("charpente/ai/apply", {"proposal": "nope"})["code"] == rpc.INVALID_PARAMS


def test_a_useless_answer_is_a_coded_error(project, monkeypatch):
    fake_ai(monkeypatch, "I do not know.")
    c = Client(project)
    context = c.ok("charpente/ai/context", {"kind": "error", "text": "x"})
    error = c.error("charpente/ai/send", {"id": context["id"], "mode": "fix"})
    assert error["data"]["code"] == "CH8021" and "no diff" in error["message"]


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_apply_rebuilds_keeps_a_good_fix_and_reports_the_gate(project, monkeypatch):
    fake_ai(monkeypatch, "```diff\n" + FIX_DIFF + "```")
    c = Client(project)
    context = c.ok("charpente/ai/context", {"kind": "error", "text": "src/main.cpp:2: error"})
    proposal = c.ok("charpente/ai/send", {"id": context["id"], "mode": "fix"})["proposal"]
    result = c.ok("charpente/ai/apply", {"proposal": proposal})
    assert result["kept"] is True and "fixed" in (project / "src" / "main.cpp").read_text(encoding="utf-8")
    assert "ok" in result["gate"] and isinstance(result["gate"]["findings"], list)


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_apply_reverts_a_fix_that_breaks_the_build(project, monkeypatch):
    broken = FIX_DIFF.replace('+#include "greet.hpp"  // fixed', '+#include "does_not_exist.hpp"')
    fake_ai(monkeypatch, "```diff\n" + broken + "```")
    c = Client(project)
    before = (project / "src" / "main.cpp").read_bytes()
    context = c.ok("charpente/ai/context", {"kind": "error", "text": "src/main.cpp:2: error"})
    proposal = c.ok("charpente/ai/send", {"id": context["id"], "mode": "fix"})["proposal"]
    result = c.ok("charpente/ai/apply", {"proposal": proposal})
    assert result["kept"] is False and "does_not_exist" in result["output"] and "gate" not in result
    assert (project / "src" / "main.cpp").read_bytes() == before


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_profile_skips_sessions_that_found_everything_up_to_date(client, project):
    ok, _, _ = client.state.compile(["app"])
    assert ok
    ok, _, _ = client.state.compile(["app"])                                                   # a second build: nothing to do, nothing recorded
    profile = client.ok("charpente/profile")
    assert profile["actions"] and profile["session"]["executed"] > 0                           # the first build, not the empty second one
    assert client.ok("charpente/profile", {"session": "latest"})["session"]["id"] == profile["session"]["id"]


# ---------------------------------------------------------------------- the debug relay
from charpente import debug as debug_mod  # noqa: E402

HAVE_GDB = any(d["name"] == "gdb" for d in debug_mod.find_debuggers())


def test_debug_methods_report_a_missing_debugger(client, monkeypatch):
    monkeypatch.setattr(debug_mod, "find_debuggers", lambda *a, **k: [])
    assert client.ok("charpente/debug/available") == {"debuggers": []}
    error = client.error("charpente/debug/start")
    assert error["data"]["code"] == "CH8023" and "gdb" in error["message"]
    assert client.error("charpente/debug/send", {"id": "nope", "message": {}})["code"] == rpc.INVALID_PARAMS
    assert client.ok("charpente/debug/stop", {"id": "nope"}) == {"stopped": False}


@pytest.mark.skipif(not (HAVE_GDB and HAVE_COMPILER), reason="needs gdb 14+ and a C++ compiler")
def test_a_debugging_session_through_the_relay(client, project):
    started = client.ok("charpente/debug/start")
    ident = started["id"]
    assert started["debugger"] in ("gdb", "lldb-dap") and client.ok("charpente/debug/available")["debuggers"]

    counter = {"seq": 0}

    def send(command, arguments=None):
        counter["seq"] += 1
        seq = [counter["seq"]]
        message = {"seq": seq[0], "type": "request", "command": command}
        if arguments is not None:
            message["arguments"] = arguments
        assert client.ok("charpente/debug/send", {"id": ident, "message": message})["sent"] is True
        return seq[0]

    def dap(predicate, timeout=120):
        assert _wait(lambda: any(m == "charpente/dap" and "message" in p and predicate(p["message"]) for m, p in client.notes), timeout)
        return next(p["message"] for m, p in client.notes if m == "charpente/dap" and "message" in p and predicate(p["message"]))

    request = send("initialize", {"adapterID": "test"})
    assert dap(lambda m: m.get("request_seq") == request)["success"]
    launch = send("launch", {"target": "app", "config": "Debug"})                            # the adapter builds the workspace's target
    dap(lambda m: m.get("event") == "initialized")
    send("configurationDone")
    assert dap(lambda m: m.get("request_seq") == launch)["success"]
    dap(lambda m: m.get("event") == "terminated")                                            # no breakpoints: it runs to the end
    assert client.ok("charpente/debug/stop", {"id": ident}) == {"stopped": True}
    assert _wait(lambda: any(m == "charpente/dap" and "exit" in p for m, p in client.notes))
