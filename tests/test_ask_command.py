"""`ask` deliberately doesn't use argparse for its question text (see
ask.py's _parse_args docstring): a natural-language question can start
with '-', which argparse.REMAINDER would otherwise treat as an
unrecognized-option parse error instead of passing through."""
import pytest

from charpente.commands.ask import _parse_args, execute


def test_plain_question_is_joined():
    file_arg, question = _parse_args(["why", "does", "my", "build", "fail"])
    assert file_arg is None
    assert question == "why does my build fail"


def test_question_starting_with_a_dash_is_not_swallowed_by_argparse():
    file_arg, question = _parse_args(["--why", "is", "this", "broken"])
    assert question == "--why is this broken"


def test_file_flag_is_extracted_and_not_part_of_the_question():
    file_arg, question = _parse_args(["--file", "w.charpente", "why", "fail"])
    assert file_arg == "w.charpente"
    assert question == "why fail"


def test_file_flag_after_the_question_still_works():
    file_arg, question = _parse_args(["why", "fail", "--file", "w.charpente"])
    assert file_arg == "w.charpente"
    assert question == "why fail"


def test_execute_with_dash_led_question_does_not_crash(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CHARPENTE_AI_URL", raising=False)
    monkeypatch.delenv("CHARPENTE_AI_PROVIDER", raising=False)

    code = execute(["--verbose", "isn't", "printing", "anything"])
    assert code == 1  # no provider configured, but a clean exit, not a crash
    assert "not configured" in capsys.readouterr().out


def test_execute_with_no_question_raises_command_error():
    from charpente.commands._common import CommandError

    with pytest.raises(CommandError):
        execute([])
