"""The Cognitive Policy Manager (Phase 5 Ch7) + Constitutional Policy Enforcement.

Policy is how the executive governs the many *without micromanaging* (subsidiarity):
standing rules the local governors follow. Policies are versioned, inherited
(narrow-only), and **precedence-ordered** — Safety > Identity > privacy >
operational > convenience (ExL22) — with Safety and Identity DENY being
**absolute and non-overridable** (ExL7/ExL12). The manager seeds the constitutional
safety/identity policies at construction so enforcement is always in force.
"""

from __future__ import annotations

from typing import Any

from .contracts import (
    ABSOLUTE_FAMILIES,
    POLICY_PRECEDENCE,
    ExecutiveConfig,
    Policy,
    PolicyDecision,
    PolicyEffect,
    PolicyFamily,
    ReasoningProposal,
)


def _matches(policy: Policy, facts: dict[str, Any], proposal: ReasoningProposal) -> bool:
    for key, value in policy.predicate.items():
        if key == "statement_contains":
            if value not in proposal.statement:
                return False
        elif key == "kind":
            if proposal.kind != value:
                return False
        elif key in facts:
            if facts[key] != value:
                return False
        else:
            return False
    return True


class PolicyManager:
    def __init__(self, config: ExecutiveConfig) -> None:
        self._config = config
        self._policies: dict[str, Policy] = {}  # keyed by "family/name" -> latest version
        self._seed_constitutional()

    # --- constitutional enforcement (item 37) ---------------------------- #

    def _seed_constitutional(self) -> None:
        for policy in (
            Policy("pol-safety-irreversible", PolicyFamily.SAFETY, "gate_irreversible_high_stakes",
                   PolicyEffect.REQUIRE_APPROVAL,
                   predicate={"kind": "action", "irreversible": True, "high_stakes": True}),
            Policy("pol-safety-flagged", PolicyFamily.SAFETY, "gate_safety_relevant_action",
                   PolicyEffect.REQUIRE_APPROVAL,
                   predicate={"kind": "action", "safety_relevant": True}),
            Policy("pol-identity-core", PolicyFamily.IDENTITY, "protect_identity_core",
                   PolicyEffect.REQUIRE_APPROVAL, predicate={"identity_relevant": True}),
        ):
            self._policies[self._key(policy)] = policy

    @staticmethod
    def _key(policy: Policy) -> str:
        return f"{policy.family.value}/{policy.name}"

    # --- lifecycle ------------------------------------------------------- #

    def enact(self, policy: Policy, seq: int) -> Policy:
        """Enact a policy, versioning over any prior policy of the same family+name (ExL22)."""
        key = self._key(policy)
        prior = self._policies.get(key)
        version = (prior.version + 1) if prior is not None else 1
        enacted = Policy(
            policy_id=policy.policy_id, family=policy.family, name=policy.name, effect=policy.effect,
            predicate=dict(policy.predicate), scope=policy.scope, version=version, enacted_seq=seq,
        )
        self._policies[key] = enacted
        return enacted

    def retire(self, family: PolicyFamily, name: str) -> bool:
        return self._policies.pop(f"{family.value}/{name}", None) is not None

    def policies(self) -> tuple[Policy, ...]:
        return tuple(sorted(self._policies.values(), key=lambda p: (POLICY_PRECEDENCE[p.family], p.name)))

    # --- evaluation (items 13, 37) --------------------------------------- #

    def evaluate(self, proposal: ReasoningProposal) -> PolicyDecision:
        facts = {
            "always": True,
            "safety_relevant": proposal.safety_relevant,
            "identity_relevant": proposal.identity_relevant,
            "action": proposal.kind == "action",
            "irreversible": proposal.reversibility < 0.5,
            "high_stakes": proposal.stakes >= self._config.escalation_stakes,
            "low_confidence": proposal.confidence < self._config.autonomy_threshold,
        }
        applicable = [p for p in self._policies.values() if _matches(p, facts, proposal)]
        applicable.sort(key=lambda p: (POLICY_PRECEDENCE[p.family], -p.version))
        applied = tuple(p.policy_id for p in applicable)

        # Absolute dominance: a Safety/Identity DENY is non-overridable (ExL7/ExL12).
        for p in applicable:
            if p.family in ABSOLUTE_FAMILIES and p.effect is PolicyEffect.DENY:
                return PolicyDecision(
                    allowed=False, effect=PolicyEffect.DENY, dominant_family=p.family,
                    reason=f"absolute {p.family.value} policy '{p.name}' denies", applied=applied, absolute=True,
                )
        if not applicable:
            return PolicyDecision(True, PolicyEffect.ALLOW, None, "no policy applies", ())

        dominant = applicable[0]
        if dominant.effect is PolicyEffect.DENY:
            return PolicyDecision(
                False, PolicyEffect.DENY, dominant.family,
                f"policy '{dominant.name}' denies", applied,
                absolute=dominant.family in ABSOLUTE_FAMILIES,
            )
        requires_approval = any(p.effect is PolicyEffect.REQUIRE_APPROVAL for p in applicable)
        if requires_approval:
            approver = next(p for p in applicable if p.effect is PolicyEffect.REQUIRE_APPROVAL)
            return PolicyDecision(
                True, PolicyEffect.REQUIRE_APPROVAL, approver.family,
                f"policy '{approver.name}' requires approval", applied, requires_approval=True,
                absolute=approver.family in ABSOLUTE_FAMILIES,
            )
        return PolicyDecision(True, PolicyEffect.ALLOW, dominant.family, "allowed by policy", applied)

    # --- checkpoint / recovery ------------------------------------------- #

    def to_payload(self) -> list[dict[str, Any]]:
        return [
            {"policy_id": p.policy_id, "family": p.family.value, "name": p.name, "effect": p.effect.value,
             "predicate": dict(p.predicate), "scope": p.scope, "version": p.version, "enacted_seq": p.enacted_seq}
            for p in self._policies.values()
        ]

    def load_payload(self, rows: list[dict[str, Any]]) -> None:
        self._policies.clear()
        for r in rows:
            p = Policy(
                policy_id=r["policy_id"], family=PolicyFamily(r["family"]), name=r["name"],
                effect=PolicyEffect(r["effect"]), predicate=dict(r.get("predicate", {})),
                scope=r.get("scope", "global"), version=r.get("version", 1), enacted_seq=r.get("enacted_seq", 0),
            )
            self._policies[self._key(p)] = p
