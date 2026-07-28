"""Attention ABI — the salience vector, candidates, config, and value objects.

Salience is a *vector*, not a scalar (AL2/AL9): eighteen dimensions, retained for
explainability, collapsed to a composite only at competition time. All types are
immutable value objects.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class SalienceVector:
    """The eighteen salience dimensions (Phase 3, Ch3). Defaults are neutral.

    ``confidence`` is a *precision/gain* modulator (default 1.0); ``reversibility``
    default 1.0 means fully reversible (risk not amplified).
    """

    goal_relevance: float = 0.0
    novelty: float = 0.0
    surprise: float = 0.0            # prediction error
    confidence: float = 1.0          # precision (gain modulator)
    urgency: float = 0.0
    risk: float = 0.0
    user_importance: float = 0.0
    relationship_importance: float = 0.0
    recency: float = 0.0
    cognitive_cost: float = 0.0
    reward_expectation: float = 0.0
    information_gain: float = 0.0
    curiosity: float = 0.0
    conflict: float = 0.0
    emotional_significance: float = 0.0
    business_priority: float = 0.0
    safety_implications: float = 0.0
    reversibility: float = 1.0


class AttentionMode(enum.Enum):
    BOTTOM_UP = "bottom_up"      # stimulus-driven
    TOP_DOWN = "top_down"        # goal/executive-driven
    INTERRUPT = "interrupt"      # surprise/safety preemption


@dataclass(frozen=True, slots=True)
class Candidate:
    """Something that could enter consciousness — a *reference* to a State object."""

    target: str                  # a handle (never a copy)
    vector: SalienceVector = field(default_factory=SalienceVector)
    source: str = "perception"


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    target: str
    vector: SalienceVector
    composite: float
    breakdown: Mapping[str, float]  # gate/field/cost components (AL9 transparency)
    source: str


@dataclass(frozen=True, slots=True)
class AttentionConfig:
    ignition_threshold: float = 0.4
    elimination_floor: float = 0.1
    hysteresis_margin: float = 0.1     # a challenger must exceed an incumbent by this
    coalition_capacity: int = 4        # bounded conscious field (aligned to WM focus)
    cost_weight: float = 0.3
    safety_veto: float = 0.7           # safety-implications above this dominate
    interrupt_threshold: float = 0.8   # surprise/safety preemption
    fatigue_per_cycle: float = 0.02
    fatigue_recovery: float = 0.05
    novelty_window: int = 16
    weights: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType(
            {
                # Primary dimensions dominate; novelty/curiosity are lowest (Phase 3 §3.4).
                "goal_relevance": 0.80, "surprise": 0.75, "urgency": 0.65,
                "user_importance": 0.55, "business_priority": 0.50,
                "reward_expectation": 0.45, "information_gain": 0.40,
                "relationship_importance": 0.40, "conflict": 0.40,
                "emotional_significance": 0.30, "recency": 0.25,
                "novelty": 0.25, "curiosity": 0.15,
            }
        )
    )


@dataclass(frozen=True, slots=True)
class AttendResult:
    ignited: bool
    coalition: tuple[str, ...]      # targets now conscious
    newly_ignited: tuple[str, ...]
    sustained: tuple[str, ...]
    evicted: tuple[str, ...]        # inhibited/lost incumbents removed from WM
    inhibited: tuple[str, ...]      # competed but not selected
    salience_map: Mapping[str, float]
    seq: int


@dataclass(frozen=True, slots=True)
class AttentionMetricsSnapshot:
    cycles: int
    evaluated: int
    ignitions: int
    empty_ignitions: int        # cycles that ignited nothing (AL11 rest)
    switches: int
    interrupts: int
    inhibitions: int
    distractions: int
    fatigue: float


@dataclass(frozen=True, slots=True)
class AttentionHealthReport:
    healthy: bool
    detail: str
    fatigue: float
    last_coalition_size: int


@runtime_checkable
class WorkingMemoryPort(Protocol):
    """The public Working-Memory surface Attention uses (reads direct, writes via
    the runtime). Attention never touches WM internals (AL16 gate, not owner)."""

    def contents(self, workspace: str | None = None) -> Sequence[Any]: ...
    def read_focus(self, workspace: str | None = None) -> Sequence[Any]: ...
    def ignite(self, target: str, context: Any, **kw: Any) -> str: ...
    def refresh(self, ref: str, context: Any, **kw: Any) -> None: ...
    def evict(self, ref: str, context: Any) -> None: ...
    def broadcast(self, context: Any, workspace: str | None = None) -> Any: ...
