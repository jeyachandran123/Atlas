"""The Learning Policy Manager (item 18) + Safe Learning Constraints (item 19).

Classifies a candidate's **impact** and scales governance accordingly (LeL33):
LOW/MODERATE learn on the automatic tier (validated, sandboxed, monitored,
reversible — LeL34); HIGH-impact (safety/identity/policy) is gated to Executive
approval, escalating to human (LeL6/LeL17/LeL18). Constitution changes are
absolutely forbidden (LeL5). Pure and deterministic.
"""

from __future__ import annotations

from .contracts import Impact, LearningCandidate, LearningConfig, LearningKind


class LearningPolicyManager:
    def __init__(self, config: LearningConfig) -> None:
        self._config = config

    def classify_impact(self, candidate: LearningCandidate) -> Impact:
        statement = candidate.statement.lower()
        if any(marker in statement for marker in self._config.high_impact_markers):
            return Impact.HIGH  # safety/identity/policy/core — gated (LeL6/LeL17/LeL18)
        if candidate.kind is LearningKind.RULE_INDUCTION:
            return Impact.MODERATE
        return Impact.LOW

    def requires_authorization(self, impact: Impact) -> bool:
        # LOW learns on the automatic tier (LeL34); MODERATE needs Executive approval;
        # HIGH is gated to Executive → human review (LeL3/LeL17).
        return impact in (Impact.MODERATE, Impact.HIGH)

    def forbidden(self, candidate: LearningCandidate) -> tuple[bool, str]:
        statement = candidate.statement.lower()
        if "constitution" in statement:
            return True, "the constitution can never be learned or altered (LeL5)"
        return False, ""

    def stakes_for(self, impact: Impact) -> float:
        return {Impact.LOW: 0.1, Impact.MODERATE: 0.4, Impact.HIGH: self._config.high_impact_stakes}[impact]
