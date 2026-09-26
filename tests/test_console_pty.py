"""The console interface in a real Windows pseudo-console (ConPTY): arrow keys, shortcuts and text input as a person would use them.

Needs `pywinpty` and `pyte` (both in the dev extras); skipped everywhere else. The scenarios run in a separate process (tests/pty_scenarios.py): a ConPTY created inside the
pytest process was found to make later child processes hang. The POSIX key reader (`PosixKeys`) has no equivalent test yet: it was not run.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.skipif(sys.platform != "win32", reason="ConPTY is a Windows feature"),
              pytest.mark.skipif(importlib.util.find_spec("winpty") is None or importlib.util.find_spec("pyte") is None,
                                 reason="needs pywinpty and pyte (pip install -e '.[dev]')")]
SCRIPT = Path(__file__).with_name("pty_scenarios.py")


@pytest.mark.parametrize("scenario", ["arrows_shortcuts_and_quit", "typing_after_navigation"])
def test_the_menu_works_in_a_real_terminal(scenario, tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), scenario, str(tmp_path / "home"), str(tmp_path)], capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=180, stdin=subprocess.DEVNULL)
    assert result.returncode == 0 and "PASS" in result.stdout, result.stdout[-1500:] + result.stderr[-500:]
