"""Checks that only read files: secrets, file size, the DSL lint, formatting."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import List, Optional, Pattern, Tuple

from ..lint import lint_source
from ..workspace_finder import find_workspace_file
from .files import CPP_SUFFIXES, matches_any
from .model import FIXED, PASSED, Check, CheckContext, CheckResult, Finding

ALLOW_MARKER = "charpente:allow-secret"

# (label, regex). Precise formats first: they are far less likely to be false positives than the generic rule.
SECRET_PATTERNS: List[Tuple[str, Pattern[str]]] = [
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Stripe live key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{20,}\b")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----")),
    ("JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("Anthropic/OpenAI style API key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{32,}\b")),
]
_ASSIGNMENT = re.compile(
    r"""(?ix)\b(?P<name>[\w.-]*(?:password|passwd|secret|token|api[_-]?key|apikey|private[_-]?key)[\w.-]*)\s*
        [:=]\s*["'](?P<value>[^"'\s]{10,})["']""")
_PLACEHOLDER = re.compile(r"(?i)^(?:x+|\*+|<.*>|\$\{.*\}|\{\{.*\}\}|%\(.*\)s|changeme|example|your[-_ ].*|.*placeholder.*|"
                          r"todo|none|null|test.*|dummy.*|foo.*|bar.*|password|secret)$")


def entropy(text: str) -> float:
    """Shannon entropy in bits per character: random secrets are high, words and identifiers low."""
    if not text:
        return 0.0
    counts = {c: text.count(c) for c in set(text)}
    return -sum(n / len(text) * math.log2(n / len(text)) for n in counts.values())


def redact(value: str) -> str:
    return value[:4] + "*" * min(8, max(0, len(value) - 4))


def scan_text(text: str) -> List[Tuple[int, str, str]]:
    """(line number, what it looks like, redacted excerpt) for each probable secret in `text`."""
    hits: List[Tuple[int, str, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if ALLOW_MARKER in line or len(line) > 2000:
            continue
        found_specific = False
        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(line)
            if match:
                hits.append((number, label, redact(match.group(0))))
                found_specific = True
                break
        if found_specific:
            continue
        match = _ASSIGNMENT.search(line)
        if match:
            value = match.group("value")
            if not _PLACEHOLDER.match(value) and entropy(value) >= 3.3:
                hits.append((number, f"hard-coded {match.group('name')}", redact(value)))
    return hits


class SecretsCheck(Check):
    name = "secrets"
    level = "rapide"
    per_file = True
    description = "No keys, tokens or passwords in the files (fix: move them to the environment or a vault)."

    def run(self, ctx: CheckContext) -> CheckResult:
        allow = list(ctx.option("allow", []))
        limit = int(ctx.option("max_kb", 512)) * 1024
        findings: List[Finding] = []
        scanned = 0
        from .files import list_files

        for path in (ctx.files if ctx.files is not None else list_files(ctx.root)):
            relative = ctx.rel(path)
            if matches_any(relative, allow):
                continue
            try:
                if path.stat().st_size > limit:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            if b"\x00" in data[:4096]:
                continue                                   # binary
            scanned += 1
            for line, label, excerpt in scan_text(data.decode("utf-8", "replace")):
                findings.append(Finding(f"possible secret ({label}): {excerpt}", relative, line, severity="error",
                                        code="secret",
                                        fix=f"remove it and rotate the credential; if it is a test value, add `{ALLOW_MARKER}` "
                                            "to the line or list the file under [checks.secrets] allow"))
        if findings:
            return self.failed(findings, f"{len(findings)} possible secret(s)")
        return self.passed(f"{scanned} file(s) scanned")


class FileSizeCheck(Check):
    name = "file-size"
    level = "rapide"
    per_file = True
    description = "No accidental huge files (binaries, dumps) in the repository."

    def run(self, ctx: CheckContext) -> CheckResult:
        from .files import list_files

        limit = int(ctx.option("max_kb", 1024)) * 1024
        allow = list(ctx.option("allow", []))
        findings: List[Finding] = []
        for path in (ctx.files if ctx.files is not None else list_files(ctx.root)):
            relative = ctx.rel(path)
            if matches_any(relative, allow):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > limit:
                findings.append(Finding(f"{size // 1024} KB exceeds the {limit // 1024} KB limit", relative,
                                        severity="error", code="file-size",
                                        fix="keep large files out of Git (Git LFS, a release asset), or raise "
                                            "[checks.file-size] max_kb / add it to allow"))
        return self.failed(findings, f"{len(findings)} file(s) too large") if findings else self.passed()


class DslLintCheck(Check):
    name = "dsl-lint"
    level = "rapide"
    description = "The .charpente file is analysed (never run) for likely mistakes."

    def run(self, ctx: CheckContext) -> CheckResult:
        try:
            path = find_workspace_file(start_dir=ctx.root)
        except Exception:
            return self.skipped("no workspace file")
        if path.suffix.lower() == ".toml":
            return self.passed("charpente.toml is validated when loaded")
        issues = lint_source(path.read_text(encoding="utf-8-sig"))
        findings = [Finding(i.message, ctx.rel(path), i.line, severity="error" if i.severity == "error" else "warning",
                            code=i.code) for i in issues]
        strict = bool(ctx.option("warnings_are_errors", False))
        bad = [f for f in findings if f.severity == "error" or strict]
        if bad:
            return self.failed(findings, f"{len(bad)} problem(s) in {path.name}")
        return CheckResult(self.name, PASSED, findings=findings, message=f"{path.name} is clean")


class FormatCheck(Check):
    name = "format"
    level = "rapide"
    per_file = True
    description = "C/C++ files follow the project's clang-format style (`--fix` rewrites them)."

    def run(self, ctx: CheckContext) -> CheckResult:
        tool = ctx.option("tool", "clang-format")
        exe = ctx.which(str(tool))
        if not exe:
            return self.skipped(f"{tool} not found (install LLVM/clang-format to enable this check)")
        files = ctx.selected(CPP_SUFFIXES)
        if not files:
            return self.passed("no C/C++ files")
        style = str(ctx.option("style", "file"))
        base = [exe, f"--style={style}"]
        if ctx.fix:
            fixed_any = self._fix(ctx, base, files)
            if fixed_any:
                return CheckResult(self.name, FIXED, message=f"reformatted {fixed_any} file(s)")
            return self.passed("already formatted")
        findings: List[Finding] = []
        for path in files:
            result = ctx.run([*base, "--dry-run", "-Werror", str(path)], timeout=120)
            if result.returncode == 0:
                continue
            located = re.findall(r"^(?P<file>.+?):(?P<line>\d+):(?P<col>\d+): (?:error|warning): (?P<msg>.*)$",
                                 result.output, re.M)
            if located:
                for _file, line, col, msg in located[:20]:
                    findings.append(Finding(msg, ctx.rel(path), int(line), int(col), code="format",
                                            fix="run `charpente check --fix`"))
            else:
                findings.append(Finding(result.output.splitlines()[0] if result.output else "not formatted",
                                        ctx.rel(path), code="format", fix="run `charpente check --fix`"))
        return self.failed(findings, f"{len({f.file for f in findings})} file(s) not formatted") if findings else self.passed()

    @staticmethod
    def _fix(ctx: CheckContext, base: List[str], files: List[Path]) -> int:
        changed = 0
        for path in files:
            before: Optional[bytes] = path.read_bytes()
            ctx.run([*base, "-i", str(path)], timeout=120)
            if path.read_bytes() != before:
                changed += 1
        return changed
