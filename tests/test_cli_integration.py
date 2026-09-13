"""End-to-end CLI tests that invoke the real host compiler (no mocking) --
these are the tests that would have caught the two real bugs found during
manual smoke testing (a Path.glob('**.cpp') pathlib rejects, and
str.format() colliding with literal braces in a C++ source template).
Skipped automatically if no compiler is available."""
import pytest

from charpente.cli import main
from charpente.platform import host_os
from charpente.toolchains import NoToolchainFoundError, pick_default

def _has_compiler() -> bool:
    try:
        pick_default(host_os())
        return True
    except NoToolchainFoundError:
        return False


requires_compiler = pytest.mark.skipif(not _has_compiler(), reason="no C/C++ compiler on PATH")


@pytest.fixture(autouse=True)
def trust_and_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(tmp_path)
    yield tmp_path


@requires_compiler
def test_init_then_build_then_run(tmp_path, capfd):
    assert main(["init", "Demo", "--dir", str(tmp_path)]) == 0

    workspace_file = tmp_path / "Demo.charpente"
    assert workspace_file.exists()
    assert (tmp_path / "src" / "main.cpp").exists()

    assert main(["build", "--file", str(workspace_file)]) == 0
    out = capfd.readouterr().out
    assert "[ok]" in out

    # capfd (not capsys): the compiled binary is a real child process that
    # writes to the inherited OS-level stdout, which capsys's sys.stdout
    # replacement never sees.
    assert main(["run", "--file", str(workspace_file)]) == 0
    out = capfd.readouterr().out
    assert "Hello from Demo!" in out


@requires_compiler
def test_build_is_incremental_on_second_run(tmp_path, capsys):
    main(["init", "Demo", "--dir", str(tmp_path)])
    workspace_file = tmp_path / "Demo.charpente"

    main(["build", "--file", str(workspace_file)])
    capsys.readouterr()

    main(["build", "--file", str(workspace_file)])
    out = capsys.readouterr().out
    assert "[up to date]" in out


@requires_compiler
def test_clean_removes_build_directory(tmp_path):
    main(["init", "Demo", "--dir", str(tmp_path)])
    workspace_file = tmp_path / "Demo.charpente"
    main(["build", "--file", str(workspace_file)])
    assert (tmp_path / "build").exists()

    assert main(["clean", "--file", str(workspace_file)]) == 0
    assert not (tmp_path / "build").exists()


@requires_compiler
def test_package_produces_a_zip_with_the_binary_inside(tmp_path):
    import zipfile

    main(["init", "Demo", "--dir", str(tmp_path)])
    workspace_file = tmp_path / "Demo.charpente"

    assert main(["package", "--file", str(workspace_file), "--config", "Debug"]) == 0
    archives = list((tmp_path / "dist").glob("*.zip"))
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as zf:
        names = zf.namelist()
    assert any("Demo" in n for n in names)


def test_ask_without_ai_configured_gives_honest_message(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CHARPENTE_AI_URL", raising=False)
    monkeypatch.delenv("CHARPENTE_AI_PROVIDER", raising=False)

    code = main(["ask", "why", "does", "my", "build", "fail"])
    out = capsys.readouterr().out
    assert code == 1
    assert "not configured" in out


def test_unknown_command_prints_help_and_fails(capsys):
    code = main(["frobnicate"])
    assert code == 1
    out = capsys.readouterr()
    assert "unknown command" in (out.out + out.err)


def test_version_flag(capsys):
    assert main(["--version"]) == 0
    assert "charpente" in capsys.readouterr().out


@requires_compiler
def test_run_forwards_program_arguments_after_double_dash(tmp_path, capfd):
    """Also confirms the "--" separator itself is NOT forwarded (a
    genuine bug found and fixed after the CLI layer was first written --
    argparse.REMAINDER keeps a leading "--" as a literal token unless the
    command strips it)."""
    src = tmp_path / "src"
    src.mkdir()
    cpp_lines = [
        "#include <cstdio>",
        "int main(int argc, char** argv) {",
        "    for (int i = 1; i < argc; ++i) std::printf(" + '"arg[%d]=%s' + "\\n" + '"' + ", i, argv[i]);",
        "    return 0;",
        "}",
        "",
    ]
    (src / "main.cpp").write_text("\n".join(cpp_lines))
    (tmp_path / "w.charpente").write_text("""
from charpente import *
with Workspace("W") as ws:
    with Target("echoargs") as t:
        t.sources(["src/**/*.cpp"])
""")

    assert main(["run", "--", "--hello", "world"]) == 0
    out = capfd.readouterr().out
    assert "arg[1]=--hello" in out
    assert "arg[2]=world" in out
    assert "arg[1]=--" + "\n" not in out  # the "--" separator itself must not be forwarded


@requires_compiler
def test_test_command_builds_and_runs_a_passing_test(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.cpp").write_text("int main() { return 0; }\n")
    (tmp_path / "w.charpente").write_text("""
from charpente import *
with Workspace("W") as ws:
    with Target("mytest") as t:
        t.kind(Kind.TEST)
        t.sources(["src/**/*.cpp"])
""")

    code = main(["test"])
    out = capsys.readouterr().out
    assert code == 0
    assert "[PASS] mytest" in out
    assert "1/1 test target(s) passed." in out


@requires_compiler
def test_test_command_reports_a_failing_test(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.cpp").write_text("int main() { return 1; }\n")  # non-zero exit
    (tmp_path / "w.charpente").write_text("""
from charpente import *
with Workspace("W") as ws:
    with Target("mytest") as t:
        t.kind(Kind.TEST)
        t.sources(["src/**/*.cpp"])
""")

    code = main(["test"])
    out = capsys.readouterr().out
    assert code == 1
    assert "[FAIL] mytest" in out
    assert "0/1 test target(s) passed." in out


def test_test_command_with_no_test_targets_is_a_clean_noop(tmp_path, capsys):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.cpp").write_text("int main() { return 0; }\n")
    (tmp_path / "w.charpente").write_text("""
from charpente import *
with Workspace("W") as ws:
    with Target("app") as t:
        t.sources(["src/**/*.cpp"])
""")

    assert main(["test"]) == 0
    assert "No test targets" in capsys.readouterr().out
