"""Pure computations behind Studio's panels: the critical path of a build, per-target timing, and the DSL schema used for completion."""
from __future__ import annotations

import inspect
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


def critical_path(dependencies: Mapping[str, Sequence[str]], cost: Mapping[str, float]) -> Tuple[List[str], float]:
    """The chain of targets that bounds the build time: the dependency chain with the largest total cost.

    `dependencies[t]` are the targets `t` needs; `cost[t]` is the time `t` took itself (0 when unknown). Unknown names in a dependency list are ignored.
    Returns (chain from the first thing built to the last, total cost). Cycles are impossible in a loaded workspace; a malformed input cannot loop
    forever (a node already on the current path is not revisited).
    """
    best: Dict[str, Tuple[float, List[str]]] = {}

    def visit(name: str, path: Tuple[str, ...]) -> Tuple[float, List[str]]:
        if name in best:
            return best[name]
        head: Tuple[float, List[str]] = (0.0, [])
        for dep in dependencies.get(name, ()):
            if dep in dependencies and dep not in path:
                candidate = visit(dep, path + (name,))
                if candidate[0] > head[0] or (candidate[0] == head[0] and not head[1]):
                    head = candidate
        result = (head[0] + float(cost.get(name, 0.0)), head[1] + [name])
        best[name] = result
        return result

    winner: Tuple[float, List[str]] = (0.0, [])
    for name in sorted(dependencies):
        candidate = visit(name, ())
        if candidate[0] > winner[0] or (candidate[0] == winner[0] and not winner[1]):
            winner = candidate
    return winner[1], winner[0]


def target_costs(actions: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, float]]:
    """Per target: seconds spent per action kind and the total, from history action rows (`target`, `kind`, `duration`)."""
    totals: Dict[str, Dict[str, float]] = {}
    for row in actions:
        target = str(row.get("target") or "")
        if not target:
            continue
        entry = totals.setdefault(target, {"total": 0.0})
        seconds = float(row.get("duration") or 0.0)
        entry[str(row.get("kind") or "other")] = entry.get(str(row.get("kind") or "other"), 0.0) + seconds
        entry["total"] += seconds
    return totals


def dsl_schema(classes: Mapping[str, type], enums: Mapping[str, type]) -> Dict[str, Any]:
    """Public methods (with signature and first doc line) of the DSL classes, and the members of its enums: what an editor offers as completion."""
    described: Dict[str, List[Dict[str, str]]] = {}
    for name, cls in classes.items():
        methods = []
        for member, fn in inspect.getmembers(cls, inspect.isfunction):
            if member.startswith("_"):
                continue
            try:
                bare = inspect.signature(fn).replace(return_annotation=inspect.Signature.empty)
                signature = str(bare).replace("'", "").replace("(self, ", "(").replace("(self)", "()")
            except (TypeError, ValueError):
                signature = "(...)"
            doc = (inspect.getdoc(fn) or "").strip().splitlines()
            methods.append({"name": member, "signature": signature, "doc": doc[0] if doc else ""})
        described[name] = sorted(methods, key=lambda m: m["name"])
    members = {name: [m.name for m in cls] for name, cls in enums.items()}      # type: ignore[attr-defined]
    return {"classes": described, "enums": members}
