"""Cognitive State I/O for Reasoning — via the State Manager only.

Reasoning writes three kinds of product, all through the manager's transactional
contract (RL3), and holds no durable state of its own (ReL2):

* the **episode record** — a ``REASONING_STATE`` object in **R6** keyed by the
  episode id; its version history *is* the reasoning history (item 26), and it is
  captured by State checkpoints and rebuilt on recovery;
* the **conclusion** — a ``BELIEF`` object in **R5** written **PROPOSED** (never
  committed — ReL9) with ``DEPENDENCY`` edges to the evidence that supports it
  (evidence traceability, item 24);
* **learning candidates** — ``LEARNING_CANDIDATE`` proposals in **R9**, again
  PROPOSED, for a future Learning engine to validate and commit (item 36).
"""

from __future__ import annotations

from typing import Any, Mapping

from ...state import CognitiveStateManager, ObjectStatus, ObjectType
from ...state.contracts import RelationshipEdge, RelationshipType

_STATUS = {
    "proposed": ObjectStatus.PROPOSED,
    "active": ObjectStatus.ACTIVE,
    "suspended": ObjectStatus.SUSPENDED,
}


def status_of(name: str) -> ObjectStatus:
    return _STATUS.get(name, ObjectStatus.PROPOSED)


def write_episode(
    state: CognitiveStateManager, context: Any, *, episode_id: str, payload: Mapping[str, Any]
) -> str:
    """Upsert the R6 reasoning-episode record (versioned = reasoning history)."""
    tx = state.begin_transaction(context)
    if state.exists(episode_id):
        tx.update(episode_id, payload_replace=dict(payload), provenance="reasoning")
    else:
        tx.create(
            ObjectType.REASONING_STATE, handle=episode_id, payload=dict(payload),
            provenance="reasoning",
        )
    tx.commit()
    return episode_id


def write_belief(
    state: CognitiveStateManager,
    context: Any,
    *,
    statement: str,
    negated: bool,
    confidence: float,
    evidence_handles: tuple[str, ...],
    episode_id: str,
    status: ObjectStatus,
) -> str:
    """Write a PROPOSED belief product with dependency edges to its evidence."""
    rels = tuple(
        RelationshipEdge(RelationshipType.DEPENDENCY, h)
        for h in evidence_handles
        if state.exists(h)
    )
    tx = state.begin_transaction(context)
    handle = tx.create(
        ObjectType.BELIEF,
        payload={"statement": statement, "negated": negated, "derived_by": "reasoning", "episode": episode_id},
        status=status,
        confidence=round(confidence, 6),
        relationships=rels,
        provenance=f"reasoning:{episode_id}",
    )
    tx.commit()
    return handle


def write_learning_candidate(
    state: CognitiveStateManager,
    context: Any,
    *,
    payload: Mapping[str, Any],
    episode_id: str,
    status: ObjectStatus,
) -> str:
    """Write a PROPOSED learning candidate (a proposal for Learning — never a commit)."""
    tx = state.begin_transaction(context)
    handle = tx.create(
        ObjectType.LEARNING_CANDIDATE, payload=dict(payload), status=status,
        provenance=f"reasoning:{episode_id}",
    )
    tx.commit()
    return handle


def read_episode(state: CognitiveStateManager, episode_id: str) -> Any | None:
    return state.get(episode_id) if state.exists(episode_id) else None
