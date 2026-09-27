"""`charpente generate`: build.ninja, CMakeLists.txt, a Visual Studio solution, compile_commands.json -- and, where the tools exist, the result really building."""
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from helpers import needs_gnu_default

from charpente.cli import main
from charpente.dsl.loader import load_workspace
from charpente.generators import cmake as cmake_gen
from charpente.generators import ninja as ninja_gen
from charpente.generators import vs as vs_gen

HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++"))
HAVE_NINJA = shutil.which("ninja") is not None
HAVE_CMAKE = shutil.which("cmake") is not None

WORKSPACE = '''from charpente import *

with Workspace("gen", version="1.4.0") as ws:
    with Target("core") as core:
        core.kind(Kind.STATIC_LIBRARY)
        core.standard("c++17")
        core.sources(["src/core/*.cpp"])
        core.public_include_dirs(["src/core"])
        core.public_defines(["CORE_VERSION=7"])
        core.compile_flags(["-Wall"])

    with Target("app") as app:
        app.kind(Kind.EXECUTABLE)
        app.standard("c++17")
        app.sources(["src/main.cpp"])
        app.uses("core")
        app.defines(["GREETING=\\"hi there\\""])

    with Target("core_tests") as tests:
        tests.kind(Kind.TEST)
        tests.standard("c++17")
        tests.sources(["tests/*.cpp"])
        tests.uses("core")
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    (tmp_path / "src" / "core").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "gen.charpente").write_bytes(WORKSPACE.encode())
    (tmp_path / "src" / "core" / "answer.hpp").write_bytes(b"#pragma once\nint answer();\n")
    (tmp_path / "src" / "core" / "answer.cpp").write_bytes(b'#include "answer.hpp"\nint answer() { return CORE_VERSION * 6; }\n')
    (tmp_path / "src" / "main.cpp").write_bytes(b'#include <cstdio>\n#include "answer.hpp"\nint main() { std::printf("%s %d\\n", GREETING, answer()); return 0; }\n')
    (tmp_path / "tests" / "t.cpp").write_bytes(b'#include "answer.hpp"\nint main() { return answer() == 42 ? 0 : 1; }\n')
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(exe):
    return subprocess.run([str(exe)], capture_output=True, text=True)


# ---------------------------------------------------------------------- the command
def test_the_formats_are_listed_with_what_is_verified(capsys):
    assert main(["generate", "--list"]) == 0
    out = capsys.readouterr().out
    assert "verified with Ninja" in out and "unverified" in out and "not implemented" in out


def test_xcode_is_honestly_not_implemented(project, capsys):
    assert main(["generate", "xcode"]) != 0
    assert "CH8027" in capsys.readouterr().err


def test_a_file_charpente_did_not_write_is_never_overwritten(project, capsys):
    (project / "CMakeLists.txt").write_text("# my own build description\n", encoding="utf-8")
    assert main(["generate", "cmake"]) != 0
    assert "CH8027" in capsys.readouterr().err and (project / "CMakeLists.txt").read_text(encoding="utf-8") == "# my own build description\n"
    assert main(["generate", "cmake", "--out", str(project / "elsewhere")]) == 0                      # another folder is fine
    assert main(["generate", "cmake", "--force"]) == 0
    assert main(["generate", "cmake"]) == 0                                                            # its own output can be regenerated


# ---------------------------------------------------------------------- ninja
@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
@needs_gnu_default
def test_the_ninja_text_is_deterministic_and_carries_dependency_information(project):
    assert main(["generate", "ninja"]) == 0
    text = (project / "build.ninja").read_text(encoding="utf-8")
    assert main(["generate", "ninja"]) == 0 and (project / "build.ninja").read_text(encoding="utf-8") == text
    assert "deps = gcc" in text and text.count("\nrule a") == 6 and "default " in text and "build app: phony" in text
    assert ":" not in "".join(line.split(": ")[0][6:] for line in text.splitlines() if line.startswith("build "))       # no unescaped drive letters in build statements


@pytest.mark.skipif(not (HAVE_COMPILER and HAVE_NINJA), reason="needs a C++ compiler and ninja")
@needs_gnu_default
def test_ninja_builds_the_project_and_tracks_headers(project):
    assert main(["generate", "ninja"]) == 0
    built = subprocess.run(["ninja", "-C", str(project)], capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    exe = next((project / "build" / "Debug" / "app").glob("app*"))
    assert run(exe).stdout.strip() == "hi there 42"
    assert "no work to do" in subprocess.run(["ninja", "-C", str(project)], capture_output=True, text=True).stdout
    (project / "src" / "core" / "answer.hpp").write_bytes(b"#pragma once\nint answer();\n// changed\n")        # a header: dependents must rebuild
    again = subprocess.run(["ninja", "-C", str(project)], capture_output=True, text=True).stdout
    assert "Compiling answer.cpp" in again and "Compiling main.cpp" in again and "Compiling t.cpp" in again


def test_ninja_quoting_and_escaping(tmp_path):
    from charpente.core.actions import Action
    from charpente.core.graph import ActionGraph
    from charpente.core.planner import Plan

    root = tmp_path / "my project"
    action = Action(id="c", kind="compile", target="t", argv=("cc", "-DNAME=a b", "-DCOST=$5", "x y.c"), outputs=(root / "out dir" / "a$b.o",), inputs=(root / "x y.c",),
                    env=(("K", "v w"),), description="Compiling $x")
    plan = Plan(graph=ActionGraph([action]), outputs={"t": root / "out dir" / "a$b.o"}, order=["t"])
    posix = ninja_gen.render(plan, root, windows=False)
    assert "command = K='v w' cc '-DNAME=a b' '-DCOST=$$5' 'x y.c'" in posix
    assert "build out$ dir/a$$b.o: a0 x$ y.c" in posix and "description = Compiling $$x" in posix
    windows = ninja_gen.render(plan, root, windows=True)
    assert 'set K=v w&& cc "-DNAME=a b" -DCOST=$$5 "x y.c"' in windows


# ---------------------------------------------------------------------- CMake
def test_the_cmake_text_covers_the_model(project):
    text = cmake_gen.render(load_workspace(str(project / "gen.charpente")))
    assert "project(gen VERSION 1.4.0 LANGUAGES CXX)" in text and "enable_testing()" in text
    assert 'add_library(core STATIC "src/core/answer.cpp")' in text and 'add_executable(app "src/main.cpp")' in text
    assert 'target_include_directories(core PUBLIC "src/core")' in text and 'target_compile_definitions(core PUBLIC "CORE_VERSION=7")' in text
    assert 'target_compile_definitions(app PRIVATE "GREETING=\\"hi there\\"")' in text and "target_link_libraries(app PRIVATE core)" in text
    assert "set_target_properties(core PROPERTIES CXX_STANDARD 17" in text and "add_test(NAME core_tests COMMAND core_tests)" in text
    assert text.index("add_library(core") < text.index("add_executable(app")                          # dependencies first


def test_what_cmake_cannot_express_is_listed(project):
    (project / "gen.charpente").write_text(WORKSPACE.replace('    with Target("core_tests")', '    ws.requires("fmt")\n    with Target("core_tests")')
                                           + '        with tests.on_config("Debug") as c:\n            c.defines(["X"])\n', encoding="utf-8")
    text = cmake_gen.render(load_workspace(str(project / "gen.charpente")))
    assert "# Not translated:" in text and "fmt" in text and "overlays are not translated" in text


@pytest.mark.skipif(not (HAVE_CMAKE and HAVE_COMPILER), reason="needs cmake and a C++ compiler")
def test_cmake_configures_builds_tests_and_runs_the_generated_project(project):
    assert main(["generate", "cmake"]) == 0
    build = project / "cmake-build"
    configure = subprocess.run(["cmake", "-S", str(project), "-B", str(build)] + (["-G", "Ninja"] if HAVE_NINJA else []), capture_output=True, text=True)
    assert configure.returncode == 0, configure.stdout + configure.stderr
    made = subprocess.run(["cmake", "--build", str(build)], capture_output=True, text=True)
    assert made.returncode == 0, made.stdout + made.stderr
    exe = next(build.glob("app*"))
    assert run(exe).stdout.strip() == "hi there 42"                                                     # the quoted define and the public define both arrived
    tested = subprocess.run(["ctest", "--test-dir", str(build), "--output-on-failure"], capture_output=True, text=True) if shutil.which("ctest") else None
    if tested is not None:
        assert tested.returncode == 0, tested.stdout


# ---------------------------------------------------------------------- Visual Studio
def test_visual_studio_files_are_well_formed_and_stable(project):
    workspace = load_workspace(str(project / "gen.charpente"))
    files = vs_gen.render(workspace)
    assert set(files) == {"gen.sln", "core.vcxproj", "app.vcxproj", "core_tests.vcxproj"}
    for name, text in files.items():
        if name.endswith(".vcxproj"):
            root = ET.fromstring(text)
            ns = {"m": "http://schemas.microsoft.com/developer/msbuild/2003"}
            assert root.find("m:PropertyGroup/m:ProjectGuid", ns).text == vs_gen.guid(name[:-8])
            assert [c.get("Include") for c in root.iterfind("m:ItemGroup/m:ClCompile", ns)]
    app = ET.fromstring(files["app.vcxproj"])
    ns = {"m": "http://schemas.microsoft.com/developer/msbuild/2003"}
    assert "charpente build --config $(Configuration) --target app" in app.find("m:PropertyGroup/m:NMakeBuildCommandLine", ns).text
    assert 'GREETING="hi there"' in app.find("m:PropertyGroup/m:NMakePreprocessorDefinitions", ns).text
    assert "src\\core" in ET.fromstring(files["core.vcxproj"]).find("m:PropertyGroup/m:NMakeIncludeSearchPath", ns).text
    core = ET.fromstring(files["core.vcxproj"])
    assert any(i.get("Include") == "src\\core\\answer.hpp" for i in core.iterfind("m:ItemGroup/m:ClInclude", ns))
    solution = files["gen.sln"]
    assert solution.count("\nProject(") == 3 and vs_gen.guid("app") in solution and "\r\n" in solution
    assert vs_gen.guid("app") == vs_gen.guid("app") != vs_gen.guid("core")


def test_visual_studio_generation_writes_files(project, capsys):
    assert main(["generate", "vs"]) == 0
    assert (project / "gen.sln").is_file() and (project / "app.vcxproj").is_file()
    assert "not checked in Visual Studio" in capsys.readouterr().out


# ---------------------------------------------------------------------- compile_commands.json
@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_compile_commands_are_written_with_the_engines_arguments(project):
    assert main(["generate", "compile-commands"]) == 0
    entries = json.loads((project / "compile_commands.json").read_text(encoding="utf-8"))
    assert sorted(Path(e["file"]).name for e in entries) == ["answer.cpp", "main.cpp", "t.cpp"]
    main_entry = next(e for e in entries if e["file"].endswith("main.cpp"))
    assert any(a.startswith(("-DGREETING=", "/DGREETING=")) for a in main_entry["arguments"]) and ("-c" in main_entry["arguments"] or "/c" in main_entry["arguments"])
    assert sys.version_info and os.path.isabs(main_entry["file"])
