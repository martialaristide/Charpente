import pytest

from charpente.dsl import trust


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("CHARPENTE_TRUST_ALL", raising=False)
    yield


@pytest.fixture
def a_file(tmp_path):
    f = tmp_path / "atelier.charpente"
    f.write_text("from charpente import *\n", encoding="utf-8")
    return f


def test_trust_all_bypasses(a_file, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    trust.ensure_trusted(a_file)
    assert not trust.is_trusted(a_file)


def test_non_interactive_without_prompt_refuses(a_file, monkeypatch):
    monkeypatch.setattr(trust, "_interactive", lambda: False)
    with pytest.raises(trust.TrustRequiredError):
        trust.ensure_trusted(a_file)


def test_previously_trusted_needs_no_prompt(a_file, monkeypatch):
    trust.trust(a_file)
    monkeypatch.setattr(trust, "_interactive", lambda: False)
    trust.ensure_trusted(a_file)  # must not raise


def test_injected_prompt_accept_memoizes(a_file):
    calls = []

    def fake_prompt(question):
        calls.append(question)
        return "y"

    trust.ensure_trusted(a_file, prompt=fake_prompt)
    assert trust.is_trusted(a_file)
    assert len(calls) == 1

    # Second call: must not prompt again.
    def must_not_be_called(question):
        raise AssertionError("re-asked a file that was already trusted")

    trust.ensure_trusted(a_file, prompt=must_not_be_called)


def test_injected_prompt_decline_raises_and_does_not_memoize(a_file):
    with pytest.raises(trust.TrustDeniedError):
        trust.ensure_trusted(a_file, prompt=lambda q: "n")
    assert not trust.is_trusted(a_file)


def test_editing_a_trusted_file_asks_again(a_file):
    trust.trust(a_file)
    assert trust.is_trusted(a_file)
    a_file.write_text("from charpente import *\nimport os\n", encoding="utf-8")
    assert not trust.is_trusted(a_file)
