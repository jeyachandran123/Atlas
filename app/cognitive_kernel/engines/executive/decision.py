"""The Decision Arbiter (Phase 5 Ch4) — executive commitment authority.

The executive is not a magic decider (anti-homunculus): it grounds every
governance ruling in the *reasoning proposal's* calibrated confidence (ExL10) and
applies the **risk-scaled autonomy threshold** (ExL13) under standing policy. It
produces immutable Executive Decisions (ExL3) with alternatives, rationale,
confidence, and authority. "Ask User" and "Escalate" are first-class members of
the repertoire — the executive's most important competence is knowing when *not*
to decide alone (ExL14/P10).
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from .contracts import (
    DecisionKind,
    DecisionOutcome,
    ExecutiveConfig,
    ExecutiveDecision,
    PolicyDecision,
    ReasoningProposal,
)

_ALTERNATIVES = ("approve", "reject", "escalate", "ask_user", "wait")


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


class DecisionArbiter:
    def __init__(self, config: ExecutiveConfig) -> None:
        self._config = config

    def threshold(self, stakes: float, reversibility: float) -> float:
        """The risk-scaled autonomy threshold (ExL13): irreversible high-stakes demands more."""
        risk = _clamp(stakes) * (1.0 - _clamp(reversibility))
        return round(min(0.99, self._config.autonomy_threshold + 0.3 * risk), 6)

    def decide(
        self,
        proposal: ReasoningProposal,
        policy: PolicyDecision,
        *,
        priority: float = 0.5,
        risk: Mapping[str, Any] | None = None,
        authority: str = "executive",
        seq: int = 0,
    ) -> ExecutiveDecision:
        threshold = self.threshold(proposal.stakes, proposal.reversibility)
        constraints = list(policy.applied)
        if proposal.safety_relevant:
            constraints.append("safety")
        if proposal.identity_relevant:
            constraints.append("identity")
        risk_high = bool(risk) and float(risk.get("risk", 0.0)) >= 0.8

        # 1. Absolute constitutional denial (Safety/Identity) — REJECT, non-overridable (ExL7).
        if not policy.allowed and policy.absolute:
            return self._mk(DecisionKind.REJECT, DecisionOutcome.REJECTED, proposal, threshold,
                            f"absolute denial: {policy.reason}", constraints, authority, seq)
        # 2. Ordinary policy denial — REJECT.
        if not policy.allowed:
            return self._mk(DecisionKind.REJECT, DecisionOutcome.REJECTED, proposal, threshold,
                            f"denied by policy: {policy.reason}", constraints, authority, seq)
        # 3. Human-in-the-loop required by policy — Ask User (ExL14).
        if policy.requires_approval:
            return self._mk(DecisionKind.ASK_USER, DecisionOutcome.ESCALATED, proposal, threshold,
                            f"human approval required: {policy.reason}", constraints, authority, seq)
        # 4. High risk from risk evaluation — escalate.
        if risk_high:
            return self._mk(DecisionKind.ESCALATE, DecisionOutcome.ESCALATED, proposal, threshold,
                            "risk evaluation flagged high risk", constraints, authority, seq)
        # 5. Confidence clears the risk-scaled threshold — APPROVE (ExL13).
        if proposal.confidence >= threshold:
            return self._mk(DecisionKind.APPROVE, DecisionOutcome.APPROVED, proposal, threshold,
                            "confidence clears the risk-scaled autonomy threshold", constraints, authority, seq)
        # 6. Below threshold under high stakes — escalate to human (P10).
        if proposal.stakes >= self._config.escalation_stakes:
            return self._mk(DecisionKind.ESCALATE, DecisionOutcome.ESCALATED, proposal, threshold,
                            "low confidence under high stakes — escalate (ExL13/P10)", constraints, authority, seq)
        # 7. Below threshold, low stakes — defer for more evidence (bounded, reversible).
        return self._mk(DecisionKind.WAIT, DecisionOutcome.DEFERRED, proposal, threshold,
                        "insufficient confidence; deferred pending more evidence", constraints, authority, seq)

    def _mk(self, kind, outcome, proposal, threshold, rationale, constraints, authority, seq) -> ExecutiveDecision:
        return ExecutiveDecision(
            decision_id="dec-" + uuid.uuid4().hex, kind=kind, outcome=outcome, subject=proposal.proposal_id,
            rationale=rationale, confidence=round(_clamp(proposal.confidence), 6), threshold=threshold,
            stakes=round(_clamp(proposal.stakes), 6), reversibility=round(_clamp(proposal.reversibility), 6),
            constraints=tuple(constraints), alternatives=_ALTERNATIVES, authority=authority, seq=seq,
        )

    def ruling(
        self, kind: DecisionKind, outcome: DecisionOutcome, subject: str, rationale: str,
        *, confidence: float = 1.0, authority: str = "executive", seq: int = 0,
        constraints: tuple[str, ...] = (), alternatives: tuple[str, ...] = _ALTERNATIVES,
    ) -> ExecutiveDecision:
        """A governance ruling not tied to a proposal (goal transition, allocation, policy, conflict)."""
        return ExecutiveDecision(
            decision_id="dec-" + uuid.uuid4().hex, kind=kind, outcome=outcome, subject=subject,
            rationale=rationale, confidence=round(_clamp(confidence), 6), threshold=0.0, stakes=0.0,
            reversibility=1.0, constraints=constraints, alternatives=alternatives, authority=authority, seq=seq,
        )
