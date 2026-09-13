from pathlib import Path

import pytest

from charpente.dsl.model import Kind, Language, Target, Workspace


def test_workspace_defaults():
    ws = Workspace(name="Demo")
    assert ws.configurations == ["Debug", "Release"]
    assert ws.targets == {}


def test_add_target_rejects_duplicate_name():
    ws = Workspace(name="Demo")
    ws.add_target(Target(name="app"))
    with pytest.raises(ValueError):
        ws.add_target(Target(name="app"))


def test_target_defaults():
    t = Target(name="app")
    assert t.kind == Kind.EXECUTABLE
    assert t.language == Language.CPP
    assert t.standard == "c++17"
    assert t.source_patterns == []


def test_resolved_sources_needs_location():
    t = Target(name="app", source_patterns=["*.cpp"])
    with pytest.raises(ValueError):
        t.resolved_sources()


def test_resolved_sources_globs_and_excludes(tmp_path):
    (tmp_path / "main.cpp").write_text("int main(){}")
    (tmp_path / "helper.cpp").write_text("void h(){}")
    (tmp_path / "helper_test.cpp").write_text("void t(){}")
    t = Target(
        name="app",
        source_patterns=["*.cpp"],
        exclude_patterns=["*_test.cpp"],
        location=tmp_path,
    )
    names = sorted(p.name for p in t.resolved_sources())
    assert names == ["helper.cpp", "main.cpp"]


# =============================================================================
#  build_order() -- dependency resolution
# =============================================================================
def test_build_order_respects_dependencies():
    ws = Workspace(name="Demo")
    ws.add_target(Target(name="app", depends_on=["engine"]))
    ws.add_target(Target(name="engine"))
    order = ws.build_order()
    assert order.index("engine") < order.index("app")


def test_build_order_unknown_dependency_is_named_in_error():
    ws = Workspace(name="Demo")
    ws.add_target(Target(name="app", depends_on=["ghost"]))
    with pytest.raises(ValueError, match="ghost"):
        ws.build_order()


def test_build_order_detects_direct_cycle():
    ws = Workspace(name="Demo")
    ws.add_target(Target(name="a", depends_on=["b"]))
    ws.add_target(Target(name="b", depends_on=["a"]))
    with pytest.raises(ValueError, match="[Cc]ycle"):
        ws.build_order()


def test_build_order_detects_self_cycle():
    ws = Workspace(name="Demo")
    ws.add_target(Target(name="a", depends_on=["a"]))
    with pytest.raises(ValueError, match="[Cc]ycle"):
        ws.build_order()


def test_build_order_is_stable_for_diamond_dependency():
    ws = Workspace(name="Demo")
    ws.add_target(Target(name="app", depends_on=["gfx", "audio"]))
    ws.add_target(Target(name="gfx", depends_on=["core"]))
    ws.add_target(Target(name="audio", depends_on=["core"]))
    ws.add_target(Target(name="core"))
    order = ws.build_order()
    assert order.index("core") < order.index("gfx")
    assert order.index("core") < order.index("audio")
    assert order.index("gfx") < order.index("app")
    assert order.index("audio") < order.index("app")
