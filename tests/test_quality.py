"""The quality gate: checks, configuration, levels, events, records. Tools are faked; git is real where it matters."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from charpente.core import process
from charpente.errors import ChError
from charpente.events import EventBus
from charpente.quality import checks_build, checks_release, checks_static, gate
from charpente.quality import files as qfiles
from charpente.quality.model import (
    FAILED,
    FIXED,
    PASSED,
    SKIPPED,
    Check,
    CheckContext,
    CheckResult,
    Finding,
    GateResult,
    level_at_least,
    normalise_level,
)

HAVE_GIT = shutil.which("git") is not None
needs_git = pytest.mark.skipif(not HAVE_GIT, reason="git is not installed")


def ctx(root, **kw):
    return CheckContext(root=root, level="strict", **kw)


class Rec:
    """A recording stand-in for process.run."""

    def __init__(self, responses=None):
        self.calls, self.responses = [], responses or []

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        code, out = self.responses.pop(0) if self.responses else (0, "")
        return process.ProcessResult(tuple(argv), code, out, "")


# ------------------------------------------------------------------ levels
def test_levels_and_aliases():
    assert normalise_level("Fast") == "rapide" and normalise_level("STRICT") == "strict"
    with pytest.raises(ValueError):
        normalise_level("paranoid")
    assert level_at_least("strict", "standard") and not level_at_least("rapide", "standard")


# ------------------------------------------------------------------ secrets
@pytest.mark.parametrize("line, label", [
    ('key = "AKIAIOSFODNN7EXAMPLE"', "AWS"),
    ("token: ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8", "GitHub token"),
    ("-----BEGIN RSA PRIVATE KEY-----", "Private key"),
    ("xoxb-1234567890-abcdefghij", "Slack"),
    ('password = "Tr0ub4dor&3xKq9vZ"', "hard-coded password"),
    ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk", "JSON Web Token"),
])
def test_secret_patterns_are_found_and_redacted(line, label):
    hits = checks_static.scan_text("int x;\n" + line + "\n")
    assert len(hits) == 1 and hits[0][0] == 2 and label in hits[0][1]
    assert "*" in hits[0][2] and "EXAMPLE" not in hits[0][2]                 # the excerpt is redacted


@pytest.mark.parametrize("line", [
    'password = "changeme"', 'password = "your-password-here"', 'token = "${GITHUB_TOKEN}"',
    'api_key = "xxxxxxxxxxxx"', 'secret = "aaaaaaaaaaaa"', "int password_length = 12;",
    'name = "a-perfectly-ordinary-identifier"', 'AKIAIOSFODNN7EXAMPLE  // charpente:allow-secret',
])
def test_placeholders_words_and_marked_lines_are_not_secrets(line):
    assert checks_static.scan_text(line + "\n") == []


def test_entropy_separates_random_from_words():
    assert checks_static.entropy("aaaaaaaa") == 0 and checks_static.entropy("Tr0ub4dor&3xKq9vZ") > 3.3
    assert checks_static.entropy("") == 0


def test_secrets_check_scans_files_skips_binaries_and_honours_allow(tmp_path):
    (tmp_path / "a.cpp").write_text('const char* k = "AKIAIOSFODNN7EXAMPLE";\n')
    (tmp_path / "blob.bin").write_bytes(b"\x00AKIAIOSFODNN7EXAMPLE")
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "sample.txt").write_text("AKIAIOSFODNN7EXAMPLE\n")
    result = checks_static.SecretsCheck().run(ctx(tmp_path, config={"allow": ["fixtures/*"]}))
    assert result.status == FAILED and [f.file for f in result.findings] == ["a.cpp"]
    assert result.findings[0].line == 1 and "AKIAIOSFODNN7EXAMPLE" not in result.findings[0].message
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "b.txt").write_text("nothing here\n")
    assert checks_static.SecretsCheck().run(ctx(clean)).status == PASSED


# ------------------------------------------------------------------ file size
def test_file_size_check(tmp_path):
    (tmp_path / "big.dat").write_bytes(b"x" * 3000)
    (tmp_path / "ok.txt").write_text("x")
    (tmp_path / "keep.dat").write_bytes(b"x" * 3000)
    result = checks_static.FileSizeCheck().run(ctx(tmp_path, config={"max_kb": 1, "allow": ["keep.dat"]}))
    assert result.status == FAILED and [f.file for f in result.findings] == ["big.dat"]
    assert "Git LFS" in result.findings[0].fix
    assert checks_static.FileSizeCheck().run(ctx(tmp_path, config={"max_kb": 10})).status == PASSED


# ------------------------------------------------------------------ format
def test_format_is_skipped_visibly_without_the_tool(tmp_path):
    result = checks_static.FormatCheck().run(ctx(tmp_path, which=lambda n: None))
    assert result.status == SKIPPED and "clang-format not found" in result.message


def test_format_reports_located_violations_and_fixes_on_request(tmp_path):
    source = tmp_path / "a.cpp"
    source.write_text("int  main(){}\n")
    out = f"{source}:1:4: error: code should be clang-formatted [-Wclang-format-violations]"
    rec = Rec([(1, out)])
    result = checks_static.FormatCheck().run(ctx(tmp_path, which=lambda n: "/bin/clang-format", run=rec))
    assert result.status == FAILED and result.findings[0].line == 1 and result.findings[0].file == "a.cpp"
    assert rec.calls[0][0][-3:] == ["--dry-run", "-Werror", str(source)]

    def formatter(argv, **kw):
        if "-i" in argv:
            Path(argv[-1]).write_text("int main() {}\n")
        return process.ProcessResult(tuple(argv), 0, "", "")

    fixed = checks_static.FormatCheck().run(ctx(tmp_path, fix=True, which=lambda n: "/bin/clang-format", run=formatter))
    assert fixed.status == FIXED and "1 file" in fixed.message
    again = checks_static.FormatCheck().run(ctx(tmp_path, fix=True, which=lambda n: "/bin/clang-format", run=formatter))
    assert again.status == PASSED


# ------------------------------------------------------------------ dsl lint
def test_dsl_lint_check(tmp_path, monkeypatch):
    (tmp_path / "app.charpente").write_text('from charpente import *\nwith Workspace("w") as ws:\n    pass\n')
    assert checks_static.DslLintCheck().run(ctx(tmp_path)).status == PASSED
    (tmp_path / "app.charpente").write_text("def broken(:\n")
    result = checks_static.DslLintCheck().run(ctx(tmp_path))
    assert result.status == FAILED and result.findings[0].file == "app.charpente"
    def nothing(**kw):
        raise ChError("CH1002", directory="x")

    monkeypatch.setattr(checks_static, "find_workspace_file", nothing)
    assert checks_static.DslLintCheck().run(ctx(tmp_path)).status == SKIPPED


# ------------------------------------------------------------------ build-driven checks
def test_build_check_turns_diagnostic_events_into_findings(tmp_path):
    events = "\n".join(json.dumps(e) for e in [
        {"type": "diagnostic.emitted", "payload": {"file": str(tmp_path / "src" / "a.cpp"), "line": 3, "column": 5,
                                                   "severity": "error", "message": "boom", "code": None}},
        {"type": "target.failed", "payload": {"error": "app failed"}}])
    result = checks_build.BuildCheck().run(ctx(tmp_path, run=Rec([(1, events)])))
    assert result.status == FAILED and result.findings[0].file == "src/a.cpp" and result.findings[0].line == 3
    ok = checks_build.BuildCheck().run(ctx(tmp_path, run=Rec([(0, "")])))
    assert ok.status == PASSED
    silent = checks_build.BuildCheck().run(ctx(tmp_path, run=Rec([(1, "not json at all")])))
    assert silent.status == FAILED and silent.findings[0].code == "build"


def test_build_check_passes_the_platform_through(tmp_path):
    rec = Rec([(0, "")])
    checks_build.BuildCheck().run(ctx(tmp_path, run=rec, platform="linux-arm64"))
    assert rec.calls[0][0][-2:] == ["--platform", "linux-arm64"]


def test_tests_check_reports_failures_and_flaky_tests(tmp_path):
    out = "  [FAIL] unit (exit code 3)\n  [BUILD FAILED] other: compile error\n  [FLAKY] net"
    failed = checks_build.TestsCheck().run(ctx(tmp_path, run=Rec([(1, out)])))
    assert failed.status == FAILED
    assert {f.code for f in failed.findings} == {"test-failed", "build", "flaky-test"}
    flaky = checks_build.TestsCheck().run(ctx(tmp_path, run=Rec([(0, "  [FLAKY] net")])))
    assert flaky.status == PASSED and flaky.findings[0].severity == "warning" and "flaky" in flaky.message
    assert checks_build.TestsCheck().run(ctx(tmp_path, run=Rec([(0, "No test targets in this workspace")]))).status == SKIPPED


def test_syntax_only_rewrites_a_compile_command():
    argv = ["g++", "-c", "a.cpp", "-o", "a.o", "-std=c++17", "-g", "-MMD", "-MF", "a.o.d", "-Iinc"]
    assert checks_build._syntax_only(argv, ["-Wall"]) == ["g++", "a.cpp", "-std=c++17", "-g", "-Iinc",
                                                          "-fsyntax-only", "-Wall", "-Werror"]
    assert checks_build._syntax_only(["cl", "/c", "a.cpp", "/Foa.obj"], []) is None


def test_warnings_check_compiles_only_changed_files_with_werror(tmp_path):
    (tmp_path / "build").mkdir()
    src, other = tmp_path / "a.cpp", tmp_path / "b.cpp"
    src.write_text("x")
    other.write_text("x")
    (tmp_path / "build" / "compile_commands.json").write_text(json.dumps([
        {"file": str(src), "directory": str(tmp_path), "arguments": ["g++", "-c", str(src), "-o", "a.o"]},
        {"file": str(other), "directory": str(tmp_path), "arguments": ["g++", "-c", str(other), "-o", "b.o"]}]))
    rec = Rec([(1, f"{src}:2:3: warning: unused variable 'x' [-Wunused-variable]")])
    result = checks_build.WarningsCheck().run(ctx(tmp_path, files=[src], run=rec))
    assert result.status == FAILED and len(rec.calls) == 1 and "-Werror" in rec.calls[0][0]
    assert result.findings[0].file == "a.cpp" and result.findings[0].line == 2
    assert checks_build.WarningsCheck().run(ctx(tmp_path / "x", files=[])).status == SKIPPED


def test_analysers_are_skipped_without_tools_or_a_compilation_database(tmp_path):
    for check in (checks_build.TidyCheck(), checks_build.CppcheckCheck()):
        assert check.run(ctx(tmp_path, which=lambda n: None)).status == SKIPPED
        assert "compile_commands.json" in check.run(ctx(tmp_path, which=lambda n: "/bin/x")).message


def test_tidy_findings_are_located(tmp_path):
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "compile_commands.json").write_text("[]")
    src = tmp_path / "a.cpp"
    src.write_text("x")
    rec = Rec([(1, f"{src}:4:2: warning: use nullptr [modernize-use-nullptr]")])
    result = checks_build.TidyCheck().run(ctx(tmp_path, files=[src], which=lambda n: "/bin/clang-tidy", run=rec))
    assert result.status == FAILED and result.findings[0].line == 4
    assert "--warnings-as-errors=*" in rec.calls[0][0]


def test_sanitizer_check_maps_outcomes(tmp_path):
    skip = checks_build.SanitizersCheck().run(ctx(tmp_path, run=Rec([(1, "charpente: [CH8011] This toolchain cannot build with sanitizers: no asan")])))
    assert skip.status == SKIPPED and "no asan" in skip.message
    fail = checks_build.SanitizersCheck().run(ctx(tmp_path, run=Rec([(1, "SUMMARY: AddressSanitizer: heap-buffer-overflow x.cpp:3")])))
    assert fail.status == FAILED and "heap-buffer-overflow" in fail.findings[0].message
    assert checks_build.SanitizersCheck().run(ctx(tmp_path, run=Rec([(0, "")]))).status == PASSED


GCOV = """File 'C:/proj/src/lib.cpp'
Lines executed:80.00% of 5
File 'C:/msys64/include/c++/vector'
Lines executed:10.00% of 100
File 'C:/proj/tests/t.cpp'
Lines executed:100.00% of 4
Lines executed:50.00% of 109
"""


def test_gcov_output_is_parsed():
    parsed = checks_build.parse_gcov(GCOV)
    assert parsed["C:/proj/src/lib.cpp"] == (4, 5) and parsed["C:/msys64/include/c++/vector"] == (10, 100)


def test_coverage_check_counts_only_project_sources(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    gcda = root / "build" / "Debug-cov" / "lib" / "obj" / "x.gcda"
    gcda.parent.mkdir(parents=True)
    gcda.write_text("")
    text = (f"File '{root.resolve().as_posix()}/src/lib.cpp'\nLines executed:80.00% of 10\n"
            f"File '{root.resolve().as_posix()}/tests/t.cpp'\nLines executed:0.00% of 50\n"
            "File 'C:/system/vector'\nLines executed:0.00% of 999\n")
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return process.ProcessResult(tuple(argv), 0, "" if "test" in argv else text, "")

    result = checks_build.CoverageCheck().run(ctx(root, run=run, which=lambda n: "/bin/gcov", config={"minimum": 75}))
    assert result.status == PASSED and "80.0% of 10 lines" in result.message
    low = checks_build.CoverageCheck().run(ctx(root, run=run, which=lambda n: "/bin/gcov", config={"minimum": 90}))
    assert low.status == FAILED and low.findings[0].file == "src/lib.cpp"
    assert checks_build.CoverageCheck().run(ctx(root, which=lambda n: None)).status == SKIPPED


def test_platforms_check_builds_what_it_can_and_names_what_it_skips(tmp_path, monkeypatch):
    from charpente import platforms, toolchains
    from charpente.dsl.model import OS

    monkeypatch.setattr(platforms, "host", lambda: platforms.get("windows-x64"))
    monkeypatch.setattr(toolchains, "detect", lambda _os, which=None: [
        toolchains.Toolchain(name="zig", c_compiler="z", cxx_compiler="z", archiver="z", linker="z",
                             targets=("linux-arm64",))])
    monkeypatch.setattr("charpente.platform.host_os", lambda: OS.WINDOWS)
    rec = Rec([(0, "")])
    result = checks_build.PlatformsCheck().run(ctx(tmp_path, run=rec, config={"platforms": ["linux-arm64", "macos-arm64"]}))
    assert result.status == PASSED and "built linux-arm64" in result.message and "macos-arm64" in result.message
    assert len(rec.calls) == 1
    assert checks_build.PlatformsCheck().run(ctx(tmp_path)).status == SKIPPED
    bad = checks_build.PlatformsCheck().run(ctx(tmp_path, run=Rec([(1, "")]), config={"platforms": ["linux-arm64"]}))
    assert bad.status == FAILED


# ------------------------------------------------------------------ release checks
def test_spdx_expressions_and_license_policy():
    assert checks_release.license_terms("(MIT OR Apache-2.0)") == {"MIT", "Apache-2.0"}
    assert checks_release.license_terms("GPL-2.0-only WITH Classpath-exception-2.0") == {"GPL-2.0-only", "Classpath-exception-2.0"}


def test_release_checks_skip_without_a_lock_file(tmp_path):
    for check in (checks_release.AuditCheck(), checks_release.LicensesCheck()):
        assert check.run(ctx(tmp_path)).status == SKIPPED


# ------------------------------------------------------------------ gate: config, selection, running
def test_config_defaults_and_errors(tmp_path):
    assert gate.load_config(tmp_path).level == "standard"
    (tmp_path / ".charpente").mkdir()
    path = tmp_path / ".charpente" / "quality.toml"
    path.write_text('[gate]\nlevel = "strict"\nfail_on_skipped = true\n[checks.secrets]\nenabled = false\n')
    config = gate.load_config(tmp_path)
    assert config.level == "strict" and config.fail_on_skipped and not config.enabled("secrets") and config.enabled("build")
    for text, fragment in (("[gate\n", "invalid"), ('[gate]\nlevel = "paranoid"\n', "unknown level"), ("[other]\n", "unknown section"),
                           ("[checks]\nsecrets = 3\n", "tables")):
        path.write_text(text)
        with pytest.raises(ChError) as exc:
            gate.load_config(tmp_path)
        assert exc.value.code == "CH8012" or fragment in str(exc.value)


def test_the_starter_config_is_valid_and_lists_all_levels(tmp_path):
    (tmp_path / ".charpente").mkdir()
    (tmp_path / gate.CONFIG_PATH).write_text(gate.DEFAULT_CONFIG)
    config = gate.load_config(tmp_path)
    assert config.for_check("coverage")["minimum"] == 70
    levels = gate.levels()
    assert "build" in levels["rapide"] and "tests" in levels["standard"] and "coverage" in levels["strict"]


class Fake(Check):
    def __init__(self, name, level="rapide", status=PASSED, findings=None, raises=None, per_file=False):
        self.name, self.level, self.status, self._findings, self.raises, self.per_file = name, level, status, findings or [], raises, per_file
        self.seen = None

    def run(self, ctx):
        self.seen = ctx
        if self.raises:
            raise self.raises
        return CheckResult(self.name, self.status, list(self._findings), message="msg")


def test_levels_select_cumulatively_and_only_skip_override(tmp_path):
    checks = [Fake("a"), Fake("b", "standard"), Fake("c", "strict")]
    names = lambda level, **kw: [c.name for c in gate.select(checks, level, gate.QualityConfig(), **kw)]   # noqa: E731
    assert names("rapide") == ["a"] and names("standard") == ["a", "b"] and names("strict") == ["a", "b", "c"]
    assert names("rapide", only=["c"]) == ["c"] and names("strict", skip=["b"]) == ["a", "c"]
    with pytest.raises(ChError):
        names("strict", only=["nope"])
    disabled = gate.QualityConfig(checks={"a": {"enabled": False}})
    assert [c.name for c in gate.select(checks, "strict", disabled)] == ["b", "c"]


def test_the_gate_runs_in_order_emits_events_and_blocks_on_failure(tmp_path):
    bus = EventBus()
    events = []
    bus.subscribe(events.append, sync=True)
    bad = Fake("bad", status=FAILED, findings=[Finding("nope", "x.cpp", 3, 1, code="c1", fix="do this")])
    result = gate.run_gate(tmp_path, level="rapide", bus=bus, checks=[Fake("first"), bad, Fake("skipme", status=SKIPPED)],
                           config=gate.QualityConfig())
    assert [r.name for r in result.results] == ["first", "bad", "skipme"] and not result.ok
    types = [e.type for e in events]
    assert types.count("gate.check_started") == 3 and "gate.check_failed" in types and "gate.blocked" in types
    diag = next(e for e in events if e.type == "diagnostic.emitted")
    assert diag.payload["file"] == "x.cpp" and diag.payload["line"] == 3 and diag.payload["fix"] == "do this"
    assert "skipme" not in [e.payload.get("check") for e in events if e.type == "gate.check_passed"]


def test_skipped_checks_fail_the_gate_only_when_asked(tmp_path):
    checks = [Fake("s", status=SKIPPED)]
    assert gate.run_gate(tmp_path, level="rapide", checks=checks, config=gate.QualityConfig()).ok
    strict = gate.run_gate(tmp_path, level="rapide", checks=checks, config=gate.QualityConfig(fail_on_skipped=True))
    assert not strict.ok


def test_a_crashing_check_is_a_failure_not_a_pass(tmp_path):
    result = gate.run_gate(tmp_path, level="rapide", checks=[Fake("boom", raises=RuntimeError("kaput"))], config=gate.QualityConfig())
    assert not result.ok and result.results[0].findings[0].code == "check-crashed" and "kaput" in result.results[0].findings[0].message
    coded = gate.run_gate(tmp_path, level="rapide", checks=[Fake("c", raises=ChError("CH2001", os="x"))], config=gate.QualityConfig())
    assert coded.results[0].findings[0].code == "CH2001"


def test_fix_mode_fixes_then_verifies(tmp_path):
    order = []

    class Fixer(Check):
        name, level = "format", "rapide"

        def run(self, ctx):
            order.append(("fix" if ctx.fix else "verify"))
            return CheckResult(self.name, FIXED if ctx.fix else PASSED)

    result = gate.run_gate(tmp_path, level="rapide", fix=True, checks=[Fixer()], config=gate.QualityConfig())
    assert order == ["fix", "verify"] and result.ok and result.results[0].status == PASSED


def test_per_file_checks_get_only_the_changed_files(tmp_path):
    a, b = Fake("perfile", per_file=True), Fake("whole")
    gate.run_gate(tmp_path, level="rapide", changed=False, checks=[a, b], config=gate.QualityConfig())
    assert a.seen.files is None


def test_records_and_the_tree_log(tmp_path):
    result = GateResult(level="standard", results=[CheckResult("a", PASSED, message="ok"), CheckResult("b", SKIPPED)])
    gate.write_record(tmp_path, result, tree="abc123")
    record = gate.read_record(tmp_path)
    assert record["level"] == "standard" and record["ok"] and record["results"][1]["status"] == "skipped"
    assert gate.read_log(tmp_path)["abc123"]["level"] == "standard"
    failing = GateResult(level="rapide", results=[CheckResult("a", FAILED)])
    gate.write_record(tmp_path, failing, tree="def456")
    assert "def456" not in gate.read_log(tmp_path)                      # a failed run never vouches for a tree
    assert gate.read_record(tmp_path / "missing") is None and gate.read_log(tmp_path / "missing") == {}


def test_report_lists_findings_fixes_and_the_verdict(tmp_path):
    result = GateResult(level="rapide", results=[
        CheckResult("secrets", FAILED, [Finding("possible secret", "a.cpp", 3, fix="rotate it")], "1 possible secret(s)"),
        CheckResult("format", SKIPPED, message="clang-format not found")])
    text = gate.render(result)
    assert "[FAIL ] secrets" in text and "a.cpp:3: error: possible secret" in text and "fix: rotate it" in text
    assert "BLOCKED" in text and "skipped checks did not run" in text


def test_module_checks_are_adapted(tmp_path):
    class Mod:
        name, level = "mine", "rapide"

        def run(self, root, files, fix):
            return [Finding("from a module", "x.txt", 1)]

    class Registry:
        def all(self, kind):
            return [type("E", (), {"name": "mine", "obj": Mod()})()] if kind == "quality_check" else []

    checks = gate.all_checks(Registry())
    assert checks[-1].name == "mine"
    result = gate.run_gate(tmp_path, level="rapide", checks=[checks[-1]], config=gate.QualityConfig())
    assert not result.ok and result.results[0].findings[0].message == "from a module"


def test_builtin_checks_are_registered_as_extensions():
    from charpente.modules.runtime import get_registry

    names = {e.name for e in get_registry().all("quality_check")}
    assert {"build", "secrets", "coverage", "sbom"} <= names
    assert [c.name for c in gate.all_checks()][:2] == ["build", "format"]


# ------------------------------------------------------------------ files (real git)
def git(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t.t", "-c", "user.name=t", *args],
                          capture_output=True, text=True, check=True).stdout


@needs_git
def test_list_and_changed_files_use_git_and_skip_build_output(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "a.cpp").write_text("1")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "junk.o").write_text("x")
    git(tmp_path, "add", "a.cpp")
    git(tmp_path, "commit", "-qm", "init")
    assert [p.name for p in qfiles.list_files(tmp_path)] == ["a.cpp"]
    assert qfiles.changed_files(tmp_path) == []
    (tmp_path / "a.cpp").write_text("2")
    (tmp_path / "new.cpp").write_text("n")
    (tmp_path / "staged.cpp").write_text("s")
    git(tmp_path, "add", "staged.cpp")
    assert sorted(p.name for p in qfiles.changed_files(tmp_path)) == ["a.cpp", "new.cpp", "staged.cpp"]


def test_outside_git_everything_is_listed_and_changed_is_unknown(tmp_path):
    (tmp_path / "a.txt").write_text("1")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "x").write_text("1")
    assert [p.name for p in qfiles.list_files(tmp_path, which=lambda n: None)] == ["a.txt"]
    assert qfiles.changed_files(tmp_path, which=lambda n: None) is None
    assert qfiles.matches_any("src/gen/a.cpp", ["gen/*", "*.h"]) is False and qfiles.matches_any("a.h", ["*.h"])


# ------------------------------------------------------------------ the command
def test_check_command_init_list_and_json(tmp_path, monkeypatch, capsys):
    from charpente.commands import check

    monkeypatch.chdir(tmp_path)
    assert check.execute(["--init"]) == 0 and (tmp_path / gate.CONFIG_PATH).is_file()
    assert check.execute(["--init"]) == 1                                   # never overwrites
    assert check.execute(["--list"]) == 0
    listing = capsys.readouterr().out
    assert "secrets" in listing and "strict" in listing
    (tmp_path / "a.txt").write_text("hello\n")
    code = check.execute(["--level", "rapide", "--only", "secrets", "--only", "file-size", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0 and data["ok"] and [r["check"] for r in data["results"]] == ["secrets", "file-size"]
    (tmp_path / "leak.txt").write_text('AKIAIOSFODNN7EXAMPLE\n')
    code = check.execute(["--only", "secrets"])
    assert code == 1 and "BLOCKED" in capsys.readouterr().out
