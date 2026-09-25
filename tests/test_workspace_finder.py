import pytest

from charpente.workspace_finder import (
    AmbiguousWorkspaceError,
    WorkspaceNotFoundError,
    find_workspace_file,
)


def test_explicit_file_wins_even_if_others_exist(tmp_path):
    (tmp_path / "a.charpente").touch()
    explicit = tmp_path / "b.charpente"
    explicit.touch()
    assert find_workspace_file(tmp_path, explicit=str(explicit)) == explicit.resolve()


def test_explicit_missing_file_raises(tmp_path):
    with pytest.raises(WorkspaceNotFoundError):
        find_workspace_file(tmp_path, explicit=str(tmp_path / "ghost.charpente"))


def test_finds_the_single_file_in_cwd(tmp_path):
    f = tmp_path / "workspace.charpente"
    f.touch()
    assert find_workspace_file(tmp_path) == f


def test_searches_upward_through_parents(tmp_path):
    f = tmp_path / "workspace.charpente"
    f.touch()
    sub = tmp_path / "src" / "nested"
    sub.mkdir(parents=True)
    assert find_workspace_file(sub) == f


def test_multiple_files_in_same_dir_is_ambiguous(tmp_path):
    (tmp_path / "a.charpente").touch()
    (tmp_path / "b.charpente").touch()
    with pytest.raises(AmbiguousWorkspaceError):
        find_workspace_file(tmp_path)


def test_none_found_raises_with_clear_message(tmp_path):
    with pytest.raises(WorkspaceNotFoundError):
        find_workspace_file(tmp_path)


def test_the_project_config_directory_is_not_mistaken_for_a_workspace(tmp_path):
    """Regression: `.charpente/` (state, hooks, notify.toml) matches `*.charpente`;
    with a real workspace file next to it the finder used to report two candidates."""
    (tmp_path / ".charpente").mkdir()
    (tmp_path / ".charpente" / "notify.toml").write_text("")
    workspace = tmp_path / "app.charpente"
    workspace.touch()
    assert find_workspace_file(tmp_path) == workspace
    (tmp_path / "app.charpente").unlink()
    with pytest.raises(WorkspaceNotFoundError):
        find_workspace_file(tmp_path)
