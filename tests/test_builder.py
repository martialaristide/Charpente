import subprocess
import time
from pathlib import Path

import pytest

from charpente import builder
from charpente.dsl.model import Kind, Language, OS, Target, Workspace
from charpente.toolchains import Toolchain

GCC = Toolchain(name="gcc", c_compiler="gcc", cxx_compiler="g++", archiver="ar", linker="g++")


def _fake_compiler(fail_on: set = frozenset()):
    """A stand-in for subprocess.run: creates the file a real compiler/
    linker/archiver would have created (so the incremental-build filesystem
    checks in builder.py have something real to look at), and lets a test
    force specific invocations to "fail" by source/output name."""
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        # Compile step: "-c SRC -o OBJ" (GNU-style, the only family under test here).
        if "-c" in argv:
            src = Path(argv[argv.index("-c") + 1])
            obj = Path(argv[argv.index("-o") + 1])
            if src.stem in fail_on:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr=f"error compiling {src.name}")
            obj.parent.mkdir(parents=True, exist_ok=True)
            obj.write_text("fake object")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        # Link/archive step: last positional-ish "-o OUT" or archiver "rcs OUT".
        if "rcs" in argv:
            out = Path(argv[argv.index("rcs") + 1])
        elif "-o" in argv:
            out = Path(argv[argv.index("-o") + 1])
        else:
            out = None
        if out is not None:
            if out.stem in fail_on:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="link error")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("fake binary")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    run.calls = calls
    return run


def _workspace_with_one_target(tmp_path, **target_kwargs) -> Workspace:
    (tmp_path / "main.cpp").write_text("int main(){return 0;}")
    ws = Workspace(name="Demo", location=tmp_path)
    ws.add_target(Target(name="app", source_patterns=["*.cpp"], location=tmp_path, **target_kwargs))
    return ws


# =============================================================================
#  build_target()
# =============================================================================
def test_successful_build_produces_output(tmp_path):
    ws = _workspace_with_one_target(tmp_path)
    fake = _fake_compiler()
    result = builder.build_target(ws, ws.targets["app"], GCC, OS.LINUX, run=fake)
    assert result.ok
    assert result.output_path.exists()
    assert not result.skipped


def test_target_with_no_sources_fails_clearly(tmp_path):
    ws = Workspace(name="Demo", location=tmp_path)
    ws.add_target(Target(name="app", source_patterns=["*.cpp"], location=tmp_path))  # no files exist
    result = builder.build_target(ws, ws.targets["app"], GCC, OS.LINUX, run=_fake_compiler())
    assert not result.ok
    assert "no source files" in result.error


def test_compile_failure_stops_before_linking(tmp_path):
    ws = _workspace_with_one_target(tmp_path)
    fake = _fake_compiler(fail_on={"main"})
    result = builder.build_target(ws, ws.targets["app"], GCC, OS.LINUX, run=fake)
    assert not result.ok
    assert "error compiling" in result.error
    # Only the compile call happened, never a link.
    assert all("-c" in c for c in fake.calls)


def test_second_build_with_no_changes_skips_everything(tmp_path):
    ws = _workspace_with_one_target(tmp_path)
    fake = _fake_compiler()
    r1 = builder.build_target(ws, ws.targets["app"], GCC, OS.LINUX, run=fake)
    assert r1.ok and not r1.skipped
    calls_after_first_build = len(fake.calls)

    r2 = builder.build_target(ws, ws.targets["app"], GCC, OS.LINUX, run=fake)
    assert r2.ok and r2.skipped
    assert len(fake.calls) == calls_after_first_build  # no new subprocess calls


def test_touching_a_source_triggers_recompile_and_relink(tmp_path):
    ws = _workspace_with_one_target(tmp_path)
    fake = _fake_compiler()
    builder.build_target(ws, ws.targets["app"], GCC, OS.LINUX, run=fake)
    calls_after_first_build = len(fake.calls)

    time.sleep(0.01)
    (tmp_path / "main.cpp").write_text("int main(){return 1;}")  # newer mtime
    r2 = builder.build_target(ws, ws.targets["app"], GCC, OS.LINUX, run=fake)
    assert r2.ok and not r2.skipped
    assert len(fake.calls) > calls_after_first_build


def test_static_library_uses_archiver(tmp_path):
    ws = _workspace_with_one_target(tmp_path, kind=Kind.STATIC_LIBRARY)
    result = builder.build_target(ws, ws.targets["app"], GCC, OS.LINUX, run=_fake_compiler())
    assert result.ok
    assert result.output_path.name == "libapp.a"


# =============================================================================
#  build_workspace()
# =============================================================================
def test_workspace_build_respects_dependency_order(tmp_path):
    (tmp_path / "core.cpp").write_text("void core(){}")
    (tmp_path / "app.cpp").write_text("int main(){return 0;}")
    ws = Workspace(name="Demo", location=tmp_path)
    ws.add_target(Target(name="core", kind=Kind.STATIC_LIBRARY, source_patterns=["core.cpp"], location=tmp_path))
    ws.add_target(Target(name="app", depends_on=["core"], source_patterns=["app.cpp"], location=tmp_path))

    result = builder.build_workspace(ws, GCC, OS.LINUX, run=_fake_compiler())
    assert result.ok
    names_in_order = [t.target_name for t in result.targets]
    assert names_in_order.index("core") < names_in_order.index("app")


def test_failure_stops_remaining_targets_by_default(tmp_path):
    (tmp_path / "core.cpp").write_text("void core(){}")
    (tmp_path / "app.cpp").write_text("int main(){return 0;}")
    ws = Workspace(name="Demo", location=tmp_path)
    ws.add_target(Target(name="core", kind=Kind.STATIC_LIBRARY, source_patterns=["core.cpp"], location=tmp_path))
    ws.add_target(Target(name="app", depends_on=["core"], source_patterns=["app.cpp"], location=tmp_path))

    result = builder.build_workspace(ws, GCC, OS.LINUX, run=_fake_compiler(fail_on={"core"}))
    assert not result.ok
    assert result.target("core").ok is False
    assert result.target("app") is None  # never attempted


def test_keep_going_skips_only_dependents_of_the_failed_target(tmp_path):
    (tmp_path / "core.cpp").write_text("void core(){}")
    (tmp_path / "app.cpp").write_text("int main(){return 0;}")
    (tmp_path / "tool.cpp").write_text("int tool(){return 0;}")
    ws = Workspace(name="Demo", location=tmp_path)
    ws.add_target(Target(name="core", kind=Kind.STATIC_LIBRARY, source_patterns=["core.cpp"], location=tmp_path))
    ws.add_target(Target(name="app", depends_on=["core"], source_patterns=["app.cpp"], location=tmp_path))
    ws.add_target(Target(name="tool", source_patterns=["tool.cpp"], location=tmp_path))  # independent

    result = builder.build_workspace(ws, GCC, OS.LINUX, run=_fake_compiler(fail_on={"core"}), keep_going=True)
    assert not result.ok
    assert result.target("core").ok is False
    assert result.target("app").ok is False
    assert "depends on failed" in result.target("app").error
    assert result.target("tool").ok is True  # unrelated target still built


def test_dependency_library_is_findable_by_the_linker(tmp_path):
    """The linker step for a target must be able to find a static library
    it depends on, via an automatically-added -L pointing at that
    dependency's own build directory -- without the .charpente file
    declaring any path itself."""
    (tmp_path / "core.cpp").write_text("void core(){}")
    (tmp_path / "app.cpp").write_text("int main(){return 0;}")
    ws = Workspace(name="Demo", location=tmp_path)
    ws.add_target(Target(name="core", kind=Kind.STATIC_LIBRARY,
                         source_patterns=["core.cpp"], location=tmp_path))
    ws.add_target(Target(name="app", depends_on=["core"], link_libraries=["core"],
                         source_patterns=["app.cpp"], location=tmp_path))

    fake = _fake_compiler()
    seen_link_argv = []

    def spying_run(argv, **kwargs):
        if "-o" in argv and "-c" not in argv:  # the link step, not a compile step
            seen_link_argv.append(argv)
        return fake(argv, **kwargs)

    result = builder.build_workspace(ws, GCC, OS.LINUX, run=spying_run)
    assert result.ok

    app_link_argv = seen_link_argv[-1]
    core_build_dir = str(builder.build_dir(ws, "Debug", ws.targets["core"]))
    assert f"-L{core_build_dir}" in app_link_argv
    assert "-lcore" in app_link_argv
