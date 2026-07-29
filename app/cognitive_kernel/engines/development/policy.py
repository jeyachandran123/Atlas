"""Development Policy Manager + Governance + Constitutional Evolution Protection.

Classifies each proposal's review tier (DeL3/DeL8): capability-use enhancements go
to Executive review; architectural/new-faculty/scaling proposals require **human**
review; anything touching the constitution or identity Core is **FORBIDDEN** and
never proposed (DeL1/DeL16 — no maturity stage transcends the constitution). Pure
and deterministic.
"""

from __future__ import annotations

from .contracts import DevelopmentConfig, ProposalKind, ReviewTier

_HUMAN = {ProposalKind.ARCHITECTURAL_EVOLUTION, ProposalKind.NEW_FACULTY, ProposalKind.RESOURCE_SCALING}


class DevelopmentPolicyManager:
    def __init__(self, config: DevelopmentConfig) -> None:
        self._config = config

    def is_constitutional_evolution(self, title: str) -> bool:
        lowered = title.lower()
        return any(marker in lowered for marker in self._config.forbidden_markers)

    def review_tier(self, kind: ProposalKind, title: str) -> ReviewTier:
        if self.is_constitutional_evolution(title):
            return ReviewTier.FORBIDDEN            # DeL1/DeL16 — never proposed
        if kind in _HUMAN:
            return ReviewTier.HUMAN                # architecture/autonomy needs human authority (DeL3/DeL8)
        return ReviewTier.EXECUTIVE
