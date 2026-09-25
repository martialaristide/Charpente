"""Shared test configuration.

Messages are asserted in English throughout the suite; a developer whose
machine is set to French must not see different results, so the language is
pinned here (individual tests override it with monkeypatch when they test
i18n itself).

The content cache and the per-user config directory are redirected to a
temporary folder for every test: the suite must never read or write the
developer's real ~/.charpente.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch, tmp_path_factory):
    home = tmp_path_factory.mktemp("charpente-home")
    monkeypatch.setenv("CHARPENTE_LANG", "en")
    monkeypatch.setenv("CHARPENTE_HOME", str(home))
    monkeypatch.setenv("CHARPENTE_CACHE_DIR", str(home / "cache"))
    monkeypatch.setenv("CHARPENTE_EVENTS_STRICT", "1")
    yield
