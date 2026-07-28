"""Reasoning dynamics — type & strategy selection, convergence, and the economy.

Implements the governed process of Phase 4: the Type Selector (Ch2 §3) and
Strategy Manager (Ch2 §4, Ch5) choose *what kind* of inference and *how* to run
it (explicit and recorded — ReL6); the Convergence Monitor (Ch2 §9) detects
progress, loops, and impasse; and the Resource Governor (Ch9) bounds the episode
so every one has a principled stop (ReL7) — the value-of-computation criterion,
fatigue, and the budget. Strategy switching is stabilised against thrash.
"""

from __future__ import annotations

from collections import Counter

from .contracts import (
    ReasoningConfig,
    ReasoningRequest,
    ReasoningStrategy,
    ReasoningType,
    TerminationReason,
)


class TypeSelector:
    """Map the goal + conscious content pattern to a reasoning type (Ch3, ReL6)."""

    def select(self, request: ReasoningRequest, content) -> ReasoningType:
        if request.type_hint is not None:
            return request.type_hint
        has_rules = bool(content.rules)
        has_causes = bool(content.causes)
        has_analogies = bool(content.analogies)
        if request.question:
            if has_rules:
                return ReasoningType.DEDUCTIVE            # firm premises -> derive necessarily
            if has_causes:
                return ReasoningType.CAUSAL
            if has_analogies:
                return ReasoningType.ANALOGICAL
            return ReasoningType.PROBABILISTIC            # weigh evidence for/against
        # No explicit question: explain or discover.
        if has_causes:
            return ReasoningType.ABDUCTIVE                # best explanation (the default)
        predicates = [
            s.rsplit(".", 1)[1]
            for s in (e.statement for e in content.evidence if not e.negated)
            if "." in s
        ]
        if predicates and max(Counter(predicates).values()) >= 2:
            return ReasoningType.INDUCTIVE               # recurring instances -> generalise
        if has_analogies:
            return ReasoningType.ANALOGICAL
        return ReasoningType.ABDUCTIVE


class StrategySelector:
    """Choose and switch strategy by (type x stakes), with anti-thrash hysteresis (Ch5)."""

    def __init__(self, config: ReasoningConfig) -> None:
        self._config = config

    def select(self, rtype: ReasoningType, request: ReasoningRequest) -> ReasoningStrategy:
        if request.strategy_hint is not None:
            return request.strategy_hint
        if request.stakes < 0.2:
            return ReasoningStrategy.FAST_HEURISTIC       # low stakes -> System-1
        if rtype is ReasoningType.DEDUCTIVE:
            return ReasoningStrategy.VERIFY_THEN_TRUST if request.stakes >= 0.7 else ReasoningStrategy.LINEAR
        if rtype in (ReasoningType.ABDUCTIVE, ReasoningType.DIAGNOSTIC, ReasoningType.PROBABILISTIC):
            return ReasoningStrategy.ENSEMBLE if request.stakes >= 0.7 else ReasoningStrategy.SEARCH
        return ReasoningStrategy.LINEAR

    def should_switch(self, current: ReasoningStrategy, proposed: ReasoningStrategy, dwell: int) -> bool:
        """Switch only after a minimum dwell — stabilised like attention (anti-thrash)."""
        return proposed is not current and dwell >= 1


class ConvergenceMonitor:
    """Track the confidence trajectory; detect convergence, stall, loop, and impasse."""

    def __init__(self) -> None:
        self._traj: list[float] = []

    def update(self, top_confidence: float) -> None:
        self._traj.append(round(top_confidence, 6))

    @property
    def trajectory(self) -> tuple[float, ...]:
        return tuple(self._traj)

    def converged(self, threshold: float) -> bool:
        return bool(self._traj) and self._traj[-1] >= threshold

    def diminishing(self, epsilon: float) -> bool:
        return len(self._traj) >= 2 and abs(self._traj[-1] - self._traj[-2]) < epsilon

    def stalled(self, epsilon: float, window: int = 3) -> bool:
        if len(self._traj) < window + 1:
            return False
        recent = self._traj[-(window + 1):]
        return all(abs(recent[i + 1] - recent[i]) < epsilon for i in range(window))

    def impasse(self, has_candidates: bool) -> bool:
        if not has_candidates:
            return True
        return len(self._traj) >= 3 and max(self._traj) == 0.0


class FatigueModel:
    """Sustained hard reasoning depletes budget; idle recovers it (Ch9)."""

    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value = 0.0

    def effort(self, config: ReasoningConfig) -> None:
        self.value = min(1.0, self.value + config.fatigue_per_step)

    def recover(self, config: ReasoningConfig) -> None:
        self.value = max(0.0, self.value - config.fatigue_recovery)


class ResourceGovernor:
    """Bounds the episode: budget, stopping, value-of-computation (Ch9, ReL7)."""

    def __init__(self, config: ReasoningConfig) -> None:
        self._config = config

    def max_steps(self, request: ReasoningRequest) -> int:
        return request.max_steps if request.max_steps is not None else self._config.max_steps

    def stop(
        self,
        *,
        monitor: ConvergenceMonitor,
        steps: int,
        max_steps: int,
        threshold: float,
        budget_exhausted: bool,
        has_candidates: bool,
    ) -> tuple[bool, TerminationReason | None]:
        if monitor.converged(threshold):
            return True, TerminationReason.CONVERGED
        if not has_candidates or monitor.impasse(has_candidates):
            return True, TerminationReason.IMPASSE
        if budget_exhausted or steps >= max_steps:
            return True, TerminationReason.BUDGET_EXHAUSTED
        if monitor.stalled(self._config.diminishing_epsilon):
            return True, TerminationReason.DIMINISHING_RETURNS
        return False, None
