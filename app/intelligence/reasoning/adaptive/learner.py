"""
Adaptive Learner.

Collects anonymous quality signals and adjusts reasoning behaviour
based on accumulated observations — without modifying prompts.

Signals collected:
- expansion_needed: response required expansion after generation
- clarification_needed: user had to clarify their request
- tool_failed: a tool call failed
- repo_miss: repository search returned no results
- strategy_mismatch: wrong strategy was selected

Adjustments produced:
- Increase complexity estimate for certain intent+strategy combinations
- Prefer retrieval for intents that frequently miss
- Reduce tool calls for intents that frequently fail

In-process store. Designed for a persistent backend to be swapped in.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.intelligence.reasoning.interfaces import AbstractAdaptiveLearner
from app.intelligence.reasoning.models import QualitySignal

# Thresholds for triggering adjustments
_ADJUSTMENT_THRESHOLD = 3   # signals needed before adjusting
_DECAY_FACTOR = 0.9         # older signals matter less (applied on read)


@dataclass
class _SignalBucket:
    """Accumulated signals for one (intent, strategy) combination."""
    expansion_needed: int = 0
    clarification_needed: int = 0
    tool_failed: int = 0
    repo_miss: int = 0
    strategy_mismatch: int = 0
    total: int = 0


class AdaptiveLearner(AbstractAdaptiveLearner):
    """
    Collects quality signals and produces behaviour adjustments.
    Thread-safe for single-process asyncio use.
    """

    def __init__(self) -> None:
        # Keyed by (intent, strategy)
        self._buckets: dict[tuple[str, str], _SignalBucket] = defaultdict(_SignalBucket)

    def record(self, signal: QualitySignal) -> None:
        key = (signal.intent, signal.strategy)
        bucket = self._buckets[key]
        bucket.total += 1

        if signal.signal_type == "expansion_needed":
            bucket.expansion_needed += 1
        elif signal.signal_type == "clarification_needed":
            bucket.clarification_needed += 1
        elif signal.signal_type == "tool_failed":
            bucket.tool_failed += 1
        elif signal.signal_type == "repo_miss":
            bucket.repo_miss += 1
        elif signal.signal_type == "strategy_mismatch":
            bucket.strategy_mismatch += 1

    def get_adjustments(self, intent: str, strategy: str) -> dict:
        """
        Return behaviour adjustments based on accumulated signals.
        Returns empty dict if no adjustments needed.
        """
        key = (intent, strategy)
        bucket = self._buckets.get(key)
        if not bucket or bucket.total < 1:
            return {}

        adjustments: dict = {}

        # Frequent expansions → increase response depth
        if bucket.expansion_needed >= _ADJUSTMENT_THRESHOLD:
            adjustments["increase_response_depth"] = True
            adjustments["expansion_needed_count"] = bucket.expansion_needed

        # Frequent clarifications → lower confidence threshold (ask sooner)
        if bucket.clarification_needed >= _ADJUSTMENT_THRESHOLD:
            adjustments["lower_clarification_threshold"] = True
            adjustments["clarification_needed_count"] = bucket.clarification_needed

        # Frequent tool failures → reduce tool calls
        if bucket.tool_failed >= _ADJUSTMENT_THRESHOLD:
            adjustments["reduce_tool_calls"] = True
            adjustments["tool_failed_count"] = bucket.tool_failed

        # Frequent repo misses → always attempt retrieval
        if bucket.repo_miss >= _ADJUSTMENT_THRESHOLD:
            adjustments["force_retrieval"] = True
            adjustments["repo_miss_count"] = bucket.repo_miss

        # Frequent strategy mismatches → flag for review
        if bucket.strategy_mismatch >= _ADJUSTMENT_THRESHOLD:
            adjustments["strategy_unreliable"] = True
            adjustments["strategy_mismatch_count"] = bucket.strategy_mismatch

        return adjustments

    def summary(self) -> dict:
        """Return a summary of all accumulated signals for observability."""
        return {
            f"{intent}:{strategy}": {
                "total": b.total,
                "expansion": b.expansion_needed,
                "clarification": b.clarification_needed,
                "tool_failed": b.tool_failed,
                "repo_miss": b.repo_miss,
                "strategy_mismatch": b.strategy_mismatch,
            }
            for (intent, strategy), b in self._buckets.items()
            if b.total > 0
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_learner: AdaptiveLearner | None = None


def get_adaptive_learner() -> AdaptiveLearner:
    global _learner
    if _learner is None:
        _learner = AdaptiveLearner()
    return _learner
