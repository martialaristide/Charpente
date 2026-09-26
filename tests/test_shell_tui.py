"""`charpente shell` (project environment) and `charpente tui` (Textual interface)."""
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from charpente import shellenv
from charpente.cli import main
from charpente.toolchains import Toolchain

HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++", "cl"))


def gcc(prefix="/opt/gcc/bin"):
    return Toolchain(name="gcc", c_compiler=f"{prefix}/gcc", cxx_compiler=f"{prefix}/g++", archiver=f"{prefix}/ar", linker=f"{prefix}/g++")


def zig():
    return Toolchain(name="zig", c_compiler="/z/zig", cxx_compiler="/z/zig", archiver="/z/zig", linker="/z/zig",
                     c_args=("cc", "-target", "wasm32-wasi"), cxx_args=("c++", "-target", "wasm32-wasi"), ar_args=("ar",),
                     target="wasm32-wasi", env=(("ZIG_GLOBAL_CACHE_DIR", "/cache dir"),))


# ---------------------------------------------------------------------- shellenv (pure)
def test_tool_dirs_are_deduplicated_and_ignore_bare_names():
    tc = gcc()
    assert shellenv.tool_dirs(tc) == [str(Path("/opt/gcc/bin"))]
    bare = Toolchain(name="gcc", c_compiler="gcc", cxx_compiler="g++", archiver="ar", linker="g++")
    assert shellenv.tool_dirs(bare) == []


def test_overrides_put_the_toolchain_first_on_path():
    changes = shellenv.overrides(gcc(), {"PATH": "/usr/bin"}, root=Path("/p"), config="Release", windows=False)
    assert changes["PATH"] == os.pathsep.join([str(Path("/opt/gcc/bin")), "/usr/bin"])
    assert changes["CC"] == "/opt/gcc/bin/gcc" and changes["CXX"] == "/opt/gcc/bin/g++" and changes["AR"] == "/opt/gcc/bin/ar"
    assert changes["CHARPENTE_CONFIG"] == "Release" and changes["CHARPENTE_TOOLCHAIN"] == "gcc" and changes["CHARPENTE_SHELL"] == "1"
    assert changes["CHARPENTE_ROOT"] == str(Path("/p"))


def test_overrides_keep_the_case_of_the_existing_path_variable():
    assert "Path" in shellenv.overrides(gcc(), {"Path": "C:\\Windows"}, root=Path("/p"), windows=True)


def test_a_driver_toolchain_becomes_a_full_command_and_env_is_applied():
    changes = shellenv.overrides(zig(), {}, root=Path("/p"), windows=False)
    assert changes["CC"] == "/z/zig cc -target wasm32-wasi" and changes["CXX"] == "/z/zig c++ -target wasm32-wasi"
    assert changes["AR"] == "/z/zig ar" and changes["CHARPENTE_PLATFORM"] == "wasm32-wasi"
    assert changes["ZIG_GLOBAL_CACHE_DIR"] == "/cache dir" and "PATH" in changes
    assert shellenv.overrides(zig(), {}, root=Path("/p"), windows=True)["CC"] == "/z/zig cc -target wasm32-wasi"


def test_paths_with_spaces_are_quoted_in_the_compiler_commands():
    tc = Toolchain(name="x", c_compiler="C:/Program Files/x/cc", cxx_compiler="C:/Program Files/x/c++", archiver="ar", linker="c++")
    assert shellenv.overrides(tc, {}, root=Path("/p"), windows=True)["CC"] == '"C:/Program Files/x/cc"'
    assert shellenv.overrides(tc, {}, root=Path("/p"), windows=False)["CC"] == "'C:/Program Files/x/cc'"


def test_a_toolchain_that_extends_path_puts_its_folders_first():
    tc = Toolchain(name="emscripten", c_compiler="emcc", cxx_compiler="em++", archiver="emar", linker="em++",
                   env=(("PATH", os.pathsep.join(["/emsdk", "/emsdk/node"])), ("EMSDK", "/emsdk")))
    changes = shellenv.overrides(tc, {"PATH": "/usr/bin"}, root=Path("/p"), windows=False)
    assert changes["PATH"] == os.pathsep.join(["/emsdk", "/emsdk/node", "/usr/bin"]) and changes["EMSDK"] == "/emsdk"


def test_render_formats():
    changes = {"A": "it's", "B": "x y"}
    assert shellenv.render(changes, "sh") == "export A='it'\"'\"'s'\nexport B='x y'"
    assert shellenv.render(changes, "powershell") == "$env:A = 'it''s'\n$env:B = 'x y'"
    assert shellenv.render(changes, "cmd") == 'set "A=it\'s"\nset "B=x y"'
    assert json.loads(shellenv.render(changes, "json")) == changes
    with pytest.raises(ValueError):
        shellenv.render(changes, "fish")
    assert shellenv.default_format(windows=True) == "powershell" and shellenv.default_format(windows=False) == "sh"


def test_find_shell():
    found = {"pwsh": "/pw/pwsh", "bash": "/b/bash", "/custom/zsh": "/custom/zsh"}
    assert shellenv.find_shell({}, which=found.get, windows=True) == ["/pw/pwsh", "-NoLogo"]
    assert shellenv.find_shell({"COMSPEC": "C:\\cmd.exe"}, which={}.get, windows=True) == ["C:\\cmd.exe"]
    assert shellenv.find_shell({}, which={}.get, windows=True) == []
    assert shellenv.find_shell({"SHELL": "/custom/zsh"}, which=found.get, windows=False) == ["/custom/zsh"]
    assert shellenv.find_shell({"SHELL": "/gone"}, which=found.get, windows=False) == ["/b/bash"]
    assert shellenv.find_shell({}, which={}.get, windows=False) == []


# ---------------------------------------------------------------------- the command
def test_print_env_json(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["shell", "--print-env", "--format", "json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["CHARPENTE_SHELL"] == "1" and printed["CC"] and printed["CXX"] and printed["CHARPENTE_ROOT"]


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_a_command_runs_with_the_project_environment(capfd, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = main(["shell", "--", sys.executable, "-c", "import os,sys; sys.stdout.write(os.environ['CHARPENTE_SHELL']+os.environ['CXX'])"])
    out = capfd.readouterr().out
    assert code == 0 and out.startswith("1") and len(out) > 1


def test_the_exit_code_of_the_command_is_returned(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["shell", "--", sys.executable, "-c", "raise SystemExit(7)"]) == 7


def test_an_unknown_command_is_a_coded_error(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["shell", "--", "definitely-not-a-program-xyz"]) != 0
    assert "CH8017" in capsys.readouterr().err


def test_the_new_error_codes_exist_in_both_languages():
    from charpente.i18n import en, fr

    for catalogue in (en.CATALOG, fr.CATALOG):
        for code in ("CH8017", "CH8018"):
            assert catalogue[code]["title"] and catalogue[code]["fix"]


# ---------------------------------------------------------------------- the terminal interface
textual = pytest.importorskip("textual")

WORKSPACE = '''from charpente import *

with Workspace("demo", version="1.0.0") as ws:
    with Target("lib") as lib:
        lib.kind(Kind.STATIC_LIBRARY)
        lib.standard("c++17")
        lib.sources(["src/lib.cpp"])

    with Target("app") as app:
        app.kind(Kind.EXECUTABLE)
        app.standard("c++17")
        app.sources(["src/main.cpp"])
        app.uses("lib")
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    (tmp_path / "src").mkdir()
    (tmp_path / "demo.charpente").write_text(WORKSPACE, encoding="utf-8")
    (tmp_path / "src" / "lib.cpp").write_text("int value() { return 3; }\n", encoding="utf-8")
    (tmp_path / "src" / "main.cpp").write_text("int value();\nint main() { return value() - 3; }\n", encoding="utf-8")
    return tmp_path


def _run(coro):
    return asyncio.run(coro)


def _log_text(app):
    log = app.query_one("#log")
    return "\n".join(line.text for line in log.lines)


def test_the_interface_lists_the_targets(project):
    from textual.widgets import DataTable

    from charpente.serve.state import ServerState
    from charpente.tui import CharpenteApp

    async def scenario():
        app = CharpenteApp(ServerState(project))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#targets", DataTable)
            assert table.row_count == 2
            assert {table.get_row_at(i)[0] for i in range(2)} == {"lib", "app"}
            assert app.selected() in ("lib", "app")

    _run(scenario())


def test_a_broken_workspace_is_explained_and_can_be_reloaded(project):
    from textual.widgets import DataTable

    from charpente.serve.state import ServerState
    from charpente.tui import CharpenteApp

    (project / "demo.charpente").write_text("x = (", encoding="utf-8")

    async def scenario():
        app = CharpenteApp(ServerState(project))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#targets", DataTable).row_count == 0 and "Cannot load" in _log_text(app)
            (project / "demo.charpente").write_text(WORKSPACE, encoding="utf-8")
            await pilot.press("l")
            await pilot.pause()
            assert app.query_one("#targets", DataTable).row_count == 2

    _run(scenario())


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_building_from_the_interface_updates_the_results(project):
    from charpente.serve.state import ServerState
    from charpente.tui import OK, CharpenteApp

    async def scenario():
        app = CharpenteApp(ServerState(project))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("a")
            for _ in range(600):                                               # up to ~60 s
                await pilot.pause(0.1)
                if not app.busy:
                    break
            assert not app.busy
            assert app.results.get("app") == OK and app.results.get("lib") == OK
            assert "Build succeeded" in str(app.query_one("#status").render())

    _run(scenario())


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_a_compile_error_is_shown_in_the_log(project):
    from charpente.serve.state import ServerState
    from charpente.tui import FAILED, CharpenteApp

    (project / "src" / "main.cpp").write_text("int main() { return nope; }\n", encoding="utf-8")

    async def scenario():
        app = CharpenteApp(ServerState(project))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("a")
            for _ in range(600):
                await pilot.pause(0.1)
                if not app.busy:
                    break
            assert app.results.get("app") == FAILED
            assert "nope" in _log_text(app) and "FAILED" in str(app.query_one("#status").render())

    _run(scenario())


def test_a_second_task_is_refused_while_one_runs(project):
    from charpente.serve.state import ServerState
    from charpente.tui import CharpenteApp

    async def scenario():
        app = CharpenteApp(ServerState(project))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.begin("first") is True
            assert app.begin("second") is False and "already running" in _log_text(app)
            app.end("done")
            assert app.begin("third") is True

    _run(scenario())


def test_the_command_reports_a_missing_textual(monkeypatch, capsys, project):
    monkeypatch.chdir(project)
    monkeypatch.setitem(sys.modules, "charpente.tui", None)                    # makes `from ..tui import ...` raise ImportError
    assert main(["tui"]) != 0
    assert "CH8018" in capsys.readouterr().err
