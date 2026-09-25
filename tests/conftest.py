"""Shared test configuration.

Messages are asserted in English throughout the suite; a developer whose
machine is set to French must not see different results, so the language is
pinned here (individual tests override it with monkeypatch when they test
i18n itself).
"""
import pytest


@pytest.fixture(autouse=True)
def _pin_language(monkeypatch):
    monkeypatch.setenv("CHARPENTE_LANG", "en")
    yield
