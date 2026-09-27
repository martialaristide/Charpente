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
def _isolated_environment(monkeypatch, tmp_path_factory, request):
    home = tmp_path_factory.mktemp("charpente-home")
    monkeypatch.setenv("CHARPENTE_LANG", "en")
    monkeypatch.setenv("CHARPENTE_HOME", str(home))
    monkeypatch.setenv("CHARPENTE_CACHE_DIR", str(home / "cache"))
    monkeypatch.setenv("CHARPENTE_EVENTS_STRICT", "1")
    # Tests that run `git commit` need an author: a CI machine (or a fresh install) has none configured, and the developer's own must not leak in.
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "Charpente Tests")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "tests@charpente.invalid")
    from charpente.modules import runtime

    runtime.reset()          # the module registry is built from the (per-test) config directory
    if request.module.__name__.rpartition(".")[2] != "test_resources":
        # How much memory the machine has free must not change what a build reports (test_resources measures the real machine on purpose).
        from charpente import resources

        healthy = resources.Sample(on_battery=False, free_memory=1 << 40, free_disk=1 << 40, temperature=40.0)
        monkeypatch.setattr(resources, "sample", lambda build_dir: healthy)
    yield
    runtime.reset()
