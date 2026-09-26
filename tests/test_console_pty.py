"""The console interface in a real Windows pseudo-console (ConPTY): arrow keys, shortcuts and text input as a person would use them.

Needs `pywinpty` and `pyte` (both in the dev extras); skipped everywhere else. The POSIX key reader (`PosixKeys`) has no equivalent test yet: it was not run.
"""
import os
import sys
import threading
import time

import pytest

winpty = pytest.importorskip("winpty")
pyte = pytest.importorskip("pyte")
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="ConPTY is a Windows feature")

COLS, ROWS = 100, 30


class Terminal:
    def __init__(self, cwd, home):
        env = dict(os.environ, CHARPENTE_HOME=str(home), CHARPENTE_LANG="en", CHARPENTE_TRUST_ALL="1", PYTHONIOENCODING="utf-8")
        env.pop("CHARPENTE_CONSOLE", None)
        self.proc = winpty.PtyProcess.spawn([sys.executable, "-m", "charpente"], cwd=str(cwd), dimensions=(ROWS, COLS), env=env)
        self.screen = pyte.Screen(COLS, ROWS)
        self.stream = pyte.Stream(self.screen)
        self.lock = threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while True:
            try:
                data = self.proc.read(4096)
            except Exception:
                return
            if data:
                with self.lock:
                    self.stream.feed(data)

    def text(self):
        with self.lock:
            return "\n".join(line.rstrip() for line in self.screen.display)

    def wait_for(self, needle, seconds=40):
        end = time.time() + seconds
        while time.time() < end:
            if needle in self.text():
                return self.text()
            time.sleep(0.1)
        raise AssertionError(f"never saw {needle!r}; the screen was:\n{self.text()}")

    def send(self, keys):
        self.proc.write(keys)

    def selected_row(self):
        return next((line for line in self.text().splitlines() if "►" in line or "> " in line.lstrip()[:3]), "")

    def close(self):
        if self.proc.isalive():
            self.proc.terminate(force=True)


@pytest.fixture
def terminal(tmp_path):
    t = Terminal(tmp_path, tmp_path / "home")
    yield t
    t.close()


def test_arrow_keys_shortcuts_and_quit_work_in_a_real_terminal(terminal):
    terminal.wait_for("Create a new project")
    assert "Create a new project" in terminal.selected_row()
    terminal.send("\x1b[B")                                                         # the down arrow
    end = time.time() + 10
    while time.time() < end and "Open an existing project" not in terminal.selected_row():
        time.sleep(0.1)
    assert "Open an existing project" in terminal.selected_row()
    terminal.send("?")                                                              # a shortcut acts at once
    terminal.wait_for("Help and shortcuts")
    terminal.send("\r")                                                             # Enter goes back to the menu
    terminal.wait_for("Create a new project")
    terminal.send("q")
    end = time.time() + 15
    while time.time() < end and terminal.proc.isalive():
        time.sleep(0.1)
    assert not terminal.proc.isalive() and "See you soon." in terminal.text()


def test_typing_a_line_after_key_navigation_works(terminal, tmp_path):
    terminal.wait_for("Create a new project")
    terminal.send("1")                                                              # the template list
    terminal.wait_for("console")
    terminal.send("\x1b")                                                           # Esc goes back
    terminal.wait_for("Create a new project")
    terminal.send("2")                                                              # open a project: type a path that does not exist
    terminal.wait_for("Another folder")
    terminal.send("1")
    terminal.wait_for("Folder of the project")
    terminal.send("no-such-folder\r")
    terminal.wait_for("is not a folder")
    terminal.send("\x03")                                                           # Ctrl+C cancels the question, the menu is still there
    terminal.wait_for("Create a new project")
    assert terminal.proc.isalive()
    terminal.send("2")                                                              # and typing still works afterwards
    terminal.wait_for("Another folder")
    terminal.send("1")
    terminal.wait_for("Folder of the project")
    terminal.send(str(tmp_path) + "\r")
    terminal.wait_for("Now working in")
