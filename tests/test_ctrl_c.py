"""Ctrl+C must stop the long-running commands (`charpente studio`, `serve --ws`, `deploy --logs`...).

On Windows a bare `Event().wait()` cannot be interrupted, so a server that waited that way ignored Ctrl+C. The portable tests check the waiting helper; the Windows tests
deliver a *real* Ctrl+C console event to a real command running in its own console.
"""
import base64
import os
import re
import socket
import subprocess
import sys
import threading
import time

import pytest

from charpente.commands._common import wait_until_interrupted
from charpente.multideploy import Device, LogMerger


# ---------------------------------------------------------------------- portable
def test_the_wait_returns_true_when_told_to_stop_and_false_on_ctrl_c():
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    assert wait_until_interrupted(stop, tick=0.05) is True

    class Interrupted:
        def wait(self, timeout=None):
            raise KeyboardInterrupt

    assert wait_until_interrupted(Interrupted()) is False           # type: ignore[arg-type]


def test_the_wait_is_made_of_short_slices_so_that_an_interrupt_can_be_delivered():
    slices = []

    class Recording:
        def __init__(self):
            self.calls = 0

        def wait(self, timeout=None):
            slices.append(timeout)
            self.calls += 1
            return self.calls >= 4

    assert wait_until_interrupted(Recording(), tick=0.1) is True    # type: ignore[arg-type]
    assert slices == [0.1] * 4 and None not in slices                # never one unbounded wait


def test_the_log_follower_also_waits_in_short_slices():
    class Never:
        def __init__(self, argv, on_line, on_exit):
            self.on_exit = on_exit

        def stop(self):
            pass

    merger = LogMerger("adb", [Device("A")], lambda s, line: None, start=Never)
    started = time.monotonic()
    assert merger.wait(0.6) is False and 0.5 < time.monotonic() - started < 3
    merger.stop()
    assert merger.wait(0.05) is True


# ---------------------------------------------------------------------- Windows: a real Ctrl+C
pytestmark_windows = pytest.mark.skipif(sys.platform != "win32", reason="delivers a Windows console Ctrl+C event")
CREATE_NEW_CONSOLE = 0x00000010
PRELUDE = "import ctypes;ctypes.windll.kernel32.SetConsoleCtrlHandler(None,False);"      # a normal console session does not ignore Ctrl+C


def send_ctrl_c(pid):
    """Deliver CTRL_C_EVENT to the console of `pid` (from a throw-away helper process, so this test process keeps its own console)."""
    helper = (
        "import ctypes,sys,time\n"
        "k=ctypes.windll.kernel32\n"
        "k.FreeConsole()\n"
        "assert k.AttachConsole(int(sys.argv[1]))\n"
        "k.SetConsoleCtrlHandler(None,True)\n"
        "k.GenerateConsoleCtrlEvent(0,0)\n"
        "time.sleep(0.5)\n"
        "k.FreeConsole()\n")
    subprocess.run([sys.executable, "-c", helper, str(pid)], check=True)


def start(args, tmp_path, keep_stdin=False):
    log = open(tmp_path / "out.log", "wb")
    code = PRELUDE + "import sys,runpy;sys.argv=['charpente']+" + repr(args) + ";runpy.run_module('charpente',run_name='__main__')"
    env = dict(os.environ, CHARPENTE_TRUST_ALL="1", CHARPENTE_HOME=str(tmp_path / "home"), PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=tmp_path, env=env, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.PIPE if keep_stdin else subprocess.DEVNULL, creationflags=CREATE_NEW_CONSOLE)
    return proc, tmp_path / "out.log"


def wait_for_text(path, needle, seconds=60):
    end = time.time() + seconds
    while time.time() < end:
        text = path.read_bytes().decode("utf-8", "replace")
        if needle in text:
            return text
        time.sleep(0.2)
    raise AssertionError(f"never printed {needle!r}: {path.read_bytes().decode('utf-8', 'replace')[-500:]}")


def assert_stops_after_ctrl_c(proc, seconds=15):
    time.sleep(1.0)
    send_ctrl_c(proc.pid)
    end = time.time() + seconds
    while proc.poll() is None and time.time() < end:
        time.sleep(0.1)
    stopped = proc.poll() is not None
    if not stopped:
        proc.kill()
    assert stopped, "Ctrl+C did not stop the command"
    return proc.returncode


@pytestmark_windows
def test_a_bare_event_wait_really_ignores_ctrl_c_here_so_the_next_tests_mean_something(tmp_path):
    log = open(tmp_path / "bare.log", "wb")
    code = PRELUDE + "import threading;print('READY',flush=True);threading.Event().wait()"
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=CREATE_NEW_CONSOLE)
    try:
        wait_for_text(tmp_path / "bare.log", "READY")
        time.sleep(1.0)
        send_ctrl_c(proc.pid)
        time.sleep(3)
        assert proc.poll() is None                                   # the old behaviour: still running after Ctrl+C
    finally:
        proc.kill()


@pytestmark_windows
def test_ctrl_c_stops_charpente_studio(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    (tmp_path / "p.charpente").write_text('from charpente import *\nwith Workspace("p") as ws:\n    with Target("p") as t:\n        t.kind(Kind.EXECUTABLE)\n        t.sources(["src/*.cpp"])\n',
                                          encoding="utf-8")
    proc, log = start(["studio", "--no-browser"], tmp_path)
    wait_for_text(log, "Press Ctrl+C")
    assert assert_stops_after_ctrl_c(proc) == 0
    assert "Stopping Studio." in log.read_bytes().decode("utf-8", "replace")


@pytestmark_windows
def test_ctrl_c_stops_studio_while_a_browser_is_connected(tmp_path):
    (tmp_path / "p.charpente").write_text('from charpente import *\nwith Workspace("p") as ws:\n    pass\n', encoding="utf-8")
    proc, log = start(["studio", "--no-browser"], tmp_path)
    text = wait_for_text(log, "Press Ctrl+C")
    port, token = re.search(r"http://127\.0\.0\.1:(\d+)/\?token=([\w-]+)", text).groups()
    crlf = "\r\n"
    held = socket.create_connection(("127.0.0.1", int(port)), timeout=10)
    try:
        request = (f"GET /?token={token} HTTP/1.1" + crlf + f"Host: 127.0.0.1:{port}" + crlf + f"Origin: http://127.0.0.1:{port}" + crlf + "Upgrade: websocket" + crlf
                   + "Connection: Upgrade" + crlf + f"Sec-WebSocket-Key: {base64.b64encode(os.urandom(16)).decode()}" + crlf + "Sec-WebSocket-Version: 13" + crlf + crlf)
        held.sendall(request.encode())
        assert b" 101 " in held.recv(200)                            # the page's connection is open and stays open
        assert_stops_after_ctrl_c(proc)
    finally:
        held.close()


@pytestmark_windows
def test_ctrl_c_stops_the_websocket_server_even_while_its_input_is_open(tmp_path):
    (tmp_path / "p.charpente").write_text('from charpente import *\nwith Workspace("p") as ws:\n    pass\n', encoding="utf-8")
    proc, log = start(["serve", "--ws"], tmp_path, keep_stdin=True)
    try:
        wait_for_text(log, "charpente-server")
        assert assert_stops_after_ctrl_c(proc) == 0                  # not the fatal "could not acquire lock ... at interpreter shutdown" it used to end with
        assert "Fatal Python error" not in log.read_bytes().decode("utf-8", "replace")
    finally:
        if proc.stdin:
            proc.stdin.close()
