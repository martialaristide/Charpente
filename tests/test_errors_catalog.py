"""The catalogue is a public contract: complete, aligned across languages, and
every code reachable from `charpente explain`."""
import re

import pytest

from charpente import i18n
from charpente.cli import main
from charpente.errors import ChError, ChFileNotFoundError, ChRuntimeError, ChValueError, describe
from charpente.i18n import en, fr

CODE_RE = re.compile(r"^CH[1-9]\d{3}$")


def test_both_languages_define_exactly_the_same_codes():
    assert set(en.CATALOG) == set(fr.CATALOG)


@pytest.mark.parametrize("code", sorted(en.CATALOG))
def test_every_entry_is_complete_in_both_languages(code):
    assert CODE_RE.match(code)
    for lang_catalog in (en.CATALOG, fr.CATALOG):
        entry = lang_catalog[code]
        for key in i18n.ENTRY_KEYS:
            assert entry.get(key, "").strip(), f"{code} is missing {key!r}"


@pytest.mark.parametrize("code", sorted(en.CATALOG))
def test_placeholders_match_between_languages(code):
    field = re.compile(r"\{(\w+)(?:![rsa])?\}")
    for key in ("message", "cause", "fix"):
        assert set(field.findall(en.CATALOG[code][key])) == set(field.findall(fr.CATALOG[code][key])), (code, key)


def test_codes_are_in_their_documented_family():
    for code in en.CATALOG:
        assert code[2] in "123456789"


def test_message_renders_parameters():
    err = ChError("CH1008", name="ghost", workspace="W", known="a, b")
    assert "'ghost'" in str(err) and "'W'" in str(err)


def test_language_switches_the_rendering(monkeypatch):
    err = ChError("CH1002", directory="/x")
    monkeypatch.setenv("CHARPENTE_LANG", "fr")
    assert "Aucun fichier .charpente" in str(err)
    monkeypatch.setenv("CHARPENTE_LANG", "en")
    assert "No .charpente file found" in str(err)


def test_language_falls_back_to_system_locale(monkeypatch):
    monkeypatch.delenv("CHARPENTE_LANG")
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    assert i18n.current_lang() == "fr"
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert i18n.current_lang() == "en"


def test_unknown_code_never_raises():
    assert "CH0000" in str(ChError("CH0000"))
    assert describe("CH0000") == ""


def test_missing_placeholder_never_raises():
    assert "{name}" in ChError("CH1008").message


def test_format_includes_fix_and_explain_hint():
    text = ChError("CH1002", directory="/x").format()
    assert text.startswith("[CH1002]")
    assert "charpente explain CH1002" in text
    assert "Fix:" in text


def test_compat_subclasses_are_still_the_builtin_types():
    assert isinstance(ChValueError("CH1011", field="n"), ValueError)
    assert isinstance(ChRuntimeError("CH1014", name="t"), RuntimeError)
    err = ChFileNotFoundError("CH1018", path="x")
    assert isinstance(err, FileNotFoundError) and isinstance(err, ChError)
    assert err.code == "CH1018" and "x" in str(err)


def test_english_message_is_kept_in_args_for_logs():
    assert "No such file" in ChError("CH1001", path="p").args[0]


# ------------------------------------------------------------------ explain
def test_explain_prints_cause_and_fix(capsys):
    assert main(["explain", "CH3001"]) == 0
    out = capsys.readouterr().out
    assert "CH3001" in out and "Cause:" in out and "Fix:" in out


def test_explain_accepts_lowercase_and_bare_number(capsys):
    assert main(["explain", "ch3001"]) == 0
    assert main(["explain", "3001"]) == 0


def test_explain_in_french(capsys):
    assert main(["explain", "CH3001", "--lang", "fr"]) == 0
    out = capsys.readouterr().out
    assert "Correction" in out and "Cause" in out


def test_explain_unknown_code_exits_1(capsys):
    assert main(["explain", "CH0000"]) == 1


def test_explain_list_shows_every_code(capsys):
    assert main(["explain", "--list"]) == 0
    out = capsys.readouterr().out
    for code in en.CATALOG:
        assert code in out


def test_explain_without_code_is_a_usage_error(capsys):
    assert main(["explain"]) == 1
    assert "CH4005" in capsys.readouterr().err


def test_cli_prints_code_message_and_hint(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["build"]) == 1
    err = capsys.readouterr().err
    assert "[CH1002]" in err and "charpente explain CH1002" in err


def test_generated_error_docs_are_up_to_date():
    import importlib.util
    from pathlib import Path

    tool = Path(__file__).resolve().parent.parent / "tools" / "gen_error_docs.py"
    spec = importlib.util.spec_from_file_location("gen_error_docs", tool)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--check"]) == 0
