"""Learning ports — Executive authorization routed through the Runtime.

Above-automatic-tier learning must be authorized by the Executive (LeL3), and
HIGH-impact (safety/identity/policy) escalates to human review (LeL6/LeL17/LeL18).
The port submits the change as a governance proposal to the Executive **through the
Runtime by name** — Learning never governs and never imports a sibling engine. The
null port defers everything (safe default: no authorization ⇒ no durable change).
"""

from __future__ import annotations

from typing import Any

from ...runtime import ExecutionRequest
from .contracts import AuthorizationOutcome, Impact, LearningCandidate

_STAKES = {Impact.LOW: 0.1, Impact.MODERATE: 0.4, Impact.HIGH: 0.9}


class RuntimeAuthorizationPort:
    def __init__(self, runtime: Any, engine_name: str = "executive") -> None:
        self._rt = runtime
        self._name = engine_name

    def authorize(self, candidate: LearningCandidate, context: Any) -> AuthorizationOutcome:
        payload = {
            "statement": f"commit learning: {candidate.statement}",
            "confidence": candidate.aggregate_confidence, "stakes": _STAKES[candidate.impact],
            "kind": "action", "reversibility": 1.0,
            "safety_relevant": candidate.impact is Impact.HIGH,
            "identity_relevant": "identity" in candidate.statement.lower(),
        }
        try:
            handle = self._rt.submit(ExecutionRequest(
                engine=self._name, operation="govern", payload=payload,
                correlation_id=getattr(context, "correlation_id", None),
                security=getattr(context, "security", None)))
            self._rt.drain()
            result = handle.result()
            if result.error or not result.value:
                return AuthorizationOutcome(False, True, "human", "authorizer unavailable — deferred")
            outcome = result.value.get("outcome")
        except Exception:
            return AuthorizationOutcome(False, True, "human", "authorizer unavailable — deferred")
        if outcome == "approved":
            return AuthorizationOutcome(True, False, "executive", "approved by executive")
        if outcome == "escalated":
            return AuthorizationOutcome(False, True, "human", "escalated to human review (LeL17)")
        return AuthorizationOutcome(False, False, "executive", f"declined ({outcome})")


class NullAuthorizationPort:
    """No Executive wired — above-automatic-tier changes are deferred (safe default)."""

    def authorize(self, candidate: LearningCandidate, context: Any) -> AuthorizationOutcome:
        return AuthorizationOutcome(False, True, "human", "no authorizer — deferred to review")
