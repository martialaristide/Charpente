"""Charpente Studio in a real (headless) browser, talking to a real `charpente studio` process and a real project.

Skipped when no Chromium-family browser is installed. Set STUDIO_SCREENSHOTS=<folder> to keep a screenshot of each test's final state.
"""
import contextlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from browser import Cdp, find_browser
from helpers import needs_gnu_default

EXE = find_browser()
pytestmark = pytest.mark.skipif(EXE is None, reason="needs a Chromium-family browser (Edge, Chrome)")
HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++"))
HAVE_CLANGD = shutil.which("clangd") is not None
HAVE_GIT = shutil.which("git") is not None
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
SHOTS = os.environ.get("STUDIO_SCREENSHOTS")


@pytest.fixture(scope="module")
def page():
    cdp = Cdp(EXE)
    yield cdp
    cdp.close()


class Studio:
    def __init__(self, page, root, url, proc, request):
        self.page, self.root, self.url, self.proc, self.request = page, root, url, proc, request

    # --- reading and waiting
    def js(self, expression):
        return self.page.evaluate(expression)

    def wait(self, expression, timeout=60, message=""):
        return self.page.wait_for(expression, timeout, message)

    def text(self, selector):
        return self.js(f"(document.querySelector({json.dumps(selector)}) || {{textContent: ''}}).textContent")

    def count(self, selector):
        return self.js(f"document.querySelectorAll({json.dumps(selector)}).length")

    def click(self, selector):
        self.wait(f"!!document.querySelector({json.dumps(selector)})", 30, f"element {selector}")
        self.page.click(selector)

    # --- the editor
    def editor_text(self):
        return self.js("document.querySelector('.editor .input').value")

    def set_editor(self, text):
        self.js("(() => { const t = document.querySelector('.editor .input'); t.value = " + json.dumps(text) + "; t.dispatchEvent(new Event('input', {bubbles: true})); })()")

    def open_file(self, path):
        self.js(f"studio.openFile({json.dumps(path)})")
        self.wait(f"studio.activePath === {json.dumps(path)}", 30, f"{path} to open")

    def save(self):
        self.js("document.querySelector('.editor .input').focus()")
        self.page.press("s", code="KeyS", modifiers=2, windows_virtual_key_code=83)

    def build(self, timeout=180):
        finished = self.js("studio.tasks || 0")
        self.click("#btn-build")
        self.wait(f"(studio.tasks || 0) > {finished}", timeout, "the build to finish")

    def build_ok(self):
        return "ok" in self.js("document.querySelector('#panel-build .summary').className")

    def panel(self, name):
        self.click(f"#tab-{name}")
        self.wait(f"!document.querySelector('#panel-{name}').hidden", 10, f"{name} panel")

    def problems(self):
        return self.js("[...document.querySelectorAll('#panel-problems .problem')].map(e => e.textContent)")


@contextlib.contextmanager
def launched(page, tmp_path, request, extra_env=None):
    if not HAVE_COMPILER:
        pytest.skip("needs a C++ compiler")
    env = dict(os.environ, CHARPENTE_TRUST_ALL="1", CHARPENTE_LANG="en")
    env.pop("CHARPENTE_AI_URL", None)
    env.update(extra_env or {})
    subprocess.run([sys.executable, "-m", "charpente", "init", "demo", "--template", "console", "--dir", str(tmp_path / "demo")], check=True, env=env, cwd=tmp_path,
                   capture_output=True)
    root = tmp_path / "demo"
    if HAVE_GIT:
        for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "Tester"], ["config", "commit.gpgsign", "false"],
                     ["add", "-A"], ["commit", "-q", "-m", "chore: initial"]):
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    proc = subprocess.Popen([sys.executable, "-m", "charpente", "studio", "--no-browser", "--json", "--root", str(root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)
    url = json.loads(proc.stdout.readline())["charpente-studio"]["url"]
    threading.Thread(target=proc.stderr.read, daemon=True).start()
    page.console.clear()
    page.exceptions.clear()
    page.navigate("about:blank")
    page.navigate(url)
    s = Studio(page, root, url, proc, request)
    try:
        s.wait("window.studio && window.studio.ready", 60, "Studio to be ready")
        yield s
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            page.screenshot(Path(SHOTS) / f"{request.node.name}.png")
    finally:
        proc.kill()
        proc.wait(timeout=30)
    assert not page.exceptions, page.exceptions                                     # an uncaught error in the page fails the test that caused it


@pytest.fixture
def studio(page, tmp_path, request):
    with launched(page, tmp_path, request) as s:
        yield s


# ---------------------------------------------------------------------- loading
def test_it_loads_and_shows_the_project(studio):
    assert studio.text("#project") == "demo" and studio.js("document.title") == "Charpente Studio"
    assert studio.js("studio.targets.map(t => t.displayName).sort()") == ["demo", "demo_core", "demo_tests"]
    assert studio.js("studio.activePath") == "demo.charpente"                        # the workspace file is opened first
    assert studio.count(".editor .hl .tok-keyword") > 0 and studio.count(".editor .hl .tok-dsl") > 0     # highlighted, with the DSL's names emphasised
    assert "with Workspace" in studio.editor_text()
    studio.js("document.querySelector('#sidetab-targets').click()")
    assert studio.count(".target-list .target") == 3
    assert studio.js("location.search") == ""                                        # the token was removed from the address bar
    assert studio.js("document.getElementById('boot').hidden") is True
    assert studio.count(".tab.dirty") == 0                                           # opening a file is not an edit (even with CRLF line endings)
    assert not [m for m in studio.page.console if "error" in m.lower()], studio.page.console


def test_language_and_theme_are_remembered(studio):
    assert studio.text("#btn-build") == "Build"
    studio.js("(() => { const l = document.getElementById('lang'); l.value = 'fr'; l.dispatchEvent(new Event('change')); })()")
    studio.page.pump(0.5)
    studio.wait("window.studio && window.studio.ready && document.getElementById('btn-build').textContent === 'Construire'", 60, "French UI")
    assert studio.js("document.documentElement.lang") == "fr" and studio.text("#tab-problems").startswith("Problèmes")
    studio.click("#btn-theme")
    assert studio.js("document.documentElement.dataset.theme") == "light"
    studio.click("#btn-theme")
    assert studio.js("document.documentElement.dataset.theme") == "dark"
    assert studio.js("localStorage.getItem('charpente-theme')") == "dark" and studio.js("localStorage.getItem('charpente-lang')") == "fr"


def test_a_wrong_token_is_explained(page, tmp_path):
    proc = subprocess.Popen([sys.executable, "-m", "charpente", "studio", "--no-browser", "--json", "--root", str(tmp_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=dict(os.environ, CHARPENTE_TRUST_ALL="1"))
    try:
        url = json.loads(proc.stdout.readline())["charpente-studio"]["url"]
        page.navigate("about:blank")
        page.navigate(url.split("?")[0] + "?token=not-the-token")
        page.wait_for("document.getElementById('boot').textContent.includes('Cannot reach')", 30, "the error message")
        assert page.evaluate("document.getElementById('app').hidden") is True
        page.navigate("about:blank")
        page.navigate(url.split("?")[0].replace("127.0.0.1", "localhost"))               # another origin, so no token is remembered
        page.wait_for("document.getElementById('boot').textContent.includes('address printed')", 30, "the no-token message")
    finally:
        proc.kill()
        proc.wait(timeout=30)
        page.exceptions.clear()


# ---------------------------------------------------------------------- build, run, profile
def test_build_run_graph_and_profile(studio):
    studio.build()
    assert studio.build_ok() and "Build succeeded" in studio.text("#panel-build .summary")
    studio.js("document.querySelector('#sidetab-targets').click()")
    assert studio.js("[...document.querySelectorAll('.target-list .target')].map(e => e.className.includes('status-ok') || e.className.includes('status-upToDate'))") == [True, True, True]
    assert studio.js("document.querySelector('#panel-build progress').value") == studio.js("document.querySelector('#panel-build progress').max")
    studio.js("studio.run('demo')")
    studio.wait("document.querySelector('#panel-build').textContent.includes('Hello, world!')", 120, "the program's output")
    studio.wait("!document.body.classList.contains('busy')", 60, "the run to end")
    assert "Program finished" in studio.text("#panel-build .summary")
    studio.panel("graph")
    studio.wait("document.querySelectorAll('#panel-graph svg .graph-node').length === 3", 30, "graph nodes")
    assert "demo_core" in studio.text("#panel-graph .muted") and studio.count("#panel-graph .graph-node.critical") >= 2
    studio.panel("profile")
    studio.wait("document.querySelectorAll('#panel-profile .bar-row').length > 3", 30, "profile bars")
    assert "demo_core" in studio.text("#panel-profile") and "greet" in studio.text("#panel-profile")
    studio.js("document.querySelector('#tab-problems').click()")
    assert studio.count("#panel-problems .problem") == 0


def test_the_platform_field_is_used_by_builds(studio):
    studio.js("(() => { const p = document.getElementById('platform'); p.value = 'no-such-platform'; p.dispatchEvent(new Event('change')); })()")
    studio.js("document.getElementById('btn-build').click()")
    studio.wait("document.querySelector('#panel-build .summary').className.includes('fail')", 60, "the failed build")
    assert "no-such-platform" in studio.text("#panel-build .log")                      # Charpente's own error names the platform


def test_a_compile_error_appears_where_it_is_and_disappears_when_fixed(studio):
    studio.open_file("src/main.cpp")
    original = studio.editor_text()
    broken = original.replace("return 0;", "return missing_name;")
    studio.set_editor(broken)
    assert studio.count(".tab.dirty") == 1                                             # unsaved changes are marked
    studio.build()                                                                     # saves first, then builds
    assert not studio.build_ok()
    assert (studio.root / "src" / "main.cpp").read_bytes().decode().replace("\r\n", "\n") == broken.replace("\r\n", "\n")
    studio.wait("document.querySelectorAll('#panel-problems .problem.error').length > 0", 30, "a problem")
    assert any("missing_name" in p for p in studio.problems())
    assert studio.count(".editor .gutter .mark-err") >= 1 and studio.count(".editor .hl .ln-err") >= 1
    assert "⛔" in studio.text("#tab-problems") and studio.text("#problem-status").startswith("⛔ ")
    studio.js("document.querySelector('#panel-problems .problem-row').click()")
    line = [n for n, text in enumerate(broken.splitlines(), 1) if "missing_name" in text][0]
    studio.wait(f"document.getElementById('cursor').textContent.includes('Ln {line},')", 10, "the cursor on the error line")
    assert studio.count("#panel-build a.loc") >= 1                                     # the build log links to the location
    studio.set_editor(original)
    studio.build()
    assert studio.build_ok(), studio.text("#panel-build .log")
    studio.wait("document.querySelectorAll('#panel-problems .problem').length === 0", 30, "problems to clear")
    assert studio.count(".editor .hl .ln-err") == 0


def test_explain_offers_the_documentation_of_an_error_code(studio):
    studio.js("document.getElementById('platform').value = 'no-such-platform'; document.getElementById('btn-build').click()")
    studio.wait("document.querySelector('#panel-build .summary').className.includes('fail')", 60, "the failed build")
    studio.wait("[...document.querySelectorAll('#panel-build .line button')].some(b => b.textContent === 'Explain')", 30, "an Explain button")
    studio.js("[...document.querySelectorAll('#panel-build .line button')].find(b => b.textContent === 'Explain').click()")
    studio.wait("!document.querySelector('#panel-build .explain').hidden && document.querySelector('#panel-build .explain pre').textContent.length > 20", 30, "the explanation")


# ---------------------------------------------------------------------- the editor
def test_typing_indentation_and_completion(studio):
    studio.js("studio.ask = studio.ask; 0")
    studio.open_file("demo.charpente")
    text = studio.editor_text()
    end = len(text)
    studio.js(f"(() => {{ const t = document.querySelector('.editor .input'); t.focus(); t.setSelectionRange({end}, {end}); }})()")
    studio.page.press("Enter", code="Enter", windows_virtual_key_code=13)
    studio.page.press("Tab", code="Tab", windows_virtual_key_code=9)
    assert studio.editor_text().endswith("\n    "), repr(studio.editor_text()[-12:])       # Enter kept indentation 0, Tab added four spaces
    studio.page.type_text(".editor .input", "core.sou")
    studio.wait("!document.querySelector('.editor .completion').hidden", 15, "the completion popup")
    assert studio.js("[...document.querySelectorAll('.editor .completion .label')].map(e => e.textContent)")[0] == "sources"
    studio.page.press("Enter", code="Enter", windows_virtual_key_code=13)
    assert studio.editor_text().endswith("core.sources("), repr(studio.editor_text()[-20:])
    assert studio.js("document.querySelector('.editor .completion').hidden") is True
    studio.page.press("Escape", code="Escape", windows_virtual_key_code=27)


def test_save_conflict_and_unsaved_changes(studio):
    studio.open_file("README.md")
    studio.set_editor("# mine\n")
    (studio.root / "README.md").write_text("# someone else\n", encoding="utf-8")            # changed on disk after we opened it
    studio.save()
    studio.wait("document.getElementById('modal').open", 15, "the conflict dialog")
    assert "changed on disk" in studio.text("#modal")
    studio.js("[...document.querySelectorAll('#modal button')].find(b => b.textContent === 'Overwrite').click()")
    studio.wait("!document.getElementById('modal').open && studio.activePath === 'README.md' && !document.querySelector('.tab.dirty')", 15, "the save")
    assert (studio.root / "README.md").read_text(encoding="utf-8") == "# mine\n"
    studio.set_editor("# dirty again\n")
    studio.js("document.querySelector('.tab.active .tab-close').click()")
    studio.wait("document.getElementById('modal').open", 10, "the discard question")
    studio.js("[...document.querySelectorAll('#modal button')].find(b => b.textContent === 'Cancel').click()")
    assert studio.editor_text() == "# dirty again\n"                                       # nothing was lost


def test_a_new_file_can_be_created_and_edited(studio):
    studio.js("studio.ask = () => Promise.resolve('src/extra.cpp'); 0")
    studio.click("#side-files .toolbar button")
    studio.wait("studio.activePath === 'src/extra.cpp'", 20, "the new file")
    studio.set_editor("int extra() { return 42; }\n")
    studio.save()
    studio.wait("!document.querySelector('.tab.dirty')", 15, "the save")
    assert "return 42" in (studio.root / "src" / "extra.cpp").read_text(encoding="utf-8")
    studio.wait("[...document.querySelectorAll('#side-files .tree-row')].some(e => e.dataset.path === 'src/extra.cpp')", 20, "the file in the explorer")


def test_the_command_palette_and_shortcuts(studio):
    studio.js("document.body.focus()")
    studio.page.press("P", code="KeyP", modifiers=2 | 8, windows_virtual_key_code=80)             # Ctrl+Shift+P
    studio.wait("document.getElementById('palette').open", 10, "the palette")
    studio.page.type_text("#palette input", "theme")
    assert studio.js("document.querySelectorAll('#palette li').length") == 1
    studio.page.press("Enter", code="Enter", windows_virtual_key_code=13)
    studio.wait("document.documentElement.dataset.theme === 'light'", 10, "the theme command")
    studio.page.press("F7", code="F7", windows_virtual_key_code=118)                                # build with the keyboard
    studio.wait("document.body.classList.contains('busy') || document.querySelector('#panel-build .summary').className.includes('ok')", 60, "F7 to build")
    studio.wait("!document.body.classList.contains('busy')", 180, "the build to end")


# ---------------------------------------------------------------------- terminal, git, options, packages, devices
def test_terminal_runs_commands_in_the_project_environment(studio):
    studio.panel("terminal")
    py = sys.executable.replace("\\", "/")
    studio.page.type_text(".terminal:not([hidden]) .terminal-input", f'"{py}" -c "import os; print(6*7); print(os.environ[\'CHARPENTE_SHELL\'])"')
    studio.page.press("Enter", code="Enter", windows_virtual_key_code=13)
    studio.wait("document.querySelector('.terminal:not([hidden]) .log').textContent.includes('exited with code 0')", 60, "the command to finish")
    lines = studio.js("[...document.querySelectorAll('.terminal:not([hidden]) .log .line')].map(e => e.textContent)")
    assert "42" in lines and "1" in lines                                                   # the program's output, and CHARPENTE_SHELL from the project environment
    studio.page.type_text(".terminal:not([hidden]) .terminal-input", "no-such-program-xyz")
    studio.page.press("Enter", code="Enter", windows_virtual_key_code=13)
    studio.wait("document.querySelector('.terminal:not([hidden]) .log').textContent.includes('was not found')", 30, "the error")
    studio.click(".subtab.plus")                                                              # several terminals
    assert studio.count(".terminals .terminal") == 2 and studio.count(".subtabs .subtab:not(.plus)") == 2


def test_terminal_can_stop_a_running_command(studio):
    studio.panel("terminal")
    py = sys.executable.replace("\\", "/")
    studio.page.type_text(".terminal:not([hidden]) .terminal-input", f'"{py}" -c "import time; print(\'re\' + \'ady\', flush=True); time.sleep(120)"')
    studio.page.press("Enter", code="Enter", windows_virtual_key_code=13)
    studio.wait("[...document.querySelectorAll('.terminal:not([hidden]) .log .line')].some(e => e.textContent === 'ready')", 30, "the command to start")
    studio.js("[...document.querySelectorAll('.terminal:not([hidden]) button')].find(b => b.textContent.includes('Stop')).click()")
    studio.wait("document.querySelector('.terminal:not([hidden]) .log').textContent.includes('exited with code')", 30, "the command to stop")
    assert studio.js("document.querySelector('.terminal:not([hidden]) .terminal-input').disabled") is False


@pytest.mark.skipif(not HAVE_GIT, reason="needs git")
def test_git_panel_stages_a_hunk_and_commits(studio):
    lines = "".join(f"line {i}\n" for i in range(1, 41))
    (studio.root / "notes.txt").write_text(lines, encoding="utf-8")
    subprocess.run(["git", "-C", str(studio.root), "add", "notes.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(studio.root), "commit", "-q", "-m", "chore: add notes"], check=True, capture_output=True)
    changed = lines.replace("line 2\n", "line two\n").replace("line 39\n", "line thirty-nine\n")
    (studio.root / "notes.txt").write_text(changed, encoding="utf-8")
    studio.panel("git")
    studio.wait("document.querySelectorAll('#panel-git .git-files li').length >= 1", 30, "the change list")
    assert "notes.txt" in studio.text("#panel-git .git-sections")
    studio.js("[...document.querySelectorAll('#panel-git .git-files .file-name')].find(b => b.textContent === 'notes.txt').click()")
    studio.wait("document.querySelectorAll('#panel-git .hunk').length === 2", 30, "two hunks")
    studio.js("document.querySelector('#panel-git .hunk .hunk-head button').click()")                      # stage only the first block
    studio.wait("document.querySelector('#panel-git .git-sections').textContent.includes('Staged (1)')", 30, "the staged file")
    staged = subprocess.run(["git", "-C", str(studio.root), "diff", "--cached"], capture_output=True, text=True).stdout
    assert "line two" in staged and "thirty-nine" not in staged
    studio.js("document.querySelector('#panel-git .commit-message').value = 'fix: correct line two'")
    studio.js("document.getElementById('skip-gate').checked = true")
    studio.js("document.querySelector('#panel-git .commit-box button.primary').click()")
    studio.wait("document.querySelector('#panel-git .git-log').textContent.includes('fix: correct line two')", 60, "the commit in the history")
    assert subprocess.run(["git", "-C", str(studio.root), "log", "-1", "--format=%s"], capture_output=True, text=True).stdout.strip() == "fix: correct line two"
    assert "thirty-nine" in subprocess.run(["git", "-C", str(studio.root), "diff"], capture_output=True, text=True).stdout      # the other block is still unstaged


@pytest.mark.skipif(not HAVE_GIT, reason="needs git")
def test_git_commit_without_a_message_is_refused_politely(studio):
    (studio.root / "README.md").write_text("changed\n", encoding="utf-8")
    studio.panel("git")
    studio.wait("document.querySelectorAll('#panel-git .git-files li').length >= 1", 30, "the change list")
    studio.js("document.querySelector('#panel-git .commit-box button.primary').click()")
    studio.wait("document.querySelectorAll('#toasts .toast.error').length > 0", 10, "the toast")
    assert "commit message" in studio.text("#toasts .toast")


def test_options_are_saved_and_packages_can_be_added_and_removed(studio):
    workspace = (studio.root / "demo.charpente").read_text(encoding="utf-8")
    (studio.root / "demo.charpente").write_text(workspace.replace('    ws.configurations(["Debug", "Release"])',
                                                                  '    ws.configurations(["Debug", "Release"])\n    ws.option("fast", default=False, help="Go fast")'), encoding="utf-8")
    studio.click("#btn-reload")
    studio.js("document.querySelector('#sidetab-options').click()")
    studio.wait("!!document.querySelector('#side-options input[data-option=fast]')", 30, "the option")
    studio.js("document.querySelector('#side-options input[data-option=fast]').click()")
    studio.wait("(studio.info.options.fast || {}).value === 'true'", 30, "the option to be saved")
    assert "fast = true" in (studio.root / ".charpente" / "options.toml").read_text(encoding="utf-8")
    studio.js("document.querySelector('#sidetab-packages').click()")
    studio.js("(() => { const s = document.querySelector('#side-packages input[type=search]'); s.value = 'fm'; s.dispatchEvent(new Event('input')); })()")
    studio.wait("[...document.querySelectorAll('#side-packages .package-results li')].some(li => li.textContent.includes('fmt'))", 30, "search results")
    studio.js("[...document.querySelectorAll('#side-packages .package-results li')].find(li => li.textContent.includes('fmt')).querySelector('button').click()")
    studio.wait("document.querySelector('#side-packages .package-current').textContent.includes('fmt')", 30, "fmt in the requirements")
    assert 'ws.requires("fmt")' in (studio.root / "demo.charpente").read_text(encoding="utf-8")
    assert "CH6005" in studio.js("studio.info.notice")                                            # declared but not installed: said, not fatal
    studio.js("document.querySelector('#side-packages .package-current button').click()")
    studio.wait("!document.querySelector('#side-packages .package-current').textContent.includes('fmt')", 30, "fmt removed")
    assert 'ws.requires("fmt")' not in (studio.root / "demo.charpente").read_text(encoding="utf-8")


def test_devices_panel_reports_missing_tools_instead_of_failing(studio):
    studio.panel("devices")
    studio.wait("document.querySelector('#panel-devices .devices').textContent.length > 0", 60, "the device list")
    assert studio.js("document.querySelector('#panel-devices .devices').textContent") != ""
    assert not studio.js("document.querySelector('#panel-devices').textContent.includes('undefined')")


def test_a_lost_connection_is_shown(studio):
    studio.proc.kill()
    studio.wait("document.getElementById('connection').dataset.status === 'closed'", 30, "the closed connection")
    assert "connection to the Charpente server was lost" in studio.text("#toasts")
    studio.page.exceptions.clear()                                                              # requests after this fail cleanly, not as page errors
    studio.js("document.getElementById('btn-reload').click()")
    studio.page.pump(0.5)


# ---------------------------------------------------------------------- language server
@pytest.mark.skipif(not HAVE_CLANGD, reason="needs clangd")
def test_clangd_diagnostics_and_go_to_definition_in_the_editor(studio):
    studio.open_file("src/main.cpp")
    studio.wait("document.getElementById('lsp').textContent.includes('clangd')", 60, "clangd to start")
    text = studio.editor_text()
    studio.set_editor(text.replace("return 0;", "return missing_name;"))
    studio.wait("document.querySelectorAll('#panel-problems .problem').length > 0", 60, "a clangd diagnostic")
    assert any("missing_name" in p and "clang" in p for p in studio.problems()), studio.problems()
    assert studio.count(".editor .hl .ln-err") >= 1
    studio.set_editor(text)
    studio.wait("document.querySelectorAll('#panel-problems .problem').length === 0", 60, "diagnostics to clear")
    offset = text.index("greet(") + 2
    studio.js(f"(() => {{ const t = document.querySelector('.editor .input'); t.focus(); t.setSelectionRange({offset}, {offset}); }})()")
    studio.page.press("F12", code="F12", windows_virtual_key_code=123)
    studio.wait("studio.activePath && studio.activePath.includes('greet')", 60, "the definition to open")


# ---------------------------------------------------------------------- assistant
class FakeAi(http.server.BaseHTTPRequestHandler):
    requests = []
    answers = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeAi.requests.append(body)
        answer = FakeAi.answers.pop(0) if len(FakeAi.answers) > 1 else FakeAi.answers[0]
        data = json.dumps({"choices": [{"message": {"content": answer}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_ai():
    FakeAi.requests, FakeAi.answers = [], ["default answer"]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeAi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


@pytest.fixture
def studio_ai(fake_ai, page, tmp_path, request):
    with launched(page, tmp_path, request, {"CHARPENTE_AI_URL": fake_ai}) as s:
        yield s


def click_button(studio, scope, label, exact=True):
    test = f"b.textContent === {json.dumps(label)}" if exact else f"b.textContent.includes({json.dumps(label)})"
    studio.js(f"[...document.querySelectorAll({json.dumps(scope)} + ' button')].find(b => {test}).click()")


def test_the_assistant_shows_what_it_sends_and_sends_only_after_you_agree(studio_ai):
    s = studio_ai
    FakeAi.answers = ["The variable is not declared. Declare it."]
    (s.root / "src" / "main.cpp").write_text(f'#include <cstdio>\nconst char* key = "{AWS_KEY}";\nint main() {{ return missing_name; }}\n', encoding="utf-8")
    s.js("document.querySelector('#tab-ai').click()")
    s.wait("document.querySelector('#panel-ai .ai-status').className.includes('ok')", 30, "the provider to be ready")
    s.build()
    assert not s.build_ok()
    click_button(s, "#panel-build .toolbar", "Explain with AI", exact=False)
    s.wait("!document.querySelector('#panel-ai .ai-review').hidden", 30, "the review of what would be sent")
    assert FakeAi.requests == []                                                           # nothing was sent yet
    review = s.text("#panel-ai .ai-review")
    assert "would be sent to local" in review and "build output" in review and "secret(s) replaced" in review
    assert AWS_KEY not in s.js("document.querySelector('#panel-ai .ai-exact').textContent")
    click_button(s, "#panel-ai .ai-review", "Send")
    s.wait("!!document.querySelector('#panel-ai .ai-answer')", 30, "the answer")
    assert "not declared" in s.text("#panel-ai .ai-answer")
    assert len(FakeAi.requests) == 1
    sent = json.dumps(FakeAi.requests[0])
    assert "missing_name" in sent and AWS_KEY not in sent                                    # the code is sent; the secret never leaves the machine


def test_the_assistant_proposes_a_diff_that_is_applied_only_on_request(studio_ai):
    s = studio_ai
    original = (s.root / "src" / "main.cpp").read_bytes().decode("utf-8").replace("\r\n", "\n")
    first = original.split("\n")[:5]
    diff = ("```diff\n--- a/src/main.cpp\n+++ b/src/main.cpp\n@@ -1,5 +1,5 @@\n" + "\n".join(" " + line for line in first[:3]) + "\n-" + first[3]
            + "\n+" + first[3] + "  // checked\n " + first[4] + "\n```")
    FakeAi.answers = ["Add a comment.\n" + diff]
    before = (s.root / "src" / "main.cpp").read_bytes()
    s.js("document.querySelector('#tab-ai').click()")
    s.js("(() => { document.querySelector('#panel-ai textarea').value = 'src/main.cpp:1: error: x'; document.querySelector('#panel-ai select').value = 'error'; })()")
    click_button(s, "#panel-ai .toolbar", "Prepare")
    s.wait("!document.querySelector('#panel-ai .ai-review').hidden", 30, "the review")
    click_button(s, "#panel-ai .ai-review", "fix", exact=False)                              # "Ask for a fix instead"
    click_button(s, "#panel-ai .ai-review", "Send")
    s.wait("!!document.querySelector('#panel-ai .ai-diff')", 30, "the proposed diff")
    assert (s.root / "src" / "main.cpp").read_bytes() == before                              # nothing changed yet
    assert s.count("#panel-ai .ai-diff .add") == 1 and s.count("#panel-ai .ai-diff .del") == 1
    click_button(s, "#panel-ai", "Apply, rebuild and check")
    s.wait("document.querySelector('#panel-ai .ai-result').textContent.includes('Applied to')", 240, "the fix to be applied")
    assert b"// checked" in (s.root / "src" / "main.cpp").read_bytes()


def test_without_a_provider_the_assistant_says_so(studio):
    studio.js("document.querySelector('#tab-ai').click()")
    studio.wait("document.querySelector('#panel-ai .ai-status').textContent.length > 0", 30, "the status")
    assert "No AI provider is configured" in studio.text("#panel-ai .ai-status") and "off" in studio.js("document.querySelector('#panel-ai .ai-status').className")
    studio.js("document.querySelector('#panel-ai textarea').value = 'why?'")
    click_button(studio, "#panel-ai .toolbar", "Prepare")
    studio.wait("!document.querySelector('#panel-ai .ai-review').hidden", 30, "the review")
    assert studio.js("[...document.querySelectorAll('#panel-ai .ai-review button')].find(b => b.textContent === 'Send').disabled") is True      # cannot send without a provider


# ---------------------------------------------------------------------- debugging
HAVE_GDB = any(d["name"] == "gdb" for d in __import__("charpente.debug", fromlist=["find_debuggers"]).find_debuggers())


@pytest.mark.skipif(not HAVE_GDB, reason="needs gdb 14+")
@needs_gnu_default
def test_debugging_a_program_from_the_editor(studio):
    studio.open_file("src/main.cpp")
    line = [n for n, text in enumerate(studio.editor_text().splitlines(), 1) if "std::printf" in text][0]
    studio.js(f"document.querySelector('.editor .gutter span[data-line=\"{line}\"]').dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}}))")
    studio.wait(f"document.querySelector('.editor .gutter span[data-line=\"{line}\"]').classList.contains('bp')", 10, "the breakpoint marker")
    assert studio.js("JSON.stringify(Object.fromEntries([...studio.breakpoints].map(([p, l]) => [p, [...l]])))") == json.dumps({"src/main.cpp": [line]}, separators=(",", ":"))
    studio.panel("debug")
    studio.wait("document.querySelectorAll('#panel-debug select option').length > 0", 15, "the debug targets")
    studio.js("document.querySelector('#panel-debug select').value = 'demo'")
    studio.js("document.querySelector('#panel-debug input').value = 'Ada'")
    click_button(studio, "#panel-debug .toolbar", "Debug", exact=False)
    studio.wait("document.querySelector('#panel-debug .debug-status').textContent.startsWith('Stopped')", 240, "the program to stop at the breakpoint")
    assert "breakpoint" in studio.text("#panel-debug .debug-status")
    studio.wait("document.querySelectorAll('#panel-debug .debug-stack .frame').length > 0", 30, "the call stack")
    assert studio.js("document.querySelector('#panel-debug .debug-stack .frame strong').textContent") == "main"
    studio.wait(f"document.querySelector('.editor .gutter span[data-line=\"{line}\"]').classList.contains('exec')", 30, "the execution marker")
    assert studio.count(".editor .hl .ln-exec") == 1
    studio.wait("document.querySelector('#panel-debug .debug-variables').textContent.includes('argc')", 30, "the variables")
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        studio.page.screenshot(Path(SHOTS) / "debugging_stopped.png")
    assert "argc = 2" in studio.text("#panel-debug .debug-variables").replace("\xa0", " ")           # the program's argument arrived
    studio.js("(() => { const w = document.querySelector('#panel-debug .debug-columns input'); w.value = 'argc + 40'; w.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter'})); })()")
    studio.wait("document.querySelector('#panel-debug pre').textContent.includes('= 42')", 30, "the evaluated expression")
    click_button(studio, "#panel-debug .toolbar", "Step over")
    studio.wait(f"document.querySelector('.editor .gutter span[data-line=\"{line + 1}\"]').classList.contains('exec')", 30, "the next line")
    click_button(studio, "#panel-debug .toolbar", "Continue")
    studio.wait("document.querySelector('#panel-debug .debug-status').textContent === 'Not debugging'", 60, "the session to end")
    assert "Hello, Ada!" in studio.text("#panel-debug .log")
    assert studio.count(".editor .gutter .exec") == 0                                          # the execution marker is gone
    studio.js(f"document.querySelector('.editor .gutter span[data-line=\"{line}\"]').dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}}))")
    studio.wait("studio.breakpoints.size === 0", 10, "the breakpoint to be removed")
