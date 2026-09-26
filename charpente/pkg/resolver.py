"""Dependency resolution: pick one version of every needed package so that all
constraints hold.

A small depth-first solver with backtracking. Candidates are tried highest
version first; a choice adds the constraints of that version's own dependencies;
a dead end backs up and tries the next older version. Deterministic (packages are
visited in name order), and when there is no solution the error says who asked
for what -- the information needed to fix it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from ..errors import ChError
from ..semver import Constraint, Version
from .index import RecipeIndex, RecipeRef
from .recipe import Recipe, constraint_of

MAX_STEPS = 20_000


@dataclass
class Resolved:
    recipe: Recipe
    ref: RecipeRef
    requested_by: List[str] = field(default_factory=list)


Constraints = Dict[str, List[Tuple[Constraint, str]]]


def resolve(requires: List[str], index: RecipeIndex, *, preferred: Optional[Dict[str, str]] = None,
            max_bytes: Optional[int] = None) -> Dict[str, Resolved]:
    """{name: Resolved} for `requires` and everything they need.

    `preferred` maps names to versions to try first (the lock file's choices):
    resolution stays stable across runs unless a constraint forces a change."""
    preferred = preferred or {}
    steps = 0
    recipes: Dict[Tuple[str, str], Recipe] = {}

    def recipe_for(name: str, version: str) -> Recipe:
        key = (name, version)
        if key not in recipes:
            ref = index.ref(name, version)
            assert ref is not None
            recipes[key] = index.load(ref, max_bytes=max_bytes)
        return recipes[key]

    def add(constraints: Constraints, spec: str, requester: str) -> Constraints:
        name, constraint = constraint_of(spec)
        merged = {k: list(v) for k, v in constraints.items()}
        merged.setdefault(name, []).append((constraint, requester))
        return merged

    def candidates(name: str, constraints: Constraints) -> List[str]:
        versions = index.versions(name)
        ok = [v for v in versions if all(c.matches(v) for c, _ in constraints.get(name, []))]
        ok.sort(key=Version.parse, reverse=True)
        first = preferred.get(name)
        if first in ok:
            ok.remove(first)
            ok.insert(0, first)
        return ok

    def explain(name: str, constraints: Constraints) -> ChError:
        wants = "; ".join(f"{requester} needs {name}@{c}" for c, requester in constraints.get(name, []))
        available = ", ".join(index.versions(name)) or "none found"
        if not index.versions(name):
            return ChError("CH6007", name=name, where="no recipe in any configured source")
        return ChError("CH6010", name=name, wants=wants, available=available)

    failures: List[Tuple[str, Constraints]] = []

    def solve(chosen: Dict[str, str], constraints: Constraints) -> Optional[Dict[str, str]]:
        nonlocal steps
        steps += 1
        if steps > MAX_STEPS:
            raise ChError("CH6010", name="(many)", wants="the search space is too large",
                          available="simplify the requirements")
        pending = sorted(n for n in constraints if n not in chosen)
        if not pending:
            return chosen
        name = pending[0]
        options = candidates(name, constraints)
        if not options:
            failures.append((name, constraints))
        for version in options:
            recipe = recipe_for(name, version)
            next_constraints = constraints
            for dep in recipe.dependencies:
                next_constraints = add(next_constraints, dep, f"{name}@{version}")
            # a new constraint may already contradict a package chosen earlier
            if any(not c.matches(chosen[n]) for n, lst in next_constraints.items() if n in chosen for c, _ in lst):
                continue
            result = solve({**chosen, name: version}, next_constraints)
            if result is not None:
                return result
        return None

    constraints: Constraints = {}
    for spec in requires:
        constraints = add(constraints, spec, "workspace")
    for name in constraints:
        if not index.versions(name):
            raise ChError("CH6007", name=name, where="no recipe in any configured source")
    solution = solve({}, constraints)
    if solution is None:
        if failures:
            name, at_failure = max(failures, key=lambda f: len(f[1].get(f[0], [])))
            raise explain(name, at_failure)
        raise ChError("CH6010", name="(several)", wants="the requirements contradict each other",
                      available="see `charpente pkg info` for each package's dependencies")

    requested: Dict[str, List[str]] = {}
    for name, version in solution.items():
        for dep in recipe_for(name, version).dependencies:
            requested.setdefault(constraint_of(dep)[0], []).append(f"{name}@{version}")
    direct = {constraint_of(s)[0] for s in requires}
    out: Dict[str, Resolved] = {}
    for name, version in sorted(solution.items()):
        ref = index.ref(name, version)
        assert ref is not None
        out[name] = Resolved(recipe_for(name, version), ref,
                             (["workspace"] if name in direct else []) + requested.get(name, []))
    return out


def install_order(resolved: Dict[str, Resolved]) -> List[str]:
    """Dependencies first."""
    order: List[str] = []
    seen: Set[str] = set()

    def visit(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        for dep in resolved[name].recipe.dependencies:
            visit(constraint_of(dep)[0])
        order.append(name)

    for name in sorted(resolved):
        visit(name)
    return order
