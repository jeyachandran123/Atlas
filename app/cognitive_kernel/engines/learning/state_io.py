"""Cognitive State access for Learning — read helpers + knowledge integrity (item 39).

Learning is the only faculty that *writes* durable cognitive change, and it does so
only through the State Manager (see ``revision.py``). This module holds read-only
helpers and the knowledge-integrity check: every learned belief must carry provenance
(``learned_by`` + evidence edges) and the ledger must verify (LeL22/LeL24).
"""

from __future__ import annotations

from ...state import CognitiveStateManager, ObjectStatus, ObjectType, Region
from ...state.contracts import RelationshipType


def canonical_object_count(state: CognitiveStateManager) -> int:
    return len(state.all_current())


def learned_beliefs(state: CognitiveStateManager) -> list:
    return [b for b in state.query(region=Region.R5_BELIEF, type=ObjectType.BELIEF, status=ObjectStatus.ACTIVE)
            if b.payload.get("consolidated")]


def verify_integrity(state: CognitiveStateManager) -> tuple[bool, tuple[str, ...]]:
    """Every learned belief carries provenance; the ledger verifies (LeL24/LeL22)."""
    issues: list[str] = []
    for b in learned_beliefs(state):
        if not b.payload.get("learned_by"):
            issues.append(f"{b.handle}: learned belief without provenance record")
        has_evidence = any(e.rel_type is RelationshipType.INFLUENCE for e in b.relationships)
        if not has_evidence and not b.payload.get("provenance"):
            issues.append(f"{b.handle}: learned belief without evidence provenance")
    ledger_ok = state.verify_integrity()
    if not ledger_ok:
        issues.append("ledger integrity check failed")
    return (not issues, tuple(issues))
