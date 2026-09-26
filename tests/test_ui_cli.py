"""Where the banner appears when a command is run (charpente.cli): once, for the interactive commands, on a terminal, never for programs and never in CI."""
import pytest

from charpente import cli
from charpente.ui import banner, term
from charpente.ui.term import NONE, Caps


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    banner.reset()
    for name in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "TF_BUILD", "JENKINS_URL", "TEAMCITY_VERSION", "CHARPENTE_NO_BANNER", "CHARPENTE_THEME"):
        monkeypatch.delenv(name, raising=False)
    yield
    banner.reset()


def on_a_terminal(monkeypatch, width=100, ci=False):
    monkeypatch.setattr(term, "detect", lambda *a, **k: Caps(tty=True, color=NONE, unicode=True, width=width, ci=ci))


def run(*argv):
    try:
        return cli.main(list(argv))
    except SystemExit as exc:                                                              # argparse ends `--help` this way
        return exc.code


def test_peek_output_mode():
    assert cli._peek_output_mode([]) == "auto"
    assert cli._peek_output_mode(["--output", "jsonl"]) == "jsonl" and cli._peek_output_mode(["-v", "--output=plain", "x"]) == "plain"
    assert cli._peek_output_mode(["--output"]) == "auto"                                   # a dangling flag: the command will complain, not the banner


def test_a_build_on_a_terminal_shows_the_banner_once(monkeypatch, capsys, tmp_path):
    on_a_terminal(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert run("build") == 1                                                                # no project here: the command fails, after the banner
    out = capsys.readouterr().out
    assert out.startswith("╔") and "██████╗" in out and "Multi-platform C/C++ Build System" in out
    run("build")
    assert "██████╗" not in capsys.readouterr().out                                        # once per process


@pytest.mark.parametrize("command", ["build", "run", "test", "package", "deploy", "dev", "init", "setup", "studio"])
def test_the_interactive_commands_get_the_banner(command, monkeypatch, capsys):
    on_a_terminal(monkeypatch)
    calls = []
    monkeypatch.setitem(cli.COMMANDS, command, lambda args: calls.append(args) or 0)
    assert run(command, "--whatever") == 0 and calls
    assert "██████╗" in capsys.readouterr().out


@pytest.mark.parametrize("args", [["build", "--output", "plain"], ["build", "--output=jsonl"], ["build", "--help"], ["build", "-h"], ["studio", "--json"],
                                  ["explain", "CH1001"], ["serve", "--stdio"], ["debug-adapter"], ["shell", "--print-env"], ["doctor"], ["why", "x"], ["menu"]])
def test_no_banner_for_help_machines_and_other_commands(args, monkeypatch, capsys):
    on_a_terminal(monkeypatch)
    monkeypatch.setitem(cli.COMMANDS, args[0], lambda a: 0)
    run(*args)
    assert "██████╗" not in capsys.readouterr().out


def test_no_banner_off_a_terminal(monkeypatch, capsys):
    monkeypatch.setattr(term, "detect", lambda *a, **k: Caps(tty=False, color=NONE, width=100))
    monkeypatch.setitem(cli.COMMANDS, "build", lambda a: 0)
    run("build")
    assert capsys.readouterr().out == ""


def test_no_banner_in_ci_or_when_asked_not_to(monkeypatch, capsys):
    monkeypatch.setitem(cli.COMMANDS, "build", lambda a: 0)
    on_a_terminal(monkeypatch, ci=True)
    run("build")
    assert capsys.readouterr().out == ""
    on_a_terminal(monkeypatch)
    monkeypatch.setenv("CHARPENTE_NO_BANNER", "1")
    run("build")
    assert capsys.readouterr().out == ""


def test_a_narrow_terminal_gets_the_compact_banner(monkeypatch, capsys):
    on_a_terminal(monkeypatch, width=50)
    monkeypatch.setitem(cli.COMMANDS, "build", lambda a: 0)
    run("build")
    out = capsys.readouterr().out
    assert "C H A R P E N T E" in out and "██████╗" not in out and all(term.visible_len(x) <= 50 for x in out.splitlines())


def test_the_theme_comes_from_the_environment_when_there_is_colour(monkeypatch, capsys):
    monkeypatch.setattr(term, "detect", lambda *a, **k: Caps(tty=True, color=term.TRUE, unicode=True, width=100))
    monkeypatch.setenv("CHARPENTE_THEME", "neon")
    monkeypatch.setitem(cli.COMMANDS, "build", lambda a: 0)
    run("build")
    assert "38;2;255;45;150" in capsys.readouterr().out


def test_a_banner_that_cannot_be_drawn_never_stops_the_command(monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("no terminal")

    monkeypatch.setattr(term, "detect", broken)
    monkeypatch.setitem(cli.COMMANDS, "build", lambda a: 7)
    assert run("build") == 7


def test_the_command_result_is_untouched_by_the_banner(monkeypatch):
    on_a_terminal(monkeypatch)
    monkeypatch.setitem(cli.COMMANDS, "build", lambda a: 3)
    assert run("build") == 3
