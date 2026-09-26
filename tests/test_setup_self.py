"""`charpente setup` (guided first run), remembered settings, and `charpente self uninstall`."""
import os
import subprocess
from pathlib import Path

import pytest

from charpente import i18n, onboarding, selfmanage, settings
from charpente.cli import main
from charpente.commands import setup as setup_cmd


@pytest.fixture
def home(tmp_path, monkeypatch):
    folder = tmp_path / "home" / ".charpente"
    folder.mkdir(parents=True)
    monkeypatch.setenv("CHARPENTE_HOME", str(folder))
    monkeypatch.delenv("CHARPENTE_CACHE_DIR", raising=False)
    return folder


def fill(home: Path) -> None:
    (home / "cache" / "objects").mkdir(parents=True)
    (home / "cache" / "objects" / "a.bin").write_bytes(b"x" * 1000)
    (home / "toolchains" / "zig-0.13").mkdir(parents=True)
    (home / "toolchains" / "zig-0.13" / "zig.exe").write_bytes(b"z" * 5000)
    (home / "pkg").mkdir()
    (home / "pkg" / "p.txt").write_bytes(b"p")
    (home / "trusted_files.json").write_text("{}", encoding="utf-8")
    (home / "keys").mkdir()
    (home / "keys" / "release.key").write_bytes(b"SECRET")


# ---------------------------------------------------------------------- settings
def test_settings_are_remembered_validated_and_never_break_a_run(home):
    assert settings.load() == {} and settings.get("lang") is None
    settings.set_value("lang", "fr")
    assert settings.get("lang") == "fr" and not list(home.glob("*.tmp"))
    with pytest.raises(ValueError, match="not valid"):
        settings.set_value("lang", "klingon")
    with pytest.raises(ValueError, match="unknown setting"):
        settings.set_value("token", "abc")
    (home / "settings.json").write_text("{not json", encoding="utf-8")                # hand-broken: treated as empty
    assert settings.load() == {}
    (home / "settings.json").write_text('{"lang": "xx", "other": "y"}', encoding="utf-8")
    assert settings.load() == {}                                                    # unknown keys and values are ignored


def test_the_environment_beats_the_remembered_language(home, monkeypatch):
    settings.set_value("lang", "fr")
    monkeypatch.delenv("CHARPENTE_LANG", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    assert i18n.current_lang() == "fr"
    monkeypatch.setenv("CHARPENTE_LANG", "en")
    assert i18n.current_lang() == "en"


# ---------------------------------------------------------------------- the planner (pure)
def report(**changes):
    base = {"charpente": "0", "host": "windows-x64", "toolchains": [{"name": "gcc"}], "buildable": ["windows-x64"],
            "tools": {"git": "/usr/bin/git", "clangd": "/usr/bin/clangd"}, "debuggers": ["gdb 17"]}
    base.update(changes)
    return base


def test_a_complete_machine_needs_nothing():
    assert onboarding.steps(report(), lang_chosen="en") == []


def test_a_bare_machine_gets_a_compiler_offer_and_advice():
    found = {s.id: s for s in onboarding.steps(report(toolchains=[], tools={}, debuggers=[]), lang_chosen=None)}
    assert set(found) == {"compiler", "git", "clangd", "debugger", "language"}
    assert found["compiler"].command == ["toolchain", "install", "zig"] and found["compiler"].download
    assert found["git"].command is None and found["git"].advice                       # advice only: Charpente never runs a foreign installer
    assert found["language"].options == ["en", "fr"]
    assert any("downloads files" in line for line in onboarding.describe(found["compiler"]))


# ---------------------------------------------------------------------- the command
def test_setup_runs_nothing_without_a_yes_when_not_interactive(home, monkeypatch, capsys):
    monkeypatch.setattr(setup_cmd.doctor, "gather", lambda: report(toolchains=[], buildable=[]))
    ran = []
    monkeypatch.setattr("charpente.cli.main", lambda argv=None: ran.append(argv) or 0)
    monkeypatch.setattr(setup_cmd, "_interactive", lambda: False)
    assert setup_cmd.execute([]) == 0
    out = capsys.readouterr().out
    assert ran == [] and "skipped" in out and "charpente setup --lang" in out


def test_setup_with_yes_installs_the_open_tool_and_asks_nothing(home, monkeypatch, capsys):
    monkeypatch.setattr(setup_cmd.doctor, "gather", lambda: report(toolchains=[], buildable=[]))
    ran = []
    monkeypatch.setattr("charpente.cli.main", lambda argv=None: ran.append(argv) or 0)
    monkeypatch.setattr(setup_cmd, "_interactive", lambda: False)
    assert setup_cmd.execute(["--yes", "--lang", "fr"]) == 0
    assert ran == [["toolchain", "install", "zig"]] and settings.get("lang") == "fr"


def test_setup_interactive_answers_and_failures(home, monkeypatch, capsys):
    monkeypatch.setattr(setup_cmd.doctor, "gather", lambda: report(toolchains=[], buildable=[]))
    monkeypatch.setattr("charpente.cli.main", lambda argv=None: 3)                    # the install fails
    answers = iter(["y", "fr"])
    assert setup_cmd.execute([], ask=lambda prompt: next(answers)) == 0
    captured = capsys.readouterr()
    assert "did not work (exit code 3)" in captured.err and settings.get("lang") == "fr"
    answers = iter(["n", ""])
    monkeypatch.setattr("charpente.cli.main", lambda argv=None: pytest.fail("declined: nothing may run"))
    settings.path().unlink()
    assert setup_cmd.execute([], ask=lambda prompt: next(answers)) == 0
    assert settings.get("lang") is None                                             # Enter skips the question


def test_setup_on_a_complete_machine(home, monkeypatch, capsys):
    monkeypatch.setattr(setup_cmd.doctor, "gather", lambda: report())
    settings.set_value("lang", "en")
    assert main(["setup"]) == 0
    assert "Everything Charpente looks for is here" in capsys.readouterr().out


# ---------------------------------------------------------------------- self uninstall
def test_uninstall_is_a_dry_run_by_default(home, capsys):
    fill(home)
    assert main(["self", "uninstall"]) == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "toolchains" in out
    assert not [line for line in out.splitlines() if line.startswith("  keys")]                # the protected group is not even offered
    assert (home / "cache").exists() and (home / "keys" / "release.key").exists()


def test_uninstall_removes_the_groups_but_never_the_keys_unless_named(home, capsys):
    fill(home)
    (home / "mine.txt").write_text("not Charpente's", encoding="utf-8")
    assert main(["self", "uninstall", "--yes"]) == 0
    assert not (home / "cache").exists() and not (home / "toolchains").exists() and not (home / "trusted_files.json").exists()
    assert (home / "keys" / "release.key").read_bytes() == b"SECRET"                  # irreplaceable: kept
    assert (home / "mine.txt").exists() and home.exists()                             # an unknown file is never removed, so the folder stays
    assert "pip uninstall charpente" in capsys.readouterr().out
    assert main(["self", "uninstall", "--only", "keys", "--yes"]) == 2                # asking for keys without --keys is refused
    assert (home / "keys").exists()
    assert main(["self", "uninstall", "--keys", "--yes"]) == 0
    assert not (home / "keys").exists()


def test_uninstall_only_removes_what_was_named(home, capsys):
    fill(home)
    assert main(["self", "uninstall", "--only", "cache", "--yes"]) == 0
    assert not (home / "cache").exists() and (home / "toolchains").exists() and (home / "pkg").exists()


def test_uninstall_removes_the_empty_config_folder_and_reports_nothing_to_do(home, capsys):
    (home / "pkg").mkdir()
    assert main(["self", "uninstall", "--yes"]) == 0
    assert not home.exists()
    capsys.readouterr()
    assert main(["self", "uninstall"]) == 0
    assert "Nothing to remove" in capsys.readouterr().out


def test_a_link_is_unlinked_and_its_target_left_alone(home, tmp_path):
    target = tmp_path / "precious"
    target.mkdir()
    (target / "file.txt").write_text("keep me", encoding="utf-8")
    try:
        os.symlink(target, home / "toolchains", target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            pytest.skip("symlinks are not available here")
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(home / "toolchains"), str(target)], capture_output=True)   # a junction needs no privilege
        if made.returncode != 0:
            pytest.skip("neither symlinks nor junctions are available here")
    items, _ = selfmanage.plan(home)
    link = next(i for i in items if i.group == "toolchains")
    assert link.is_link
    assert selfmanage.remove(link) is None
    assert not (home / "toolchains").exists() and (target / "file.txt").read_text(encoding="utf-8") == "keep me"


def test_a_cache_folder_elsewhere_is_removed_only_when_it_looks_like_one(home, tmp_path):
    elsewhere = tmp_path / "fast-disk" / "charpente-cache"
    elsewhere.mkdir(parents=True)
    (elsewhere / "o.bin").write_bytes(b"1")
    items, notes = selfmanage.plan(home, str(elsewhere))
    assert [i.path for i in items] == [elsewhere] and notes == []
    documents = tmp_path / "documents"
    documents.mkdir()
    items, notes = selfmanage.plan(home, str(documents))
    assert items == [] and "does not look like a cache folder" in notes[0]
    assert not selfmanage.cache_folder_is_safe(Path(Path.home().anchor), home) and not selfmanage.cache_folder_is_safe(Path.home(), home)


def test_selection_rules_and_sizes():
    a, b = selfmanage.Item("cache", Path("c"), 1), selfmanage.Item("keys", Path("k"), 1)
    chosen, refusals = selfmanage.select([a, b], None, False)
    assert chosen == [a] and refusals == []
    chosen, refusals = selfmanage.select([a, b], ["nope"], False)
    assert chosen == [] and "unknown group" in refusals[0]
    chosen, _ = selfmanage.select([a, b], ["cache"], True)
    assert chosen == [a, b]
    assert selfmanage.humanize(10) == "10 B" and selfmanage.humanize(1536) == "1.5 KB" and selfmanage.humanize(5 * 1024 ** 3) == "5.0 GB"
