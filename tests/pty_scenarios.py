"""Scenarios that drive `charpente` in a real Windows pseudo-console (ConPTY). Run as a script by tests/test_console_pty.py:  python tests/pty_scenarios.py NAME HOME CWD

They live in their own process on purpose: creating a ConPTY inside the pytest process was found to leave the console in a state that made *later* child processes (a
node process in another test) hang. Prints PASS and exits 0, or prints the failure and exits 1.
"""
import os
import sys
import threading
import time

import pyte
import winpty

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
        return next((line for line in self.text().splitlines() if "►" in line), "")

    def close(self):
        if self.proc.isalive():
            self.proc.terminate(force=True)


def wait_for_selected(t, needle, seconds=10):
    """`t.wait_for(needle)` only waits for `needle` to appear anywhere on screen; the marker can lag behind by one redraw (seen on a loaded CI runner), so
    the selection itself is polled separately instead of asserted right away."""
    t.wait_for(needle, seconds)
    end = time.time() + seconds
    while time.time() < end and needle not in t.selected_row():
        time.sleep(0.1)
    assert needle in t.selected_row(), f"{needle!r} never selected; the screen was:\n{t.text()}"


def arrows_shortcuts_and_quit(t, tmp):
    wait_for_selected(t, "Create a new project")
    t.send("\x1b[B")                                                                # the down arrow
    end = time.time() + 10
    while time.time() < end and "Open an existing project" not in t.selected_row():
        time.sleep(0.1)
    assert "Open an existing project" in t.selected_row()
    t.send("?")                                                                     # a shortcut acts at once
    t.wait_for("Help and shortcuts")
    t.send("\r")                                                                    # Enter goes back to the menu
    t.wait_for("Create a new project")
    t.send("q")
    end = time.time() + 15
    while time.time() < end and t.proc.isalive():
        time.sleep(0.1)
    assert not t.proc.isalive() and "See you soon." in t.text()


def typing_after_navigation(t, tmp):
    t.wait_for("Create a new project")
    t.send("1")                                                                     # the template list
    t.wait_for("console")
    t.send("\x1b")                                                                  # Esc goes back
    t.wait_for("Create a new project")
    t.send("2")                                                                     # open a project: type a path that does not exist
    t.wait_for("Another folder")
    t.send("1")
    t.wait_for("Folder of the project")
    t.send("no-such-folder\r")
    t.wait_for("is not a folder")
    t.send("\x03")                                                                  # Ctrl+C cancels the question, the menu is still there
    t.wait_for("Create a new project")
    assert t.proc.isalive()
    t.send("2")                                                                     # and typing still works afterwards
    t.wait_for("Another folder")
    t.send("1")
    t.wait_for("Folder of the project")
    t.send(str(tmp) + "\r")
    t.wait_for("Now working in")


SCENARIOS = {"arrows_shortcuts_and_quit": arrows_shortcuts_and_quit, "typing_after_navigation": typing_after_navigation}

if __name__ == "__main__":
    name, home, cwd = sys.argv[1:4]
    terminal = Terminal(cwd, home)
    try:
        SCENARIOS[name](terminal, cwd)
        print("PASS")
    except AssertionError as exc:
        print(f"FAIL {name}: {exc}")
        sys.exit(1)
    finally:
        terminal.close()
