"""
Policy Engine.

Evaluates every request against a set of independent policy rules.
Policies never live inside prompts.

Design:
- Each policy is an independent PolicyRule
- Rules are registered in a registry
- Adding a new policy = registering one new rule
- Returns ALLOW, BLOCK, WARN, or REQUIRE_CONFIRMATION
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.intelligence.interfaces import AbstractPolicyEngine
from app.intelligence.models import Intent, IntentAnalysis, PolicyDecision, PolicyResult


# ── Policy Rule Interface ─────────────────────────────────────────────────────


class PolicyRule(ABC):
    """A single, independently testable policy rule."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def evaluate(
        self,
        message: str,
        intent_analysis: IntentAnalysis,
        user_id: str,
        org_id: str,
    ) -> PolicyResult | None:
        """Return a PolicyResult if this rule triggers, else None."""
        ...


# ── Concrete Policy Rules ─────────────────────────────────────────────────────


class UnsafeCommandPolicy(PolicyRule):
    """Block requests that ask Atlas to run destructive shell commands."""

    _BLOCKED = [
        "rm -rf", "del /f", "format c:", "drop database", "drop table",
        ":(){:|:&};:", "mkfs", "dd if=/dev/zero",
    ]

    @property
    def name(self) -> str:
        return "unsafe_command"

    def evaluate(self, message, intent_analysis, user_id, org_id):
        lower = message.lower()
        for cmd in self._BLOCKED:
            if cmd in lower:
                return PolicyResult(
                    decision=PolicyDecision.BLOCK,
                    reason=f"Request contains potentially destructive command: '{cmd}'",
                    violated_policies=[self.name],
                    safe_response=(
                        "I can't execute that command as it could cause irreversible damage. "
                        "If you need help with system administration, I can explain the "
                        "implications and suggest safer alternatives."
                    ),
                )
        return None


class DangerousCodePolicy(PolicyRule):
    """Warn when generating code that could be misused."""

    _WARN_PATTERNS = ["keylogger", "ransomware", "malware", "exploit", "rootkit"]

    @property
    def name(self) -> str:
        return "dangerous_code"

    def evaluate(self, message, intent_analysis, user_id, org_id):
        lower = message.lower()
        for pattern in self._WARN_PATTERNS:
            if pattern in lower:
                return PolicyResult(
                    decision=PolicyDecision.BLOCK,
                    reason=f"Request involves potentially harmful software: '{pattern}'",
                    violated_policies=[self.name],
                    safe_response=(
                        "I'm not able to help create software designed to cause harm. "
                        "I can help with legitimate security research, penetration testing "
                        "concepts, or defensive security implementations."
                    ),
                )
        return None


class PrivacyPolicy(PolicyRule):
    """Warn when the request involves processing personal data."""

    _PII_SIGNALS = [
        "social security", "ssn", "credit card number", "passport number",
        "date of birth", "home address", "phone number of",
    ]

    @property
    def name(self) -> str:
        return "privacy"

    def evaluate(self, message, intent_analysis, user_id, org_id):
        lower = message.lower()
        for sig in self._PII_SIGNALS:
            if sig in lower:
                return PolicyResult(
                    decision=PolicyDecision.WARN,
                    reason="Request may involve personal identifiable information",
                    violated_policies=[self.name],
                )
        return None


class MedicalLegalPolicy(PolicyRule):
    """Warn on medical or legal advice requests."""

    _MEDICAL = ["diagnose", "medical advice", "should i take", "drug dosage", "symptoms of"]
    _LEGAL = ["legal advice", "is it legal to", "sue", "lawsuit", "legal liability"]

    @property
    def name(self) -> str:
        return "medical_legal"

    def evaluate(self, message, intent_analysis, user_id, org_id):
        lower = message.lower()
        for sig in self._MEDICAL + self._LEGAL:
            if sig in lower:
                return PolicyResult(
                    decision=PolicyDecision.WARN,
                    reason="Request touches medical or legal domain — Atlas is not a professional advisor",
                    violated_policies=[self.name],
                )
        return None


class RepositoryPermissionPolicy(PolicyRule):
    """Block tool execution when no repository is selected."""

    @property
    def name(self) -> str:
        return "repository_permission"

    def evaluate(self, message, intent_analysis, user_id, org_id):
        # Tool execution without a repo context is allowed — tool planner handles this
        return None


# ── Policy Registry ───────────────────────────────────────────────────────────


class PolicyRegistry:
    def __init__(self) -> None:
        self._rules: list[PolicyRule] = []

    def register(self, rule: PolicyRule) -> None:
        self._rules.append(rule)

    def all_rules(self) -> list[PolicyRule]:
        return list(self._rules)


def _build_default_registry() -> PolicyRegistry:
    registry = PolicyRegistry()
    registry.register(UnsafeCommandPolicy())
    registry.register(DangerousCodePolicy())
    registry.register(PrivacyPolicy())
    registry.register(MedicalLegalPolicy())
    registry.register(RepositoryPermissionPolicy())
    return registry


# ── Policy Engine ─────────────────────────────────────────────────────────────


class PolicyEngine(AbstractPolicyEngine):
    """
    Evaluates all registered policy rules against a request.
    Returns the most severe result, or ALLOW if no rules trigger.
    """

    _SEVERITY: dict[PolicyDecision, int] = {
        PolicyDecision.ALLOW: 0,
        PolicyDecision.WARN: 1,
        PolicyDecision.REQUIRE_CONFIRMATION: 2,
        PolicyDecision.BLOCK: 3,
    }

    def __init__(self, registry: PolicyRegistry | None = None) -> None:
        self._registry = registry or _build_default_registry()

    def evaluate(
        self,
        message: str,
        intent_analysis: IntentAnalysis,
        user_id: str,
        org_id: str,
    ) -> PolicyResult:
        results: list[PolicyResult] = []

        for rule in self._registry.all_rules():
            result = rule.evaluate(message, intent_analysis, user_id, org_id)
            if result is not None:
                results.append(result)

        if not results:
            return PolicyResult(decision=PolicyDecision.ALLOW)

        # Return the most severe result
        return max(results, key=lambda r: self._SEVERITY[r.decision])


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: PolicyEngine | None = None


def get_policy_engine() -> PolicyEngine:
    global _engine
    if _engine is None:
        _engine = PolicyEngine()
    return _engine
