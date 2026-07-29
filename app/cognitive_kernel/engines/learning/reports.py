"""Learning trace, report, and long-term improvement builders (items 21/36/38).

Every learning is explainable and auditable — including rejections (LeL19/LeL20).
These pure builders assemble the per-candidate trace, the integrity digest, the
learning report, and the long-term improvement summary (Development evidence).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Sequence

from .contracts import (
    AuthorizationOutcome,
    KnowledgeRevision,
    LearningCandidate,
    LearningRecord,
    LearningReport,
    ValidationResult,
)


def build_trace(candidate: LearningCandidate, validation: ValidationResult,
                authorization: AuthorizationOutcome | None, revision: KnowledgeRevision | None) -> tuple[str, ...]:
    lines = [
        f"candidate {candidate.candidate_id[:12]} [{candidate.kind.value}] '{candidate.statement}'"
        f"{' (¬)' if candidate.negated else ''}",
        f"evidence={len(candidate.evidence)} episodes={len(candidate.episodes)} "
        f"support={candidate.support:.3f} oppose={candidate.oppose:.3f} conf={candidate.aggregate_confidence:.3f}",
        f"impact={candidate.impact.value}",
        f"validation={validation.verdict.value} ({'; '.join(validation.reasons)})",
    ]
    if authorization is not None:
        lines.append(f"authorization: {authorization.authority} "
                     f"{'approved' if authorization.approved else ('escalated' if authorization.escalated else 'declined')}"
                     f" — {authorization.reason}")
    if revision is not None:
        lines.append(f"revision {revision.revision_id[:12]}: {revision.target_handle} "
                     f"v{revision.from_version}->v{revision.to_version} (reversible={revision.reversible})")
        lines.append(f"provenance: {list(revision.provenance)}")
    else:
        lines.append("NO CHANGE (default — LeL9)")
    return tuple(lines)


def digest(trace: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps(list(trace), sort_keys=True).encode("utf-8")).hexdigest()


def build_report(records: Sequence[LearningRecord], *, seq: int) -> LearningReport:
    committed = sum(1 for r in records if r.committed)
    deferred = sum(1 for r in records if not r.committed and r.verdict.value == "needs_authorization")
    rejected = len(records) - committed - deferred
    return LearningReport(report_id="lrep-" + uuid.uuid4().hex, examined=len(records), committed=committed,
                          deferred=deferred, rejected=rejected, records=tuple(records), seq=seq)


def improvement_tracking(history: Sequence[dict]) -> dict:
    """Long-term improvement summary (item 38) — Development evidence, read-only."""
    committed = [h for h in history if h.get("committed")]
    return {
        "total_records": len(history), "committed": len(committed),
        "rejected": sum(1 for h in history if not h.get("committed")),
        "mean_committed_confidence": round(
            sum(h.get("confidence", 0.0) for h in committed) / len(committed), 4) if committed else 0.0,
        "kinds": sorted({h.get("kind") for h in committed if h.get("kind")}),
    }
