"""Guard rails for ADR 0001: one process layer, no shell."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

from charpente.core import process
from charpente.errors import ChError

PACKAGE = Path(__file__).resolve().parent.parent / "charpente"
ALLOWED = {PACKAGE / "core" / "process.py"}


def _python_files():
    return [p for p in PACKAGE.rglob("*.py") if p not in ALLOWED]


def test_no_module_outside_the_process_layer_imports_subprocess():
    offenders = [
        str(p.relative_to(PACKAGE))
        for p in _python_files()
        if re.search(r"^\s*(import subprocess|from subprocess import)", p.read_text(encoding="utf-8"), re.M)
    ]
    assert offenders == []


def test_shell_true_is_never_written_anywhere():
    offenders = [
        str(p.relative_to(PACKAGE))
        for p in PACKAGE.rglob("*.py")
        if re.search(r"shell\s*=\s*True", p.read_text(encoding="utf-8"))
        # the catalogue *mentions* the rule in prose ("no shell=True")
        and "i18n" not in p.parts
    ]
    assert offenders == []


def test_os_system_and_popen_are_not_used():
    offenders = [
        str(p.relative_to(PACKAGE))
        for p in PACKAGE.rglob("*.py")
        if re.search(r"\bos\.(system|popen)\(", p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


@pytest.mark.parametrize("bad", ["g++ -c a.cpp", b"ls", "", [], [""], None])
def test_a_shell_string_or_empty_command_is_refused(bad):
    with pytest.raises(ChError) as exc:
        process.run(bad)
    assert exc.value.code == "CH9001"


def test_missing_program_becomes_a_coded_error():
    with pytest.raises(ChError) as exc:
        process.run(["definitely-not-a-real-program-xyz"])
    assert exc.value.code == "CH2002"
    assert "definitely-not-a-real-program-xyz" in str(exc.value)


def test_run_captures_output_and_exit_code():
    result = process.run([sys.executable, "-c",
                          "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"])
    assert result.returncode == 3
    assert not result.ok
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"
    assert "out" in result.output and "err" in result.output
    assert result.duration >= 0


def test_metacharacters_are_not_interpreted():
    # With a shell, `&& echo pwned` would run a second command.
    result = process.run([sys.executable, "-c", "import sys; print(sys.argv[1])", "a && echo pwned"])
    assert result.stdout.strip() == "a && echo pwned"


def test_non_utf8_output_never_raises():
    code = "import sys; sys.stdout.buffer.write(b'caf\\xe9 ok\\n')"
    result = process.run([sys.executable, "-c", code])
    assert result.returncode == 0
    assert "ok" in result.stdout


def test_injected_runner_is_used_and_never_receives_a_shell():
    seen = {}

    def fake(argv, **kwargs):
        seen.update(kwargs)
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="hi", stderr="")

    result = process.run(["tool", "x"], runner=fake)
    assert result.stdout == "hi"
    assert seen["argv"] == ["tool", "x"]
    assert seen["shell"] is False


def test_pathlike_arguments_are_accepted():
    result = process.run([sys.executable, "-c", "pass", Path("some") / "path"])
    assert result.returncode == 0


def test_capture_false_lets_the_child_write_to_the_terminal(capfd):
    result = process.run([sys.executable, "-c", "print('direct')"], capture=False)
    assert result.returncode == 0
    assert result.stdout == ""
    assert "direct" in capfd.readouterr().out
