"""The Cognitive Runtime ABI — abstractions only.

Value objects (immutable) and ``Protocol`` contracts for the runtime layer. It
imports the kernel's ABI (``..contracts``) but nothing from concrete runtime
modules, so it can never be part of a circular dependency.

The runtime performs NO cognition. These contracts describe how the runtime
*coordinates* engines; what engines *do* is entirely opaque to the runtime.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from ..contracts import (
    EventPriority,
    ExecutionContext,
    HealthStatus,
    SecurityContext,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class ExecutionState(enum.Enum):
    """Lifecycle of a single execution (validated transitions, RL3)."""

    CREATED = "created"
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    EXECUTING = "executing"
    WAITING = "waiting"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    RECOVERED = "recovered"


TERMINAL_STATES = frozenset(
    {ExecutionState.COMPLETED, ExecutionState.FAILED, ExecutionState.CANCELLED}
)


class RuntimeLifecycleState(enum.Enum):
    """The Runtime Manager's own lifecycle."""

    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    DRAINING = "draining"
    STOPPED = "stopped"


class RuntimeHealth(enum.Enum):
    HEALTHY = "healthy"
    BUSY = "busy"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    UNAVAILABLE = "unavailable"


class QueueKind(enum.Enum):
    IMMEDIATE = "immediate"
    PRIORITY = "priority"
    BACKGROUND = "background"
    DEFERRED = "deferred"
    PERIODIC = "periodic"


class RecoveryStrategy(enum.Enum):
    NONE = "none"
    RETRY = "retry"
    CHECKPOINT = "checkpoint"
    REPLAY = "replay"


# --------------------------------------------------------------------------- #
# Value objects (immutable)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class BudgetSpec:
    """A multi-dimensional budget request. ``None`` = unbounded for that axis.

    The runtime (not the engine) enforces these (P3/P5).
    """

    time_seconds: float | None = None
    steps: int | None = None
    memory: int | None = None
    tokens: int | None = None  # future
    tools: int | None = None  # future
    simulations: int | None = None  # future


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    """Runtime policy governing an execution (configurable; loaded by runtime)."""

    name: str = "default"
    priority: EventPriority = EventPriority.NORMAL
    max_attempts: int = 1  # retry budget
    retry_backoff_seconds: float = 0.0
    timeout_seconds: float | None = None
    isolated: bool = False  # isolated (fresh) context vs inherited
    recovery: RecoveryStrategy = RecoveryStrategy.NONE
    cancel_propagates: bool = True  # cancel parent -> cancel children


RuntimeTask = Callable[[ExecutionContext], Any]


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    """An immutable request to execute cognitive work.

    Either supply ``task`` (a callable the runtime runs) or ``engine`` +
    ``operation`` (routed to a registered :class:`ExecutableEngine`). The runtime
    never inspects the semantics of the work.
    """

    engine: str = "anonymous"
    operation: str = "execute"
    payload: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    task: RuntimeTask | None = None
    priority: EventPriority = EventPriority.NORMAL
    kind: QueueKind = QueueKind.IMMEDIATE
    budget: BudgetSpec = field(default_factory=BudgetSpec)
    policy: str = "default"
    parent_id: str | None = None
    correlation_id: str | None = None
    security: SecurityContext | None = None
    delay_seconds: float = 0.0  # for DEFERRED/PERIODIC
    workspace_id: str | None = None
    conversation_id: str | None = None


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    time_seconds: float
    steps: int
    memory: int
    tokens: int
    tools: int
    simulations: int


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    execution_id: str
    engine: str
    state: ExecutionState
    value: Any = None
    error: str | None = None
    attempts: int = 1
    queued_at: int = 0  # logical time
    started_at: int = 0
    finished_at: int = 0
    duration_seconds: float = 0.0
    queue_seconds: float = 0.0
    budget: BudgetUsage | None = None


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    """An immutable, serialisable record of where an execution stands.

    The runtime (not the engine) knows this. It is the basis for resumable
    executions and checkpoints (RL8).
    """

    execution_id: str
    engine: str
    operation: str
    state: ExecutionState
    attempts: int
    parent_id: str | None
    correlation_id: str
    ledger_head: int
    created_at: str = field(default_factory=lambda: _utcnow().isoformat())


@dataclass(frozen=True, slots=True)
class RuntimeMetricsSnapshot:
    submitted: int
    completed: int
    failed: int
    cancelled: int
    timed_out: int
    recovered: int
    retries: int
    active: int
    queued: int
    throughput: float  # completed per second (rolling)
    avg_duration_seconds: float
    avg_queue_seconds: float
    failure_rate: float
    cancellation_rate: float
    recovery_rate: float
    budget_utilization: float
    engine_utilization: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class RuntimeHealthReport:
    status: RuntimeHealth
    lifecycle: RuntimeLifecycleState
    detail: str
    queue_depth: int
    active_executions: int
    recovering: int
    kernel_health: HealthStatus
    checked_at: datetime = field(default_factory=_utcnow)


# --------------------------------------------------------------------------- #
# Abstractions
# --------------------------------------------------------------------------- #


@runtime_checkable
class ExecutableEngine(Protocol):
    """The contract by which the runtime executes a registered engine's work.

    A future cognitive engine implements this (in addition to the kernel's
    ``CognitiveEngine`` lifecycle contract). The runtime calls ``execute`` and
    treats the return value as opaque (it performs no cognition itself).
    """

    def execute(self, operation: str, payload: Mapping[str, Any], context: ExecutionContext) -> Any: ...


@runtime_checkable
class ExecutionHandle(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def state(self) -> ExecutionState: ...
    def result(self, timeout: float | None = None) -> ExecutionResult: ...


@runtime_checkable
class RuntimeApi(Protocol):
    """The internal-only surface engines use. No engine calls another engine;
    everything flows through this + the event bus.
    """

    def submit(self, request: ExecutionRequest) -> ExecutionHandle: ...
    def cancel(self, execution_id: str, reason: str | None = None) -> bool: ...
    def status(self, execution_id: str) -> ExecutionState: ...
