"""The action graph: which action must wait for which, in what order to run
them, and which chain of actions bounds the total build time.

Edges come from two places: an action that reads a file another action
writes, and explicit `after` ordering edges. Everything here is pure.
"""
from __future__ import annotations

import os
from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Set, Tuple, Union

from ..errors import ChValueError
from .actions import Action


def path_key(path: Union[str, Path]) -> str:
    """Canonical dictionary key for a path (absolute, case-folded on Windows)."""
    return os.path.normcase(os.path.abspath(str(path)))


class ActionGraph:
    def __init__(self, actions: Iterable[Action]) -> None:
        self.actions: Dict[str, Action] = {}
        self._producer: Dict[str, str] = {}
        for action in actions:
            if action.id in self.actions:
                raise ChValueError("CH3013", action=action.id)
            self.actions[action.id] = action
            for out in action.outputs:
                key = path_key(out)
                if key in self._producer:
                    raise ChValueError("CH3010", path=str(out), first=self._producer[key], second=action.id)
                self._producer[key] = action.id

        self.deps: Dict[str, Set[str]] = {aid: set() for aid in self.actions}
        self.dependents: Dict[str, Set[str]] = {aid: set() for aid in self.actions}
        for action in self.actions.values():
            for inp in action.inputs:
                producer = self._producer.get(path_key(inp))
                if producer is not None and producer != action.id:
                    self._link(producer, action.id)
            for before in action.after:
                if before not in self.actions:
                    raise ChValueError("CH3011", action=action.id, missing=before)
                if before != action.id:
                    self._link(before, action.id)
        self._index = {aid: i for i, aid in enumerate(self.actions)}
        self._order = self._toposort()

    # ------------------------------------------------------------- structure
    def _link(self, before: str, after: str) -> None:
        self.deps[after].add(before)
        self.dependents[before].add(after)

    def producer_of(self, path: Union[str, Path]) -> Optional[str]:
        return self._producer.get(path_key(path))

    def __len__(self) -> int:
        return len(self.actions)

    def __contains__(self, action_id: object) -> bool:
        return action_id in self.actions

    def _toposort(self) -> List[str]:
        """Kahn's algorithm, keeping insertion order among ready nodes so the
        result is deterministic. Raises CH3012 (naming one cycle) if none exists."""
        indegree = {aid: len(d) for aid, d in self.deps.items()}
        ready = deque(aid for aid in self.actions if indegree[aid] == 0)
        order: List[str] = []
        while ready:
            aid = ready.popleft()
            order.append(aid)
            for nxt in sorted(self.dependents[aid], key=self._index.__getitem__):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    ready.append(nxt)
        if len(order) != len(self.actions):
            stuck = [aid for aid, d in indegree.items() if d > 0]
            raise ChValueError("CH3012", cycle=" -> ".join(self._find_cycle(stuck)))
        return order

    def _find_cycle(self, candidates: List[str]) -> List[str]:
        remaining = set(candidates)
        start = candidates[0]
        path: List[str] = []
        seen: Dict[str, int] = {}
        node = start
        while node not in seen:
            seen[node] = len(path)
            path.append(node)
            node = next((d for d in sorted(self.deps[node]) if d in remaining), node)
        return list(reversed(path[seen[node]:] + [node]))

    def topological_order(self) -> List[str]:
        return list(self._order)

    def closure(self, roots: Iterable[str]) -> Set[str]:
        """`roots` plus everything they (transitively) depend on."""
        needed: Set[str] = set()
        stack = [r for r in roots if r in self.actions]
        while stack:
            aid = stack.pop()
            if aid in needed:
                continue
            needed.add(aid)
            stack.extend(self.deps[aid])
        return needed

    def descendants(self, roots: Iterable[str]) -> Set[str]:
        """Everything that (transitively) depends on any of `roots` (excluding them)."""
        found: Set[str] = set()
        stack: List[str] = []
        for r in roots:
            stack.extend(self.dependents.get(r, ()))
        while stack:
            aid = stack.pop()
            if aid in found:
                continue
            found.add(aid)
            stack.extend(self.dependents[aid])
        return found

    def subgraph(self, ids: Iterable[str]) -> "ActionGraph":
        keep = set(ids)
        chosen = [a for aid, a in self.actions.items() if aid in keep]
        # ordering edges to actions outside the subset are dropped: those actions are not being run
        clipped = [
            a if all(b in keep for b in a.after) else _without_after(a, keep)
            for a in chosen
        ]
        return ActionGraph(clipped)

    # ---------------------------------------------------------- critical path
    def priorities(self, durations: Optional[Mapping[str, float]] = None,
                   default: float = 1.0) -> Dict[str, float]:
        """For each action, the length of the longest chain that starts at it
        (its own weight plus its slowest dependent chain). Running the action
        with the highest number first shortens the whole build the most."""
        weight = {aid: float(durations.get(aid, default)) if durations else default for aid in self.actions}
        best: Dict[str, float] = {}
        for aid in reversed(self._order):
            tail = max((best[d] for d in self.dependents[aid]), default=0.0)
            best[aid] = weight[aid] + tail
        return best

    def critical_path(self, durations: Optional[Mapping[str, float]] = None,
                      default: float = 1.0) -> Tuple[float, List[str]]:
        """(total length, action ids along the longest chain)."""
        if not self.actions:
            return 0.0, []
        best = self.priorities(durations, default)
        current = max(best, key=lambda a: (best[a], a))
        total = best[current]
        chain = [current]
        while self.dependents[current]:
            current = max(self.dependents[current], key=lambda a: (best[a], a))
            chain.append(current)
        return total, chain


def _without_after(action: Action, keep: Set[str]) -> Action:
    from dataclasses import replace

    return replace(action, after=tuple(b for b in action.after if b in keep))
