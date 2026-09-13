import pytest

from charpente.dsl.model import Target, Workspace
from charpente.safe_name import validate


def test_legitimate_name_is_accepted():
    assert validate("MyApp") == "MyApp"
    assert validate("My Étage App (v2)") == "My Étage App (v2)"


def test_directory_traversal_is_rejected():
    with pytest.raises(ValueError):
        validate("../../../../etc/cron.d/evil")


def test_path_separators_are_rejected():
    with pytest.raises(ValueError):
        validate("sub/dir")
    with pytest.raises(ValueError):
        validate("sub\\dir")


def test_empty_name_is_rejected():
    with pytest.raises(ValueError):
        validate("")
    with pytest.raises(ValueError):
        validate("   ")


def test_control_character_is_rejected():
    with pytest.raises(ValueError):
        validate("App\nrm -rf /")


def test_target_construction_validates_the_name():
    with pytest.raises(ValueError):
        Target(name="../evil")


def test_workspace_construction_validates_the_name():
    with pytest.raises(ValueError):
        Workspace(name="../evil")
