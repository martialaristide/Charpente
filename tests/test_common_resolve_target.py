import pytest

from charpente.commands._common import CommandError, resolve_target
from charpente.dsl.model import Target, Workspace


def test_single_target_is_picked_automatically(tmp_path):
    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="app", location=tmp_path))
    assert resolve_target(ws, None).name == "app"


def test_named_target_is_returned(tmp_path):
    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="a", location=tmp_path))
    ws.add_target(Target(name="b", location=tmp_path))
    assert resolve_target(ws, "b").name == "b"


def test_unknown_named_target_lists_known_ones(tmp_path):
    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="a", location=tmp_path))
    with pytest.raises(CommandError, match="a"):
        resolve_target(ws, "ghost")


def test_ambiguous_without_name_lists_known_targets(tmp_path):
    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="a", location=tmp_path))
    ws.add_target(Target(name="b", location=tmp_path))
    with pytest.raises(CommandError, match="--target"):
        resolve_target(ws, None)


def test_empty_workspace_gives_a_clear_message_not_a_confusing_one(tmp_path):
    ws = Workspace(name="W", location=tmp_path)
    with pytest.raises(CommandError, match="no targets"):
        resolve_target(ws, None)
