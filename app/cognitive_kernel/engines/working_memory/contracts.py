"""Working Memory ABI — enums, value objects, config, and the engine's API.

WM holds *references* (handles) with ephemeral activation. Capacity is bounded
by constitution (Cowan focus + small periphery). These are value objects and
Protocols only.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from ...contracts import ExecutionContext


class Zone(enum.Enum):
    """Where a reference sits in the bounded workspace (Phase 2.5 §5.5)."""

    FOCUS = "focus"          # the ~4 conscious chunks
    PERIPHERY = "periphery"  # the preconscious fringe (activated but not conscious)
    BINDING = "binding"      # a bound chunk (episodic buffer)


class WorkspaceKind(enum.Enum):
    ROOT = "root"
    GOAL = "goal"
    TASK = "task"
    BELIEF = "belief"
    CONVERSATION = "conversation"
    DOCUMENT = "document"
    SIMULATION = "simulation"  # isolated (Phase 6 PrL8)
    NESTED = "nested"


@dataclass(frozen=True, slots=True)
class WMConfig:
    """Bounded capacity (constitutionally enforced, CL1/P3). Evolvable only by the
    Development hook (gated)."""

    focus_capacity: int = 4       # Cowan focus of attention
    periphery_capacity: int = 3   # activated fringe
    decay_rate: float = 0.15      # per logical step (exponential decay)
    min_activation: float = 0.05  # expiration threshold
    refresh_boost: float = 0.5


@dataclass(frozen=True, slots=True)
class Slot:
    """An immutable view of one Working Memory reference (backed by an R4 object)."""

    handle: str          # the WM-reference object handle (in Cognitive State R4)
    target: str          # the referenced cognitive object (a handle, NEVER a copy)
    workspace: str
    zone: Zone
    base_activation: float
    loaded_seq: int
    pinned: bool
    chunk_of: str | None
    is_chunk: bool
    salience: float
    confidence: float | None

    def effective_activation(self, now: int, decay_rate: float) -> float:
        """Deterministic computed decay (WM activation is ephemeral, §5.6)."""
        if self.pinned:
            return max(self.base_activation, 1.0)
        dt = max(0, now - self.loaded_seq)
        return self.base_activation * math.exp(-decay_rate * dt)


@dataclass(frozen=True, slots=True)
class WorkspaceInfo:
    id: str
    kind: WorkspaceKind
    parent: str | None
    isolated: bool
    created_seq: int


@dataclass(frozen=True, slots=True)
class WMSnapshot:
    workspace: str
    seq: int
    slots: tuple[Slot, ...]


@dataclass(frozen=True, slots=True)
class WMMetricsSnapshot:
    loads: int
    evictions: int
    overflow_evictions: int
    refreshes: int
    chunks: int
    consolidations: int
    context_switches: int
    simulations: int
    workspaces: int
    focus_used: int
    periphery_used: int


@dataclass(frozen=True, slots=True)
class WMHealthReport:
    healthy: bool
    detail: str
    focus_used: int
    focus_capacity: int
    workspaces: int


@runtime_checkable
class WorkingMemoryApi(Protocol):
    """The surface future engines use — every mutation routed through the Runtime."""

    def load(self, target: str, context: ExecutionContext, **kw: Any) -> str: ...
    def refresh(self, ref: str, context: ExecutionContext, **kw: Any) -> None: ...
    def evict(self, ref: str, context: ExecutionContext) -> None: ...
    def read_focus(self, workspace: str | None = None) -> Sequence[Slot]: ...
