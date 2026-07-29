"""Development ports — proposal review routed through the Runtime (no engine imports).

A proposal is submitted for review through the Runtime, to the Executive (which
routes human-tier proposals onward — DeL3/DeL8). Development *proposes*; it never
applies anything. Submission is best-effort (recorded, never fatal). The null port
records without submitting.
"""

from __future__ import annotations

from typing import Any

from ...runtime import ExecutionRequest
from .contracts import EvolutionProposal, ReviewTier


class RuntimeReviewPort:
    def __init__(self, runtime: Any, engine_name: str = "executive") -> None:
        self._rt = runtime
        self._name = engine_name

    def submit(self, proposal: EvolutionProposal, context: Any) -> bool:
        if proposal.review_tier is ReviewTier.FORBIDDEN:
            return False  # constitution/identity Core — never submitted (DeL1/DeL16)
        payload = {"subject": f"development:{proposal.proposal_id}",
                   "reason": f"[{proposal.review_tier.value}] {proposal.title} — {proposal.rationale}"}
        try:
            handle = self._rt.submit(ExecutionRequest(
                engine=self._name, operation="escalate", payload=payload,
                correlation_id=getattr(context, "correlation_id", None),
                security=getattr(context, "security", None)))
            self._rt.drain()
            return handle.result().error is None
        except Exception:
            return False


class NullReviewPort:
    def submit(self, proposal: EvolutionProposal, context: Any) -> bool:
        return False
