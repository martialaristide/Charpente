"""`charpente import cmake`: the translation of CMake's File API answers (canned) and a real CMake project (when cmake is installed)."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from charpente.cli import main
from charpente.dsl.loader import load_workspace
from charpente.errors import ChError
from charpente.importers import cmake as imp
from charpente.lint import lint_source

HAVE_CMAKE = shutil.which("cmake") is not None
HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++"))
SOURCE = Path("/proj")


def target(name, kind="EXECUTABLE", **extra):
    base = {"name": name, "id": f"{name}::@1", "type": kind, "sources": [], "compileGroups": [], "dependencies": [], "link": {"commandFragments": []}}
    base.update(extra)
    return base


def group(language="CXX", includes=(), defines=(), fragments=(), standard=""):
    result = {"language": language, "includes": [{"path": str(p), **({"isSystem": True} if s else {})} for p, s in includes],
              "defines": [{"define": d} for d in defines], "compileCommandFragments": [{"fragment": f} for f in fragments]}
    if standard:
        result["languageStandard"] = {"standard": standard}
    return result


MODEL = {"configurations": [{"name": "Debug", "projects": [{"name": "Demo"}]}]}


def convert(*targets, cache=None):
    return imp.convert(MODEL, list(targets), cache or {}, SOURCE, Path("/build"))


# ---------------------------------------------------------------------- translation (canned answers)
def test_kinds_sources_flags_and_standard():
    lib = target("core", "STATIC_LIBRARY", sources=[{"path": "src/a.cpp"}, {"path": "src/b.cc"}, {"path": "include/a.hpp"}],
                 compileGroups=[group(includes=[(SOURCE / "include", False), ("/usr/include", True)], defines=["A=1", "B"], fragments=["-g", "-O2", "-std=gnu++20", "-Wall", "-fno-rtti", "-DNDEBUG"], standard="20")])
    app = target("app", sources=[{"path": "src/main.cpp"}], dependencies=[{"id": "core::@1"}],
                 link={"commandFragments": [{"fragment": "-lm -lz core.lib", "role": "libraries"}]}, compileGroups=[group(standard="17")])
    imported = convert(app, lib, cache={"CMAKE_PROJECT_VERSION": "1.2.3"})
    assert (imported.name, imported.version) == ("Demo", "1.2.3")
    assert [t.name for t in imported.targets] == ["core", "app"]                                      # dependencies first
    core, application = imported.targets
    assert core.kind == "Kind.STATIC_LIBRARY" and core.standard == "c++20" and core.sources == ["src/a.cpp", "src/b.cc"]     # headers are not sources
    assert core.include_dirs == ["include"] and core.defines == ["A=1", "B"] and core.compile_flags == ["-Wall", "-fno-rtti"]
    assert application.kind == "Kind.EXECUTABLE" and application.uses == ["core"] and application.links == ["z"]      # -lm implicit; core.lib is a project target


def test_c_and_cpp_languages():
    only_c = convert(target("c", sources=[{"path": "a.c"}], compileGroups=[group("C", fragments=["-std=gnu11"])]))
    assert only_c.targets[0].language == "c" and only_c.targets[0].standard == "c11"
    mixed = convert(target("m", sources=[{"path": "a.c"}, {"path": "b.cpp"}], compileGroups=[group("C"), group("CXX", standard="14")]))
    assert mixed.targets[0].language == "cpp" and mixed.targets[0].standard == "c++14"


def test_the_standard_is_assumed_and_said_so_when_cmake_did_not_set_one():
    imported = convert(target("a", sources=[{"path": "a.cpp"}], compileGroups=[group()]))
    assert imported.targets[0].standard == "c++17" and any("assumed c++17" in r for r in imported.report)


def test_what_cannot_be_translated_is_reported_not_dropped():
    imported = convert(
        target("gen", "UTILITY"),
        target("obj", "OBJECT_LIBRARY", sources=[{"path": "o.cpp"}], compileGroups=[group(standard="17")]),
        target("app", sources=[{"path": "main.cpp"}, {"path": "gen.cpp", "isGenerated": True}, {"path": "/elsewhere/x.cpp"}],
               compileGroups=[group(includes=[("/opt/other/include", False)], fragments=["/W4", "-fweird-flag"], standard="17")],
               link={"commandFragments": [{"fragment": "/opt/lib/libfoo.a -Wl,--as-needed -framework Cocoa", "role": "libraries"}, {"fragment": "-static", "role": "flags"}]}))
    text = "\n".join(imported.report)
    assert "gen: a custom/utility target" in text and "obj: an OBJECT library became a static library" in text
    assert "gen.cpp is generated at build time" in text and "source /elsewhere/x.cpp is outside the project" in text
    assert "/opt/other/include is outside the project" in text and "compile flags not translated: /W4 -fweird-flag" in text
    assert "links /opt/lib/libfoo.a, a library outside the project" in text and "link options" in text or "-Wl,--as-needed not translated" in text
    assert "link flags not translated: -static" in text
    assert [t.name for t in imported.targets] == ["app", "obj"]                                       # the utility target is not a target
    assert imported.targets[0].sources == ["main.cpp"]


def test_interface_and_module_libraries():
    imported = convert(target("headers", "INTERFACE_LIBRARY", compileGroups=[]), target("plug", "MODULE_LIBRARY", sources=[{"path": "p.cpp"}], compileGroups=[group(standard="17")]))
    kinds = {t.name: t.kind for t in imported.targets}
    assert kinds == {"headers": "Kind.HEADER_ONLY", "plug": "Kind.PLUGIN"}


def test_dependencies_on_unknown_targets_are_dropped_quietly():
    imported = convert(target("a", sources=[{"path": "a.cpp"}], compileGroups=[group(standard="17")], dependencies=[{"id": "ghost::@1"}]))
    assert imported.targets[0].uses == []


def test_rendering_is_valid_and_lint_clean():
    imported = convert(target("core", "STATIC_LIBRARY", sources=[{"path": "a.cpp"}], compileGroups=[group(includes=[(SOURCE / "inc", False)], defines=['NAME="x y"'], standard="17")]),
                       target("app", sources=[{"path": "m.cpp"}], dependencies=[{"id": "core::@1"}], compileGroups=[group(standard="17")]))
    text = imp.render(imported)
    compile(text, "x.charpente", "exec")
    assert not [i for i in lint_source(text) if i.severity == "error"]
    assert 't.uses("core")' in text and 't.public_include_dirs(["inc"])' in text and r'"NAME=\"x y\""' in text
    assert text.index('Target("core")') < text.index('Target("app")') and "# ---- import report" in text


def test_the_reply_folder_is_validated(tmp_path):
    with pytest.raises(ChError, match="no File API reply"):
        imp.read_reply(tmp_path)
    (tmp_path / "index-1.json").write_text('{"objects": []}', encoding="utf-8")
    with pytest.raises(ChError, match="codemodel"):
        imp.read_reply(tmp_path)
    (tmp_path / "index-1.json").write_text('{"objects": [{"kind": "codemodel", "jsonFile": "missing.json"}]}', encoding="utf-8")
    with pytest.raises(ChError, match="cannot read"):
        imp.read_reply(tmp_path)


def test_configure_errors_are_coded(tmp_path):
    with pytest.raises(ChError, match="no CMakeLists.txt"):
        imp.configure(tmp_path, tmp_path / "b")
    (tmp_path / "CMakeLists.txt").write_text("project(x)\n", encoding="utf-8")
    with pytest.raises(ChError, match="CMake was not found"):
        imp.configure(tmp_path, tmp_path / "b", cmake="no-such-cmake-xyz", which=lambda name: None)


# ---------------------------------------------------------------------- a real CMake
CMAKELISTS = """cmake_minimum_required(VERSION 3.16)
project(Demo VERSION 2.3.1 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
add_library(mylib STATIC src/mylib.cpp)
target_include_directories(mylib PUBLIC include)
target_compile_definitions(mylib PUBLIC MYLIB_VERSION=3)
add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE mylib)
target_compile_options(app PRIVATE -Wall -Wextra)
add_custom_target(docs COMMAND echo docs)
"""


@pytest.fixture
def cmake_project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "include" / "mylib").mkdir(parents=True)
    (tmp_path / "CMakeLists.txt").write_text(CMAKELISTS, encoding="utf-8")
    (tmp_path / "include" / "mylib" / "mylib.hpp").write_bytes(b"#pragma once\nint answer();\n")
    (tmp_path / "src" / "mylib.cpp").write_bytes(b'#include "mylib/mylib.hpp"\nint answer() { return MYLIB_VERSION * 14; }\n')
    (tmp_path / "src" / "main.cpp").write_bytes(b'#include <cstdio>\n#include "mylib/mylib.hpp"\nint main() { std::printf("answer=%d\\n", answer()); return 0; }\n')
    return tmp_path


@pytest.mark.skipif(not HAVE_CMAKE, reason="needs cmake")
def test_a_real_cmake_project_is_imported_and_the_result_builds_and_runs(cmake_project, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    assert main(["import", "cmake", str(cmake_project)]) == 0
    out = capsys.readouterr().out
    written = cmake_project / "Demo.charpente"
    assert written.is_file() and "2 target(s)" in out and "docs: a custom/utility target" in out
    assert not list(cmake_project.glob("build*")) and not (cmake_project / "CMakeCache.txt").exists()          # the source folder was not touched by CMake
    workspace = load_workspace(str(written))
    assert workspace.version == "2.3.1" and set(workspace.targets) == {"mylib", "app"}
    assert workspace.targets["app"].uses == ["mylib"] and workspace.targets["mylib"].public_include_dirs == ["include"]
    if HAVE_COMPILER:
        monkeypatch.chdir(cmake_project)
        assert main(["build"]) == 0
        exe = next((cmake_project / "build" / "Debug" / "app").glob("app*"))
        assert subprocess.run([str(exe)], capture_output=True, text=True).stdout.strip() == "answer=42"       # 3 * 14: the define crossed over


@pytest.mark.skipif(not HAVE_CMAKE, reason="needs cmake")
def test_import_refuses_to_overwrite_and_can_print(cmake_project, capsys):
    assert main(["import", "cmake", str(cmake_project)]) == 0
    capsys.readouterr()
    assert main(["import", "cmake", str(cmake_project)]) != 0
    assert "already exists" in capsys.readouterr().err
    assert main(["import", "cmake", str(cmake_project), "--force"]) == 0
    assert main(["import", "cmake", str(cmake_project), "--print"]) == 0
    assert capsys.readouterr().out.count("with Target(") == 2


@pytest.mark.skipif(not HAVE_CMAKE, reason="needs cmake")
def test_a_cmake_configuration_error_is_shown(tmp_path, capsys):
    (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.16)\nproject(Bad)\nadd_executable(x missing.cpp)\n", encoding="utf-8")
    assert main(["import", "cmake", str(tmp_path)]) != 0
    err = capsys.readouterr().err
    assert "CH8026" in err and "missing.cpp" in err                                                     # CMake's own words


@pytest.mark.skipif(not HAVE_CMAKE, reason="needs cmake")
def test_cmake_arguments_reach_the_configuration(cmake_project, capsys):
    (cmake_project / "CMakeLists.txt").write_text(CMAKELISTS.replace("target_compile_definitions(mylib PUBLIC MYLIB_VERSION=3)",
                                                                     "if(WITH_X)\n  target_compile_definitions(mylib PUBLIC WITH_X=1)\nendif()\ntarget_compile_definitions(mylib PUBLIC MYLIB_VERSION=3)"), encoding="utf-8")
    assert main(["import", "cmake", str(cmake_project), "--print", "--cmake-arg=-DWITH_X=ON"]) == 0
    assert "WITH_X=1" in capsys.readouterr().out
    assert main(["import", "cmake", str(cmake_project), "--print"]) == 0
    assert "WITH_X=1" not in capsys.readouterr().out


def test_the_command_is_registered():
    from charpente.commands import COMMANDS

    assert "import" in COMMANDS and sys.version_info >= (3, 9)
