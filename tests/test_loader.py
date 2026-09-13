import pytest

from charpente.dsl.loader import WorkspaceLoadError, load_workspace
from charpente.dsl.model import Kind, Language


@pytest.fixture(autouse=True)
def trust_everything(monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")


def _write(tmp_path, content):
    f = tmp_path / "workspace.charpente"
    f.write_text(content, encoding="utf-8")
    return f


def test_loads_a_simple_workspace(tmp_path):
    f = _write(tmp_path, """
from charpente import *

with Workspace("HelloWorld") as ws:
    ws.configurations(["Debug", "Release"])

    with Target("hello") as t:
        t.kind(Kind.EXECUTABLE)
        t.language(Language.CPP)
        t.sources(["src/**.cpp"])
""")
    ws = load_workspace(str(f))
    assert ws.name == "HelloWorld"
    assert ws.configurations == ["Debug", "Release"]
    assert set(ws.targets) == {"hello"}
    assert ws.targets["hello"].kind == Kind.EXECUTABLE


def test_target_location_matches_workspace_directory(tmp_path):
    f = _write(tmp_path, """
from charpente import *
with Workspace("W") as ws:
    with Target("t") as t:
        pass
""")
    ws = load_workspace(str(f))
    assert ws.targets["t"].location == tmp_path


def test_missing_file_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_workspace("does/not/exist.charpente")


def test_file_without_workspace_block_raises(tmp_path):
    f = _write(tmp_path, "from charpente import *\nx = 1\n")
    with pytest.raises(WorkspaceLoadError):
        load_workspace(str(f))


def test_syntax_error_is_wrapped(tmp_path):
    f = _write(tmp_path, "with Workspace('W' as ws:\n")
    with pytest.raises(WorkspaceLoadError):
        load_workspace(str(f))


def test_runtime_error_in_file_is_wrapped(tmp_path):
    f = _write(tmp_path, """
from charpente import *
with Workspace("W") as ws:
    raise RuntimeError("boom")
""")
    with pytest.raises(WorkspaceLoadError, match="boom"):
        load_workspace(str(f))


def test_multiple_targets_and_dependencies(tmp_path):
    f = _write(tmp_path, """
from charpente import *
with Workspace("W") as ws:
    with Target("engine") as t:
        t.kind(Kind.STATIC_LIBRARY)
    with Target("app") as t:
        t.kind(Kind.EXECUTABLE)
        t.depends_on(["engine"])
""")
    ws = load_workspace(str(f))
    assert ws.build_order() == ["engine", "app"]


def test_arbitrary_python_is_allowed_in_a_charpente_file(tmp_path):
    """This is the DSL's whole design: a .charpente file is Python, not a
    restricted config format. Confirms the loader doesn't accidentally
    sandbox anything."""
    f = _write(tmp_path, """
from charpente import *
import math

with Workspace("W") as ws:
    n = sum(range(5))
    with Target("app") as t:
        t.defines([f"COMPUTED={n}", f"PI={math.pi:.2f}"])
""")
    ws = load_workspace(str(f))
    assert "COMPUTED=10" in ws.targets["app"].define_macros


def test_two_loads_do_not_leak_state_between_each_other(tmp_path):
    f1 = _write(tmp_path, "from charpente import *\nwith Workspace('A') as ws:\n    pass\n")
    tmp_path2 = tmp_path / "sub"
    tmp_path2.mkdir()
    f2 = tmp_path2 / "workspace.charpente"
    f2.write_text("from charpente import *\nwith Workspace('B') as ws:\n    pass\n", encoding="utf-8")

    ws1 = load_workspace(str(f1))
    ws2 = load_workspace(str(f2))
    assert ws1.name == "A"
    assert ws2.name == "B"
