"""State consistency invariants (RL3) — structural only; semantics are engines'.

The manager enforces the *structural* constitutional invariants it can verify
without cognition:
  * placement — an object lives only in its constitutional Region (Phase 1 §2.2);
  * acyclicity — DAG relationship types form no cycle (Phase 1.5 Ch2/Ch4);
  * referential integrity — dependency/composition/supersedes targets exist.
Semantic invariants (belief coherence, confidence monotonicity) are supplied by
engines as pluggable :class:`InvariantValidator`s.
"""

from __future__ import annotations

import threading
from typing import Mapping

from .contracts import (
    DAG_EDGES,
    TYPE_REGION,
    CognitiveObject,
    InvariantValidator,
    RelationshipType,
)
from .errors import PlacementError, StateConsistencyError

_REFERENTIAL = frozenset(
    {RelationshipType.DEPENDENCY, RelationshipType.COMPOSITION, RelationshipType.SUPERSEDES}
)


def _check_placement(objects: Mapping[str, CognitiveObject]) -> None:
    for obj in objects.values():
        expected = TYPE_REGION.get(obj.type)
        if obj.region is not expected:
            raise PlacementError(
                f"{obj.handle} ({obj.type.value}) placed in {obj.region.value}, "
                f"must be {expected.value if expected else '?'}"
            )


def _check_referential_integrity(objects: Mapping[str, CognitiveObject]) -> None:
    for obj in objects.values():
        for edge in obj.relationships:
            if edge.rel_type in _REFERENTIAL and edge.target not in objects:
                raise StateConsistencyError(
                    f"{obj.handle} has {edge.rel_type.value} to missing {edge.target}"
                )


def _check_acyclicity(objects: Mapping[str, CognitiveObject]) -> None:
    # Build the DAG-edge graph and detect any cycle (DFS with colouring).
    adj: dict[str, list[str]] = {h: [] for h in objects}
    for obj in objects.values():
        for edge in obj.relationships:
            if edge.rel_type in DAG_EDGES and edge.target in objects:
                adj[obj.handle].append(edge.target)
    WHITE, GREY, BLACK = 0, 1, 2
    color = {h: WHITE for h in objects}

    def dfs(node: str) -> None:
        color[node] = GREY
        for nxt in adj[node]:
            if color[nxt] == GREY:
                raise StateConsistencyError(f"Cyclic DAG relationship at {node} -> {nxt}")
            if color[nxt] == WHITE:
                dfs(nxt)
        color[node] = BLACK

    for h in objects:
        if color[h] == WHITE:
            dfs(h)


class InvariantEngine:
    """Runs structural invariants plus any registered semantic validators."""

    def __init__(self) -> None:
        self._validators: list[InvariantValidator] = []
        self._lock = threading.Lock()

    def register(self, validator: InvariantValidator) -> None:
        if not isinstance(validator, InvariantValidator):
            raise TypeError(f"{validator!r} is not an InvariantValidator")
        with self._lock:
            self._validators.append(validator)

    def validators(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(v.name for v in self._validators)

    def validate(self, objects: Mapping[str, CognitiveObject]) -> None:
        _check_placement(objects)
        _check_referential_integrity(objects)
        _check_acyclicity(objects)
        with self._lock:
            validators = list(self._validators)
        for v in validators:
            v.validate(objects)  # engine-supplied semantic checks
