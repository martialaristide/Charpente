"""Static checks of a `.charpente` file -- without executing it.

The file is parsed with `ast` and looked at, never run, so this is safe to do
before the trust prompt and on code you have not read. It only reports what it
can be sure of from literal values: a name computed at run time is skipped rather
than guessed at. It complements, and never replaces, the trust check.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .dsl import api as _api
from .dsl.model import Kind

_LIBRARY_KIND_NAMES = {"STATIC_LIBRARY", "SHARED_LIBRARY", "PLUGIN"}
_MAGIC_DOUBLE_STAR = re.compile(r"[^/\\]\*\*|\*\*[^/\\]")


def _public_methods(cls: type) -> Set[str]:
    return {n for n, v in vars(cls).items() if callable(v) and not n.startswith("_")}


_TARGET_METHODS = _public_methods(_api.Target)
_WORKSPACE_METHODS = _public_methods(_api.Workspace)
_RULE_METHODS = _public_methods(_api.Rule)
_CONDITION_METHODS = _public_methods(_api._Conditional) | {"android", "harmony", "ios", "wasm", "web", "xr",
                                                           "embedded", "quest"}
_KIND_NAMES = {k.name for k in Kind}


@dataclass(frozen=True)
class LintIssue:
    code: str
    severity: str            # "error" | "warning"
    message: str
    line: int = 0


@dataclass
class _TargetInfo:
    name: Optional[str]
    line: int
    kind: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    uses: List[str] = field(default_factory=list)
    has_sources: bool = False
    dynamic_edges: bool = False


def _kit_members(name: str) -> List[str]:
    """Package names of a bundled kit (empty for an unknown name: `ws.kit` itself reports it when loaded)."""
    try:
        from .pkg import kits

        return [spec.partition("@")[0] for spec in kits.load_all()[name].requires]
    except Exception:
        return []


def _literal_strings(node: ast.AST) -> Optional[List[str]]:
    """The strings in a literal (`"a"`, `["a", "b"]`, `("a",)`), or None if not fully literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        out: List[str] = []
        for element in node.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                out.append(element.value)
            else:
                return None
        return out
    return None


def _call_name(node: ast.AST) -> Optional[str]:
    return node.id if isinstance(node, ast.Name) else None


def lint_source(source: str) -> List[LintIssue]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [LintIssue("CH1101", "error", f"syntax error: {exc.msg}", exc.lineno or 0)]

    issues: List[LintIssue] = []
    targets: List[_TargetInfo] = []
    rule_names: Set[str] = set()
    requires: Set[str] = set()
    variables: Dict[str, str] = {}          # variable name -> "target" | "workspace" | "rule" | "condition"
    infos: Dict[str, _TargetInfo] = {}      # target variable -> info
    depth = {"workspace": 0}

    def note_pattern(pattern: str, line: int) -> None:
        if _MAGIC_DOUBLE_STAR.search(pattern):
            issues.append(LintIssue("CH1102", "error", f"invalid pattern {pattern!r}: '**' must be a whole path "
                                    f"component (write src/**/*.cpp)", line))
        elif re.match(r"^([A-Za-z]:[\\/]|/)", pattern):
            issues.append(LintIssue("CH1102", "warning", f"pattern {pattern!r} is absolute; patterns are relative to "
                                    f"the .charpente file", line))

    class Visitor(ast.NodeVisitor):
        def visit_With(self, node: ast.With) -> None:
            opened: List[str] = []
            for item in node.items:
                call = item.context_expr
                if not isinstance(call, ast.Call):
                    continue
                kind = None
                func = _call_name(call.func)
                if func == "Workspace":
                    kind = "workspace"
                    depth["workspace"] += 1
                elif func == "Target":
                    kind = "target"
                    if depth["workspace"] == 0:
                        issues.append(LintIssue("CH1108", "error", "Target(...) outside of `with Workspace(...)`",
                                                node.lineno))
                    name = None
                    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                        name = call.args[0].value
                    info = _TargetInfo(name=name, line=node.lineno)
                    targets.append(info)
                    if isinstance(item.optional_vars, ast.Name):
                        infos[item.optional_vars.id] = info
                elif func == "Rule":
                    kind = "rule"
                    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                        rule_names.add(call.args[0].value)
                elif isinstance(call.func, ast.Attribute) and call.func.attr in ("on_config", "on_platform",
                                                                                 "on_toolchain", "when"):
                    kind = "condition"
                if kind and isinstance(item.optional_vars, ast.Name):
                    variables[item.optional_vars.id] = kind
                    opened.append(item.optional_vars.id)
                elif kind == "workspace":
                    opened.append("")
            self.generic_visit(node)
            for item in node.items:
                if isinstance(item.context_expr, ast.Call) and _call_name(item.context_expr.func) == "Workspace":
                    depth["workspace"] -= 1

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                var, method = func.value.id, func.attr
                kind = variables.get(var)
                valid = {"target": _TARGET_METHODS, "workspace": _WORKSPACE_METHODS, "rule": _RULE_METHODS,
                         "condition": _CONDITION_METHODS}.get(kind or "")
                if valid is not None and method not in valid and not method.startswith("_"):
                    near = sorted(m for m in valid if m.startswith(method[:3]))[:4]
                    hint = f" Did you mean {', '.join(near)}?" if near else ""
                    issues.append(LintIssue("CH1106", "error", f"{var}.{method}() does not exist.{hint}", node.lineno))
                info = infos.get(var)
                if info is not None:
                    self._record_target_call(info, method, node)
                if kind == "workspace" and method == "requires":
                    for arg in node.args:
                        for name in _literal_strings(arg) or []:
                            requires.add(name.partition("@")[0])
                if kind == "workspace" and method == "kit":
                    for arg in node.args:
                        for name in _literal_strings(arg) or []:
                            requires.add(name)                          # `uses("kit-core")` is valid ...
                            requires.update(_kit_members(name))         # ... and so are its members
                if method in ("sources", "exclude") and kind in ("target", "condition"):
                    for arg in node.args:
                        for pattern in _literal_strings(arg) or []:
                            note_pattern(pattern, node.lineno)
            self.generic_visit(node)

        def _record_target_call(self, info: _TargetInfo, method: str, node: ast.Call) -> None:
            collected: List[str] = []
            strings: Optional[List[str]] = collected
            for arg in node.args:
                lit = _literal_strings(arg)
                if lit is None:
                    strings = None
                    break
                collected.extend(lit)
            if method == "kind" and node.args and isinstance(node.args[0], ast.Attribute):
                info.kind = node.args[0].attr
            elif method == "sources":
                info.has_sources = True
            elif method in ("depends_on", "links", "uses", "uses_public"):
                if strings is None:
                    info.dynamic_edges = True
                elif method == "depends_on":
                    info.depends_on += strings
                elif method == "links":
                    info.links += strings
                else:
                    info.uses += strings

    Visitor().visit(tree)

    # ------------------------------------------------------------ cross-target checks
    known = {t.name: t for t in targets if t.name}
    seen: Dict[str, int] = {}
    for t in targets:
        if t.name is None:
            continue
        if t.name in seen:
            issues.append(LintIssue("CH1107", "error", f"target {t.name!r} is declared twice "
                                    f"(first at line {seen[t.name]})", t.line))
        seen.setdefault(t.name, t.line)
    all_literal = all(t.name is not None for t in targets)

    for t in targets:
        for dep in t.depends_on:
            if dep not in known and all_literal:
                issues.append(LintIssue("CH1103", "warning", f"{t.name!r} depends on {dep!r}, which is not "
                                        f"declared in this file", t.line))
            elif dep in known and known[dep].kind in _LIBRARY_KIND_NAMES and dep not in t.links \
                    and dep not in t.uses:
                issues.append(LintIssue("CH1105", "warning",
                                        f"{t.name!r} depends_on {dep!r} (a library) but does not link it: "
                                        f'depends_on only orders the build. Use uses("{dep}"), or add '
                                        f'links(["{dep}"]).', t.line))
        for used in t.uses:
            if used not in known and used not in requires and all_literal:
                issues.append(LintIssue("CH1109", "warning", f"{t.name!r} uses {used!r}, which is neither a target "
                                        f"of this file nor listed in ws.requires(...)", t.line))
        if not t.has_sources and t.kind not in ("HEADER_ONLY", None) and t.kind in _KIND_NAMES:
            issues.append(LintIssue("CH1110", "warning", f"target {t.name!r} declares no sources()", t.line))

    issues.extend(_cycles(known))
    return sorted(issues, key=lambda i: (i.line, i.code))


def _cycles(known: Dict[str, _TargetInfo]) -> List[LintIssue]:
    found: List[LintIssue] = []
    state: Dict[str, int] = {}

    def visit(name: str, trail: List[str]) -> None:
        state[name] = 1
        info = known[name]
        for dep in [*info.depends_on, *info.uses]:
            if dep not in known:
                continue
            if state.get(dep) == 1:
                cycle = " -> ".join([*trail[trail.index(dep):], name, dep]) if dep in trail else f"{name} -> {dep}"
                found.append(LintIssue("CH1104", "error", f"dependency cycle: {cycle}", info.line))
            elif state.get(dep) is None:
                visit(dep, [*trail, name])
        state[name] = 2

    for name in known:
        if state.get(name) is None:
            visit(name, [])
    return found
