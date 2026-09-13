import subprocess

import pytest

from charpente.cli import main
from charpente.dsl.model import Language, Target


@pytest.fixture(autouse=True)
def trust_and_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def _broken_workspace(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() { this is not valid c++ }")
    f = tmp_path / "w.charpente"
    f.write_text("""
from charpente import *
with Workspace("W") as ws:
    with Target("app") as t:
        t.sources(["*.cpp"])
""")
    return f


def test_ai_diagnose_flag_off_by_default_no_ai_call(tmp_path, monkeypatch, capsys):
    """Without --ai-diagnose, a build failure must never touch the AI
    provider selection at all (no cost, no network, no prompt printed)."""
    f = _broken_workspace(tmp_path)

    called = {"select_provider": False}
    import charpente.commands.build as build_mod
    monkeypatch.setattr(build_mod, "_print_ai_diagnosis",
                        lambda *a, **k: called.__setitem__("select_provider", True))

    code = main(["build", "--file", str(f)])
    assert code == 1
    assert called["select_provider"] is False


def test_ai_diagnose_flag_invokes_diagnosis_on_failure(tmp_path, monkeypatch, capsys):
    f = _broken_workspace(tmp_path)

    seen = {}

    def fake_diagnose(provider, *, target_name, toolchain_name, error_text):
        seen["target_name"] = target_name
        seen["toolchain_name"] = toolchain_name
        seen["error_text"] = error_text
        return "Looks like a syntax error in main.cpp."

    class FakeProvider:
        name = "fake"

    monkeypatch.setattr("charpente.ai.diagnose", fake_diagnose)
    monkeypatch.setattr("charpente.ai.select_provider", lambda: FakeProvider())

    code = main(["build", "--file", str(f), "--ai-diagnose"])
    assert code == 1
    out = capsys.readouterr().out
    assert "Looks like a syntax error" in out
    assert seen["target_name"] == "app"
