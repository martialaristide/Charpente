"""`charpente migrate`: rewrite v0.1.0 idioms into their DSL v2 equivalents.

Everything written for v0.1.0 keeps working unchanged; migration is optional.
It is deliberately conservative: it only rewrites a pattern it can prove is
equivalent, and shows a diff first.

Rewrites:
  t.depends_on(["core"])  +  t.links(["core"])   ->   t.uses("core")
     (names present in both; names in only one of them stay where they are)
"""
from __future__ import annotations

import ast
import difflib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class MigrationResult:
    new_source: str
    changes: List[str]

    @property
    def changed(self) -> bool:
        return bool(self.changes)

    def diff(self, path: str = "workspace.charpente", old: str = "") -> str:
        return "".join(difflib.unified_diff(old.splitlines(True), self.new_source.splitlines(True),
                                            fromfile=path, tofile=path + " (migrated)"))


def _strings(node: ast.AST) -> Optional[List[str]]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)) and all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                                                       for e in node.elts):
        return [e.value for e in node.elts]  # type: ignore[attr-defined]
    return None


def _quote(names: List[str]) -> str:
    return ", ".join(repr(n).replace("'", '"') if "'" not in n else repr(n) for n in names)


def _line(indent: str, var: str, method: str, names: List[str]) -> str:
    return f"{indent}{var}.{method}([{_quote(names)}])\n"


def migrate_source(source: str) -> MigrationResult:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return MigrationResult(source, [])
    lines = source.splitlines(keepends=True)
    edits: List[Tuple[int, int, str]] = []          # (start line, end line, replacement) 1-based inclusive
    changes: List[str] = []

    for block in [n for n in ast.walk(tree) if isinstance(n, ast.With)]:
        var: Optional[str] = None
        target_name = ""
        for item in block.items:
            call = item.context_expr
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "Target"
                    and isinstance(item.optional_vars, ast.Name)):
                var = item.optional_vars.id
                if call.args and isinstance(call.args[0], ast.Constant):
                    target_name = str(call.args[0].value)
        if var is None:
            continue

        found: Dict[str, List[ast.Expr]] = {"depends_on": [], "links": []}
        for stmt in block.body:
            if (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
                    and isinstance(stmt.value.func, ast.Attribute) and isinstance(stmt.value.func.value, ast.Name)
                    and stmt.value.func.value.id == var and stmt.value.func.attr in found and len(stmt.value.args) == 1
                    and not stmt.value.keywords):
                found[stmt.value.func.attr].append(stmt)
        if len(found["depends_on"]) != 1 or len(found["links"]) != 1:
            continue
        dep_stmt, link_stmt = found["depends_on"][0], found["links"][0]
        deps, links = _strings(dep_stmt.value.args[0]), _strings(link_stmt.value.args[0])  # type: ignore[attr-defined]
        if deps is None or links is None:
            continue
        both = [n for n in deps if n in links]
        if not both:
            continue
        rest_deps = [n for n in deps if n not in both]
        rest_links = [n for n in links if n not in both]
        indent = " " * dep_stmt.col_offset

        first, second = sorted([dep_stmt, link_stmt], key=lambda s: s.lineno)
        replacement_first = f"{indent}{var}.uses({_quote(both)})\n"
        if rest_deps:
            replacement_first += _line(indent, var, "depends_on", rest_deps)
        edits.append((first.lineno, first.end_lineno or first.lineno, replacement_first))
        edits.append((second.lineno, second.end_lineno or second.lineno,
                      _line(indent, var, "links", rest_links) if rest_links else ""))
        changes.append(f"target {target_name or var}: depends_on + links of {', '.join(both)} -> uses({_quote(both)})")

    for start, end, text in sorted(edits, reverse=True):
        lines[start - 1:end] = [text] if text else []
    return MigrationResult("".join(lines), changes)
