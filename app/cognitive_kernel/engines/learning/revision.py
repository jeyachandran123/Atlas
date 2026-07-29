"""The Knowledge Revision Manager (items 9/30/32) — the durable, reversible write.

Learning is the *only* faculty that commits durable change (LeL1), and it does so
**only through the State Manager** — versioned (LeL21), with complete provenance
(LeL24), and with a defined rollback (LeL13). A validated candidate promotes an
existing PROPOSED belief to ACTIVE (or consolidates a new one), stamping provenance
edges to its evidence and archiving the consumed candidates (never deleting them —
LeL27). Rollback reverts to the prior version (or deprecates a newly-created belief).
"""

from __future__ import annotations

import uuid
from typing import Any

from ...state import CognitiveStateManager, ObjectStatus, ObjectType, Region
from ...state.contracts import RelationshipEdge, RelationshipType
from .contracts import KnowledgeRevision, LearningCandidate, LearningConfig
from .errors import RollbackError


class KnowledgeRevisionManager:
    def __init__(self, state: CognitiveStateManager, config: LearningConfig) -> None:
        self._state = state
        self._config = config

    def find_target(self, candidate: LearningCandidate) -> str | None:
        """An existing PROPOSED belief with the same claim — to promote (consolidate)."""
        if candidate.target_handle and self._state.exists(candidate.target_handle):
            return candidate.target_handle
        for b in self._state.query(region=Region.R5_BELIEF, type=ObjectType.BELIEF, status=ObjectStatus.PROPOSED):
            if (b.payload.get("statement") == candidate.statement
                    and bool(b.payload.get("negated", False)) == candidate.negated):
                return b.handle
        return None

    def revise(self, candidate: LearningCandidate, *, record_id: str, context: Any, seq: int) -> KnowledgeRevision:
        provenance = tuple(f"episode:{e}" for e in candidate.episodes) + \
            tuple(f"evidence:{h}" for h in candidate.evidence)
        target = self.find_target(candidate)
        tx = self._state.begin_transaction(context)
        payload = {
            "statement": candidate.statement, "negated": candidate.negated, "learned_by": record_id,
            "provenance": list(provenance), "episodes": list(candidate.episodes), "consolidated": True,
        }
        if target is not None:
            from_version = self._state.get(target).version
            tx.update(target, status=ObjectStatus.ACTIVE, confidence=candidate.aggregate_confidence,
                      payload_merge=payload, provenance=f"learning:{record_id}")
            for ev in candidate.evidence:
                if self._state.exists(ev):
                    tx.link(target, RelationshipType.INFLUENCE, ev)
            to_version = from_version + 1
        else:
            edges = tuple(RelationshipEdge(RelationshipType.INFLUENCE, ev)
                          for ev in candidate.evidence if self._state.exists(ev))
            target = tx.create(ObjectType.BELIEF, payload=payload, status=ObjectStatus.ACTIVE,
                               confidence=candidate.aggregate_confidence, relationships=edges,
                               provenance=f"learning:{record_id}")
            from_version, to_version = 0, 1
        # Archive the consumed candidate objects — never delete (LeL27).
        for h in candidate.source_handles:
            if self._state.exists(h):
                tx.update(h, status=ObjectStatus.ARCHIVED, payload_merge={"consolidated_into": target})
        tx.commit()
        return KnowledgeRevision(
            revision_id="rev-" + uuid.uuid4().hex, target_handle=target, from_version=from_version,
            to_version=to_version, kind=candidate.kind, statement=candidate.statement,
            confidence=candidate.aggregate_confidence, evidence=candidate.evidence, provenance=provenance,
            reversible=True, seq=seq,
        )

    def rollback(self, revision: KnowledgeRevision, context: Any) -> bool:
        """Reverse a committed revision (LeL13) — versioned, never destructive."""
        if not self._state.exists(revision.target_handle):
            raise RollbackError(f"revision target {revision.target_handle} no longer exists")
        if revision.from_version == 0:
            # a newly-created belief is deprecated (archived), never deleted (LeL27).
            tx = self._state.begin_transaction(context)
            tx.update(revision.target_handle, status=ObjectStatus.ARCHIVED, payload_merge={"rolled_back": True})
            tx.commit()
        else:
            self._state.rollback(revision.target_handle, revision.from_version, context)
        return True
