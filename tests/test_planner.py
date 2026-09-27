from pathlib import Path

import pytest
from helpers import GCC

from charpente.core.planner import plan_workspace
from charpente.dsl.model import OS, Kind, Language, Target, Workspace
from charpente.errors import ChValueError
from charpente.toolchains import Toolchain

MSVC = Toolchain(name="msvc", c_compiler="cl", cxx_compiler="cl", archiver="lib", linker="cl")


def _ws(tmp_path, files, targets):
    for rel in files:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    ws = Workspace(name="W", location=tmp_path)
    for t in targets:
        ws.add_target(t)
    return ws


def test_one_compile_per_source_plus_one_link(tmp_path):
    ws = _ws(tmp_path, ["a.cpp", "b.cpp"], [Target(name="app", source_patterns=["*.cpp"], location=tmp_path)])
    plan = plan_workspace(ws, GCC, OS.LINUX)
    assert list(plan.target_actions) == ["app"]
    kinds = [plan.graph.actions[i].kind for i in plan.target_actions["app"]]
    assert kinds == ["compile", "compile", "link"]
    link = plan.graph.actions["link:app"]
    assert set(link.inputs) == {a.outputs[0] for a in plan.graph.actions.values() if a.kind == "compile"}
    assert plan.outputs["app"] == link.outputs[0]


def test_same_file_name_in_different_folders_never_collides(tmp_path):
    ws = _ws(tmp_path, ["one/util.cpp", "two/util.cpp", "util.c"],
             [Target(name="app", source_patterns=["**/*.cpp", "*.c"], location=tmp_path)])
    plan = plan_workspace(ws, GCC, OS.LINUX)
    objects = [a.outputs[0] for a in plan.graph.actions.values() if a.kind == "compile"]
    assert len(objects) == len(set(objects)) == 3
    assert {o.name for o in objects} == {"util.cpp.o", "util.c.o"}


def test_object_extension_follows_the_toolchain_family(tmp_path):
    ws = _ws(tmp_path, ["a.cpp"], [Target(name="app", source_patterns=["*.cpp"], location=tmp_path)])
    msvc = plan_workspace(ws, MSVC, OS.WINDOWS)
    compile_action = next(a for a in msvc.graph.actions.values() if a.kind == "compile")
    assert compile_action.outputs[0].name == "a.cpp.obj"
    assert compile_action.dep_format == "msvc" and compile_action.depfile is None
    assert ("VSLANG", "1033") in compile_action.env
    gnu = plan_workspace(ws, GCC, OS.LINUX)
    g = next(a for a in gnu.graph.actions.values() if a.kind == "compile")
    assert g.dep_format == "gnu" and g.depfile is not None and "-MMD" in g.argv


def test_actions_run_from_the_workspace_directory(tmp_path):
    ws = _ws(tmp_path, ["a.cpp"], [Target(name="app", source_patterns=["*.cpp"], location=tmp_path,
                                          include_dirs=["include"])])
    plan = plan_workspace(ws, GCC, OS.LINUX)
    assert all(a.cwd == tmp_path for a in plan.graph.actions.values())
    assert "-Iinclude" in plan.graph.actions[plan.target_actions["app"][0]].argv


def test_static_library_uses_the_archiver(tmp_path):
    ws = _ws(tmp_path, ["a.cpp"], [Target(name="lib", kind=Kind.STATIC_LIBRARY, source_patterns=["*.cpp"],
                                          location=tmp_path)])
    plan = plan_workspace(ws, GCC, OS.LINUX)
    final = plan.graph.actions["archive:lib"]
    assert final.argv[:2] == ("ar", "rcs") and final.outputs[0].name == "liblib.a"


def test_dependent_link_waits_for_the_dependency_and_lists_its_library_as_input(tmp_path):
    ws = _ws(tmp_path, ["core.cpp", "app.cpp"], [
        Target(name="core", kind=Kind.STATIC_LIBRARY, source_patterns=["core.cpp"], location=tmp_path),
        Target(name="app", depends_on=["core"], link_libraries=["core"], source_patterns=["app.cpp"],
               location=tmp_path)])
    plan = plan_workspace(ws, GCC, OS.LINUX)
    link = plan.graph.actions["link:app"]
    assert "archive:core" in plan.graph.deps["link:app"]
    assert plan.outputs["core"] in link.inputs            # relink when the library changes
    assert any(a.startswith("-L") and "core" in a for a in link.argv) and "-lcore" in link.argv
    # compiling app.cpp does not have to wait for the library
    assert plan.graph.deps["compile:app:app.cpp"] == set()


def test_depends_on_without_links_is_ordering_only(tmp_path):
    ws = _ws(tmp_path, ["core.cpp", "app.cpp"], [
        Target(name="core", kind=Kind.STATIC_LIBRARY, source_patterns=["core.cpp"], location=tmp_path),
        Target(name="app", depends_on=["core"], source_patterns=["app.cpp"], location=tmp_path)])
    plan = plan_workspace(ws, GCC, OS.LINUX)
    assert plan.outputs["core"] not in plan.graph.actions["link:app"].inputs
    assert "archive:core" in plan.graph.deps["link:app"]


def test_target_without_sources_is_an_error_and_blocks_its_dependents(tmp_path):
    ws = _ws(tmp_path, ["app.cpp"], [
        Target(name="empty", kind=Kind.STATIC_LIBRARY, source_patterns=["nothing/*.cpp"], location=tmp_path),
        Target(name="app", depends_on=["empty"], source_patterns=["app.cpp"], location=tmp_path)])
    plan = plan_workspace(ws, GCC, OS.LINUX)
    assert plan.errors["empty"].code == "CH3001"
    assert plan.errors["app"].code == "CH3006" and "empty" in str(plan.errors["app"])
    assert len(plan.graph) == 0


def test_only_restricts_the_plan(tmp_path):
    ws = _ws(tmp_path, ["a.cpp", "b.cpp"], [
        Target(name="a", source_patterns=["a.cpp"], location=tmp_path),
        Target(name="b", source_patterns=["b.cpp"], location=tmp_path)])
    plan = plan_workspace(ws, GCC, OS.LINUX, only=["b"])
    assert list(plan.target_actions) == ["b"]


def test_unknown_dependency_and_cycles_use_the_workspace_errors(tmp_path):
    ws = _ws(tmp_path, ["a.cpp"], [Target(name="a", depends_on=["ghost"], source_patterns=["a.cpp"],
                                          location=tmp_path)])
    with pytest.raises(ChValueError, match="ghost"):
        plan_workspace(ws, GCC, OS.LINUX)


def test_c_sources_use_the_c_compiler_and_language(tmp_path):
    ws = _ws(tmp_path, ["a.c"], [Target(name="app", language=Language.C, standard="c11",
                                        source_patterns=["*.c"], location=tmp_path)])
    plan = plan_workspace(ws, GCC, OS.LINUX)
    assert plan.graph.actions["compile:app:a.c"].argv[0] == "gcc"


def test_sources_outside_the_workspace_get_a_stable_separate_object_dir(tmp_path):
    outside = tmp_path / "shared"
    outside.mkdir()
    (outside / "x.cpp").write_text("x")
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    ws = Workspace(name="W", location=ws_dir)
    ws.add_target(Target(name="app", source_patterns=["../shared/*.cpp"], location=ws_dir))
    plan = plan_workspace(ws, GCC, OS.LINUX)
    obj = plan.graph.actions[plan.target_actions["app"][0]].outputs[0]
    assert "_external" in obj.parts and Path(obj).name == "x.cpp.o"
    again = plan_workspace(ws, GCC, OS.LINUX)
    assert again.graph.actions[again.target_actions["app"][0]].outputs[0] == obj


@pytest.mark.parametrize("name,compiler", [("msvc", "cl"), ("clang-cl", "clang-cl")])
def test_msvc_style_compiles_report_the_headers_they_read(tmp_path, name, compiler):
    """Header tracking never worked with MSVC-style compilers: the planner passed no depfile for them, so `/showIncludes` was never added (found by the Windows CI job,
    where clang-cl is the default toolchain: editing a header rebuilt nothing)."""
    tc = Toolchain(name=name, c_compiler=compiler, cxx_compiler=compiler, archiver="lib", linker=compiler)
    ws = _ws(tmp_path, ["a.cpp"], [Target(name="app", source_patterns=["*.cpp"], location=tmp_path)])
    compile_action = next(a for a in plan_workspace(ws, tc, OS.WINDOWS).graph.actions.values() if a.kind == "compile")
    assert "/showIncludes" in compile_action.argv and compile_action.dep_format == "msvc" and compile_action.depfile is None
    gnu = next(a for a in plan_workspace(ws, GCC, OS.LINUX).graph.actions.values() if a.kind == "compile")
    assert "-MMD" in gnu.argv and "/showIncludes" not in gnu.argv and gnu.depfile is not None                      # GNU-style: unchanged
