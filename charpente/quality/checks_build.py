"""Checks that build or run things: the build itself, warnings, clang-tidy, cppcheck, tests, sanitizers, coverage,
other platforms.

They drive Charpente itself as a subprocess (`python -m charpente ...`) so a check sees exactly what a user would, and
the gate stays isolated from the engine's state. A tool that is not installed makes a check *skipped* -- visibly; a
strict CI can turn skips into failures (`fail_on_skipped`).
"""
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core import diagnostics
from .files import CPP_SUFFIXES
from .model import FAILED, PASSED, SKIPPED, Check, CheckContext, CheckResult, Finding

SOURCE_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".c++", ".m", ".mm")


def charpente(ctx: CheckContext, args: List[str], timeout: float = 3600) -> Any:
    """Run `charpente <args>` in the project."""
    return ctx.run([ctx.python or sys.executable, "-m", "charpente", *args], cwd=str(ctx.root), timeout=timeout)


def findings_from_jsonl(text: str, root: Path) -> Tuple[List[Finding], List[str]]:
    """(diagnostics, plain lines) from `--output jsonl` output: `diagnostic.emitted` events become findings."""
    findings: List[Finding] = []
    other: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            other.append(line)
            continue
        if event.get("type") == "diagnostic.emitted":
            p = event.get("payload", {})
            file = p.get("file")
            if file:
                try:
                    file = Path(file).resolve().relative_to(root.resolve()).as_posix()
                except (ValueError, OSError):
                    file = str(file).replace("\\", "/")
            findings.append(Finding(str(p.get("message", "")), file, p.get("line"), p.get("column"),
                                    severity=str(p.get("severity", "error")), code=p.get("code"), fix=p.get("fix")))
        elif event.get("type") == "target.failed":
            other.append(str(event.get("payload", {}).get("error", "")))
    return findings, other


class BuildCheck(Check):
    name = "build"
    level = "rapide"
    description = "The project builds (incrementally, so this is fast when little changed)."

    def run(self, ctx: CheckContext) -> CheckResult:
        args = ["build", "--output", "jsonl"]
        if ctx.platform:
            args += ["--platform", ctx.platform]
        result = charpente(ctx, args)
        findings, other = findings_from_jsonl(result.stdout, ctx.root)
        if result.returncode == 0:
            return CheckResult(self.name, PASSED, findings=[f for f in findings if f.severity != "error"],
                               message="built")
        errors = [f for f in findings if f.severity == "error"]
        if not errors:
            tail = (result.stderr or "\n".join(other) or result.output).strip().splitlines()
            errors = [Finding(tail[-1] if tail else "the build failed", severity="error", code="build")]
        return self.failed(errors, "the build failed")


class TestsCheck(Check):
    name = "tests"
    level = "standard"
    description = "Unit tests pass; a test that fails and then passes on retry is reported as flaky."

    def run(self, ctx: CheckContext) -> CheckResult:
        result = charpente(ctx, ["test", "--retries", str(int(ctx.option("retries", 1)))])
        out = result.output
        if "No test targets" in out:
            return self.skipped("no test targets (declare one with Kind.TEST)")
        flaky = [Finding(f"test target {name!r} is flaky: it failed, then passed on retry", severity="warning",
                         code="flaky-test", fix="find the race or the dependency on time/order/environment")
                 for name in re.findall(r"\[FLAKY\] (\S+)", out)]
        if result.returncode == 0:
            return CheckResult(self.name, PASSED, findings=flaky,
                               message="tests passed" + (f" ({len(flaky)} flaky)" if flaky else ""))
        failures = [Finding(f"test target {name!r} failed" + (f" (exit code {code})" if code else ""), severity="error",
                            code="test-failed")
                    for name, code in re.findall(r"\[FAIL\] (\S+)(?: \(exit code (\d+)\))?", out)]
        failures += [Finding(f"test target {name!r} did not build: {msg.strip()[:200]}", severity="error", code="build")
                     for name, msg in re.findall(r"\[BUILD FAILED\] (\S+): (.*)", out)]
        if not failures:
            failures = [Finding((out.splitlines() or ["tests failed"])[-1], severity="error", code="test-failed")]
        return self.failed(failures + flaky, f"{len(failures)} test problem(s)")


def _compile_commands(ctx: CheckContext) -> Optional[List[Dict[str, Any]]]:
    path = ctx.root / "build" / "compile_commands.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return data if isinstance(data, list) else None


class WarningsCheck(Check):
    name = "warnings"
    level = "standard"
    per_file = True
    description = "Changed sources compile without warnings (warnings are errors here, only for what you touched)."

    def run(self, ctx: CheckContext) -> CheckResult:
        database = _compile_commands(ctx)
        if database is None:
            return self.skipped("no build/compile_commands.json (the build check produces it)")
        wanted = {str(p.resolve()) for p in ctx.selected(SOURCE_SUFFIXES)}
        flags = list(ctx.option("flags", ["-Wall", "-Wextra"]))
        findings: List[Finding] = []
        checked = 0
        for entry in database:
            if str(Path(entry["file"]).resolve()) not in wanted:
                continue
            argv = _syntax_only(list(entry.get("arguments") or shlex.split(entry.get("command", ""))), flags)
            if argv is None:
                return self.skipped("MSVC-style command lines are not supported by this check yet")
            checked += 1
            result = ctx.run(argv, cwd=entry.get("directory") or str(ctx.root), timeout=600)
            for d in diagnostics.parse_output(result.output):
                if d.severity in ("warning", "error"):
                    findings.append(Finding(d.message, ctx.rel(Path(d.file)) if d.file else None, d.line, d.column,
                                            severity="error", code=d.code or "warning",
                                            fix="fix the warning (it is an error in this gate)"))
        if findings:
            return self.failed(findings, f"{len(findings)} warning(s) in changed code")
        return self.passed(f"{checked} file(s) compiled with {' '.join(flags)} -Werror")


def _syntax_only(argv: List[str], flags: List[str]) -> Optional[List[str]]:
    """The build's compile command turned into a warnings-as-errors syntax check (no object, no depfile)."""
    if not argv or argv[0].lower().endswith(("cl", "cl.exe", "clang-cl", "clang-cl.exe")) or any(a.startswith("/Fo") for a in argv):
        return None
    out: List[str] = []
    skip = 0
    for arg in argv:
        if skip:
            skip -= 1
            continue
        if arg in ("-c",):
            continue
        if arg in ("-o", "-MF", "-MT", "-MQ"):
            skip = 1
            continue
        if arg in ("-MMD", "-MD", "-MP", "-M", "-MM"):
            continue
        out.append(arg)
    return [*out, "-fsyntax-only", *flags, "-Werror"]


class TidyCheck(Check):
    name = "clang-tidy"
    level = "standard"
    per_file = True
    description = "clang-tidy finds bugs and bad habits in C/C++ (uses build/compile_commands.json)."

    def run(self, ctx: CheckContext) -> CheckResult:
        exe = ctx.which(str(ctx.option("tool", "clang-tidy")))
        if not exe:
            return self.skipped("clang-tidy not found (install LLVM to enable this check)")
        if _compile_commands(ctx) is None:
            return self.skipped("no build/compile_commands.json (the build check produces it)")
        files = ctx.selected(SOURCE_SUFFIXES)
        if not files:
            return self.passed("no C/C++ sources")
        base = [exe, "-p", str(ctx.root / "build"), "--quiet"]
        if ctx.option("checks"):
            base.append(f"--checks={ctx.option('checks')}")
        if ctx.option("warnings_as_errors", True):
            base.append("--warnings-as-errors=*")
        if ctx.fix:
            base.append("--fix")
        findings: List[Finding] = []
        for path in files:
            result = ctx.run([*base, str(path)], cwd=str(ctx.root), timeout=900)
            for d in diagnostics.parse_output(result.output):
                if d.severity in ("error", "warning") and d.file:
                    findings.append(Finding(d.message, ctx.rel(Path(d.file)), d.line, d.column, severity="error",
                                            code=d.code, fix="`charpente check --fix` applies clang-tidy's safe fixes"))
        return self.failed(findings, f"{len(findings)} clang-tidy finding(s)") if findings else self.passed()


class CppcheckCheck(Check):
    name = "cppcheck"
    level = "standard"
    description = "cppcheck's static analysis of the whole project."

    def run(self, ctx: CheckContext) -> CheckResult:
        exe = ctx.which(str(ctx.option("tool", "cppcheck")))
        if not exe:
            return self.skipped("cppcheck not found (install it to enable this check)")
        database = ctx.root / "build" / "compile_commands.json"
        if not database.is_file():
            return self.skipped("no build/compile_commands.json (the build check produces it)")
        result = ctx.run([exe, f"--project={database}", "--enable=warning,performance,portability", "--inline-suppr",
                          "--error-exitcode=1", "--quiet", "--template={file}:{line}:{column}: {severity}: {message} [{id}]"],
                         cwd=str(ctx.root), timeout=1800)
        findings: List[Finding] = []
        for d in diagnostics.parse_output(result.output):
            if d.severity in ("error", "warning") and d.file:
                findings.append(Finding(d.message, ctx.rel(Path(d.file)), d.line, d.column, severity="error", code=d.code))
        if findings or result.returncode != 0:
            return self.failed(findings or [Finding(result.output.splitlines()[-1] if result.output else "cppcheck failed")],
                               f"{len(findings)} cppcheck finding(s)")
        return self.passed()


class SanitizersCheck(Check):
    name = "sanitizers"
    level = "strict"
    description = "Tests run under AddressSanitizer and UndefinedBehaviorSanitizer (where the toolchain supports them)."

    def run(self, ctx: CheckContext) -> CheckResult:
        kinds = ",".join(ctx.option("kinds", ["address", "undefined"]))
        result = charpente(ctx, ["test", "--sanitize", kinds])
        out = result.output
        if "CH8011" in out:
            reason = next((line.strip() for line in out.splitlines() if "cannot build with" in line), "not supported")
            return self.skipped(reason.replace("charpente: [CH8011] ", ""))
        if "No test targets" in out:
            return self.skipped("no test targets")
        if result.returncode == 0:
            return self.passed(f"tests clean under -fsanitize={kinds}")
        summary = re.findall(r"(?:ERROR|SUMMARY): (?:Address|Undefined)Sanitizer[^\n]*|runtime error: [^\n]*", out)
        findings = [Finding(text.strip()[:300], severity="error", code="sanitizer") for text in summary[:10]] or [
            Finding((out.splitlines() or ["tests failed under sanitizers"])[-1], severity="error", code="sanitizer")]
        return self.failed(findings, "the tests failed under sanitizers")


GCOV_FILE = re.compile(r"^File '(?P<file>.+)'$")
GCOV_LINES = re.compile(r"^Lines executed:(?P<pct>[\d.]+)% of (?P<n>\d+)$")


def parse_gcov(text: str) -> Dict[str, Tuple[int, int]]:
    """`gcov -n` output -> {file: (executed lines, total lines)} (a file seen twice keeps its best run)."""
    result: Dict[str, Tuple[int, int]] = {}
    current: Optional[str] = None
    for line in text.splitlines():
        m = GCOV_FILE.match(line.strip())
        if m:
            current = m.group("file").replace("\\", "/")
            continue
        m = GCOV_LINES.match(line.strip())
        if m and current is not None:
            total = int(m.group("n"))
            executed = round(float(m.group("pct")) * total / 100)
            previous = result.get(current)
            result[current] = (max(executed, previous[0]) if previous else executed, total)
            current = None
    return result


class CoverageCheck(Check):
    name = "coverage"
    level = "strict"
    description = "Line coverage of the project's own sources reaches the configured minimum."

    def run(self, ctx: CheckContext) -> CheckResult:
        gcov = ctx.which(str(ctx.option("tool", "gcov")))
        if not gcov:
            return self.skipped("gcov not found (it ships with GCC; use llvm-cov gcov with Clang)")
        result = charpente(ctx, ["test", "--coverage"])
        out = result.output
        if "CH8011" in out:
            return self.skipped("this toolchain cannot build with coverage instrumentation")
        if "No test targets" in out:
            return self.skipped("no test targets")
        if result.returncode != 0:
            return self.failed([Finding("the tests failed while measuring coverage", severity="error", code="tests")],
                               "tests failed")
        merged: Dict[str, Tuple[int, int]] = {}
        root = ctx.root.resolve().as_posix().lower()
        exclude = list(ctx.option("exclude", ["tests/*", "test/*", "*_test.*", "*/test_*"]))
        from .files import matches_any

        gcda_files = [g for d in sorted((ctx.root / "build").glob("*-cov")) for g in sorted(d.rglob("*.gcda"))]
        for gcda in gcda_files:
            report = ctx.run([gcov, "-n", str(gcda)], cwd=str(gcda.parent), timeout=300)
            for file, (executed, total) in parse_gcov(report.output).items():
                low = file.lower()
                if not low.startswith(root):
                    continue                                    # system headers, packages
                relative = file[len(root) + 1:]
                if relative.startswith("build/") or matches_any(relative, exclude):
                    continue
                previous = merged.get(relative)
                merged[relative] = (max(executed, previous[0]) if previous else executed, total)
        total_lines = sum(t for _, t in merged.values())
        covered = sum(e for e, _ in merged.values())
        if not total_lines:
            return self.skipped("no coverage data for the project's sources")
        percent = covered * 100.0 / total_lines
        minimum = float(ctx.option("minimum", 70))
        message = f"{percent:.1f}% of {total_lines} lines (minimum {minimum:g}%)"
        if percent + 1e-9 < minimum:
            worst = sorted(merged.items(), key=lambda item: item[1][0] / max(item[1][1], 1))[:5]
            findings = [Finding(f"only {e}/{t} lines covered", f, severity="error", code="coverage") for f, (e, t) in worst]
            return self.failed(findings, message)
        return self.passed(message)


class PlatformsCheck(Check):
    name = "platforms"
    level = "strict"
    description = "The project builds for every platform it declares (those this machine has a toolchain for)."

    def run(self, ctx: CheckContext) -> CheckResult:
        from .. import cross, platforms, toolchains
        from ..platform import host_os

        wanted = list(ctx.option("platforms", []))
        if not wanted:
            return self.skipped("no platforms listed under [checks.platforms] platforms = [...]")
        try:
            host = platforms.host().name
        except Exception:
            host = ""
        detected = toolchains.detect(host_os())
        findings: List[Finding] = []
        built: List[str] = []
        skipped: List[str] = []
        for name in wanted:
            try:
                platform = platforms.get(name)
            except Exception as exc:
                findings.append(Finding(str(exc), severity="error", code="platform"))
                continue
            if name != host and not any(cross.can_target(t, platform) for t in detected):
                skipped.append(name)
                continue
            result = charpente(ctx, ["build", "--platform", name, "--output", "jsonl"])
            if result.returncode == 0:
                built.append(name)
            else:
                errors, other = findings_from_jsonl(result.stdout, ctx.root)
                findings += [Finding(f"[{name}] {f.message}", f.file, f.line, f.column, f.severity, f.code)
                             for f in errors if f.severity == "error"] or [
                    Finding(f"[{name}] the build failed", severity="error", code="build")]
        if findings:
            return self.failed(findings, f"{len(findings)} problem(s) on other platforms")
        if not built:
            return self.skipped("no toolchain here for: " + ", ".join(skipped))
        note = f"built {', '.join(built)}" + (f"; skipped (no toolchain): {', '.join(skipped)}" if skipped else "")
        return CheckResult(self.name, PASSED, message=note)


__all__ = ["BuildCheck", "TestsCheck", "WarningsCheck", "TidyCheck", "CppcheckCheck", "SanitizersCheck",
           "CoverageCheck", "PlatformsCheck", "parse_gcov", "findings_from_jsonl", "FAILED", "SKIPPED", "CPP_SUFFIXES"]
