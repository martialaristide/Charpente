"""Charpente declares support for Python 3.9 (pyproject.toml, CI matrix), but the development machine runs a newer Python: a few APIs that only exist from 3.10 slipped in and showed up
only in CI as TypeError -> exit code 70. This scans the sources for the ones that are easy to miss."""
import ast
from pathlib import Path

import pytest

from charpente import fsutil

ROOT = Path(__file__).resolve().parents[1] / "charpente"
SKIPPED = ("templates_data", "kit_sources")


def sources():
    for path in sorted(ROOT.rglob("*.py")):
        if not any(part in SKIPPED for part in path.parts):
            yield path


@pytest.mark.parametrize("path", list(sources()), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_api_newer_than_python_39(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 9))          # syntax: match statements, parenthesised context managers...
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", getattr(node.func, "id", ""))
        keywords = {k.arg for k in node.keywords}
        owner = getattr(getattr(node.func, "value", None), "id", "")
        if name in ("write_text", "read_text") and "newline" in keywords and owner != "fsutil":
            problems.append(f"line {node.lineno}: {name}(newline=...) needs Python 3.10 (use charpente.fsutil.write_text)")
        if name == "zip" and "strict" in keywords:
            problems.append(f"line {node.lineno}: zip(strict=...) needs Python 3.10")
        if name == "dataclass" and keywords & {"slots", "kw_only", "match_args"}:
            problems.append(f"line {node.lineno}: dataclass({', '.join(sorted(keywords & {'slots', 'kw_only', 'match_args'}))}) needs Python 3.10")
        if name in ("pairwise", "aiter", "anext"):
            problems.append(f"line {node.lineno}: {name}() needs Python 3.10")
    assert not problems, "\n".join(problems)


def test_write_text_writes_exactly_what_it_is_given(tmp_path):
    target = tmp_path / "f.txt"
    assert fsutil.write_text(target, "a\r\nb\nc", newline="") == 6
    assert target.read_bytes() == b"a\r\nb\nc"                                           # no translation of line endings
    fsutil.write_text(target, "x\ny\n", newline="\n")
    assert target.read_bytes() == b"x\ny\n"
    fsutil.write_text(str(target), "é", encoding="utf-8", newline="")                  # a plain string path works too
    assert target.read_bytes() == "é".encode("utf-8")
