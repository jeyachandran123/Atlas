"""Cognitive State I/O for the Executive — via the State Manager only.

The executive's durable footprint in Cognitive State is: **GOAL** objects in R2
(owned/governed by the Goal Governor) and immutable **EXECUTIVE_DECISION** objects
in R9 — every governance ruling is an immutable, auditable artifact (ExL3), and
their set is the decision audit trail (item 39). All writes flow through the State
Manager's transactional contract (RL3/ExL26); the executive owns no store.
"""

from __future__ import annotations

from typing import Any

from ...state import CognitiveStateManager, ObjectType, Region
from .contracts import ExecutiveDecision


def write_decision(state: CognitiveStateManager, context: Any, decision: ExecutiveDecision) -> str:
    """Persist an immutable Executive Decision (R9); a new decision supersedes, never edits."""
    tx = state.begin_transaction(context)
    handle = tx.create(
        ObjectType.EXECUTIVE_DECISION,
        payload={
            "decision_id": decision.decision_id, "kind": decision.kind.value,
            "outcome": decision.outcome.value, "subject": decision.subject,
            "rationale": decision.rationale, "confidence": decision.confidence,
            "threshold": decision.threshold, "stakes": decision.stakes,
            "reversibility": decision.reversibility, "constraints": list(decision.constraints),
            "alternatives": list(decision.alternatives), "authority": decision.authority, "seq": decision.seq,
        },
        confidence=decision.confidence,
        provenance=f"executive:{decision.authority}",
    )
    tx.commit()
    return handle


def decision_trail(state: CognitiveStateManager, *, subject: str | None = None) -> list[Any]:
    """The immutable Executive Decision audit trail (item 39)."""
    objs = state.query(region=Region.R9_METACOGNITIVE, type=ObjectType.EXECUTIVE_DECISION)
    trail = [o for o in objs if "decision_id" in o.payload]
    if subject is not None:
        trail = [o for o in trail if o.payload.get("subject") == subject]
    return sorted(trail, key=lambda o: o.payload.get("seq", 0))
