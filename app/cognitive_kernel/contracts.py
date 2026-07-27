"""The Cognitive Kernel ABI — abstractions only.

This module is the *stable application-binary-interface* of the kernel. It
contains **only** value objects (immutable data) and ``Protocol`` abstractions.
It imports nothing from the rest of the kernel, so it can never participate in a
circular dependency and can be depended upon by every other module (SOLID DIP).

Nothing here performs cognition. These are the contracts that future cognitive
engines (Working Memory, Attention, Reasoning, Executive, Prediction,
Meta-Cognition, Learning, Development) will implement and consume.

Constitutional anchors are noted inline (e.g. ``RL4`` = Runtime Law 4).
"""

from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence, runtime_checkable

# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class KernelState(enum.Enum):
    """Kernel lifecycle states (Phase 2 Runtime; validated transitions only)."""

    CREATED = "created"
    INITIALIZING = "initializing"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class EventPriority(enum.IntEnum):
    """Event priority. Lower value = higher priority (Phase 2.5 broadcast modes)."""

    INTERRUPT = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


class HealthStatus(enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ScheduleKind(enum.Enum):
    IMMEDIATE = "immediate"
    DELAYED = "delayed"
    BACKGROUND = "background"
    PERIODIC = "periodic"
    EVENT_DRIVEN = "event_driven"
    PRIORITY = "priority"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Value objects (immutable)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class TraceInfo:
    """Distributed-tracing coordinates (observability; distributed-ready)."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None


@dataclass(frozen=True, slots=True)
class SecurityContext:
    """Who the operation runs as. Enforcement lives in the platforms, not here."""

    principal: str
    org_id: str
    scopes: frozenset[str] = frozenset()


class CancellationToken:
    """Cooperative, thread-safe cancellation signal.

    Not frozen: it carries mutable runtime state, but the mutation is confined
    to a single boolean flag guarded by a lock (no hidden business state).
    """

    __slots__ = ("_cancelled", "_lock", "_reason")

    def __init__(self) -> None:
        self._cancelled = False
        self._reason: str | None = None
        self._lock = threading.Lock()

    def cancel(self, reason: str | None = None) -> None:
        with self._lock:
            self._cancelled = True
            self._reason = reason

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason


class ExecutionBudget:
    """A bounded allowance for a cognitive operation (P3/P5/ExL4 boundedness).

    Holds immutable limits plus a thread-safe consumed-step meter. The kernel
    itself never *interprets* the budget cognitively; it only tracks and
    reports exhaustion so engines and the (future) executive can act on it.
    """

    __slots__ = ("max_steps", "deadline_monotonic", "_consumed", "_lock")

    def __init__(self, max_steps: int = 0, max_wall_seconds: float | None = None) -> None:
        self.max_steps = max_steps
        self.deadline_monotonic = (
            (time.monotonic() + max_wall_seconds) if max_wall_seconds is not None else None
        )
        self._consumed = 0
        self._lock = threading.Lock()

    def consume(self, steps: int = 1) -> None:
        with self._lock:
            self._consumed += steps

    @property
    def consumed(self) -> int:
        with self._lock:
            return self._consumed

    @property
    def exhausted(self) -> bool:
        with self._lock:
            over_steps = self.max_steps > 0 and self._consumed >= self.max_steps
        over_time = (
            self.deadline_monotonic is not None and time.monotonic() >= self.deadline_monotonic
        )
        return over_steps or over_time


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """The ambient context every cognitive operation executes inside.

    Nothing may execute without a context. It is immutable; derive a child with
    :meth:`child` (e.g. when handing work to a sub-operation).
    """

    correlation_id: str
    identity_id: str
    security: SecurityContext
    trace: TraceInfo
    workspace_id: str | None = None
    conversation_id: str | None = None
    current_goal_id: str | None = None
    active_engine: str | None = None
    cancellation: CancellationToken = field(default_factory=CancellationToken)
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)
    created_at: datetime = field(default_factory=_utcnow)

    def child(self, **overrides: Any) -> "ExecutionContext":
        base: dict[str, Any] = {
            "correlation_id": self.correlation_id,
            "identity_id": self.identity_id,
            "security": self.security,
            "trace": self.trace,
            "workspace_id": self.workspace_id,
            "conversation_id": self.conversation_id,
            "current_goal_id": self.current_goal_id,
            "active_engine": self.active_engine,
            "cancellation": self.cancellation,
            "budget": self.budget,
        }
        base.update(overrides)
        return ExecutionContext(**base)


@dataclass(frozen=True, slots=True)
class CognitiveEvent:
    """A typed message on the cognitive nervous system (Phase 0 C1 / Phase 2.5).

    Events are the *only* means of inter-engine communication. They are
    serialisable (:meth:`to_dict`) to keep future distributed execution open.
    """

    event_id: str
    type: str
    sequence: int  # logical time (RL4); total order across the mind
    source: str
    correlation_id: str
    payload: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    priority: EventPriority = EventPriority.NORMAL
    causation_id: str | None = None  # causal link (Phase 1.5 Ch7)
    context_id: str | None = None
    occurred_at: datetime = field(default_factory=_utcnow)  # wall clock: advisory (RL4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "sequence": self.sequence,
            "source": self.source,
            "correlation_id": self.correlation_id,
            "payload": dict(self.payload),
            "priority": int(self.priority),
            "causation_id": self.causation_id,
            "context_id": self.context_id,
            "occurred_at": self.occurred_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """An immutable, hash-chained record in the append-only ledger (OL4/OL6/RL8)."""

    sequence: int
    event: CognitiveEvent
    digest: str  # sha256 over (previous digest + event); tamper-evident seal
    recorded_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True)
class Identity:
    """The invariant Identity Core (Phase 1 Ch4; DeL1/ExL12/MeL12).

    Created once, never replaced. ``core`` holds the immutable self-model and
    inviolable constraints. It survives restart, recovery, and every engine.
    """

    identity_id: str
    name: str
    core: Mapping[str, Any]
    created_at: datetime
    version: int = 1


@dataclass(frozen=True, slots=True)
class Law:
    """A single constitutional law, indexed by code (e.g. ``P1``, ``RL8``)."""

    code: str
    phase: str
    title: str
    statement: str


@dataclass(frozen=True, slots=True)
class ConstitutionVersion:
    version: str
    frozen_at: str
    law_count: int


@dataclass(frozen=True, slots=True)
class Capability:
    """A faculty or tool discovered from an existing UnityWorks platform."""

    name: str
    kind: str  # "faculty" | "tool" | "platform"
    version: str
    descriptor: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class EngineMetadata:
    """Declarative metadata a future engine registers with (contracts only)."""

    name: str
    version: str = "0.0.0"
    provides: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()  # engine names; drives initialization order
    constitutional_scope: tuple[str, ...] = ()  # law codes this engine must honor


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """An opaque, integrity-sealed snapshot owned by some engine (Phase 1.5 Ch10).

    The kernel persists ``blob`` verbatim and never interprets it.
    """

    checkpoint_id: str
    owner: str
    kind: str
    sequence: int  # ledger position the checkpoint is consistent with
    blob: bytes
    digest: str
    created_at: datetime = field(default_factory=_utcnow)
    lineage: str | None = None  # parent checkpoint id (branching)


@dataclass(frozen=True, slots=True)
class HealthReport:
    component: str
    status: HealthStatus
    detail: str = ""
    metrics: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    checked_at: datetime = field(default_factory=_utcnow)


# --------------------------------------------------------------------------- #
# Abstractions (Protocols) — the kernel service contracts
# --------------------------------------------------------------------------- #


@runtime_checkable
class LogicalClock(Protocol):
    """Authoritative logical time (RL4): a monotonic total order."""

    def tick(self) -> int: ...
    def current(self) -> int: ...


@runtime_checkable
class Container(Protocol):
    """Dependency-injection container. Register/resolve by abstraction only."""

    def register(self, contract: type, factory: Callable[["Container"], Any], *, singleton: bool = True) -> None: ...
    def register_instance(self, contract: type, instance: Any) -> None: ...
    def resolve(self, contract: type) -> Any: ...
    def has(self, contract: type) -> bool: ...


@runtime_checkable
class Subscription(Protocol):
    def unsubscribe(self) -> None: ...


EventHandler = Callable[[CognitiveEvent], None]
EventFilter = Callable[[CognitiveEvent], bool]


@runtime_checkable
class EventBus(Protocol):
    """The cognitive nervous system. Engines communicate ONLY through this."""

    def publish(self, event: CognitiveEvent) -> None: ...
    def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        *,
        predicate: EventFilter | None = None,
        max_priority: EventPriority = EventPriority.BACKGROUND,
    ) -> Subscription: ...
    def replay(self, handler: EventHandler, *, since: int = 0) -> int: ...


@runtime_checkable
class Ledger(Protocol):
    """Append-only, event-sourced cognitive record (OL4/OL6/RL8). No mutation."""

    def append(self, event: CognitiveEvent) -> LedgerEntry: ...
    def read(self, *, since: int = 0, until: int | None = None) -> Iterable[LedgerEntry]: ...
    def head(self) -> int: ...
    def verify(self) -> bool: ...


ScheduledFn = Callable[[ExecutionContext], None]


@runtime_checkable
class ScheduledHandle(Protocol):
    def cancel(self) -> None: ...
    @property
    def id(self) -> str: ...


@runtime_checkable
class Scheduler(Protocol):
    """Execution infrastructure only — performs no cognition."""

    def schedule(
        self,
        fn: ScheduledFn,
        context: ExecutionContext,
        *,
        kind: ScheduleKind = ScheduleKind.IMMEDIATE,
        delay: float = 0.0,
        interval: float | None = None,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> ScheduledHandle: ...
    def tick(self, now: float | None = None) -> int: ...
    def drain(self) -> int: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...


HealthProbe = Callable[[], HealthReport]


@runtime_checkable
class HealthMonitor(Protocol):
    def register_probe(self, name: str, probe: HealthProbe) -> None: ...
    def report(self) -> Mapping[str, HealthReport]: ...
    def overall(self) -> HealthStatus: ...


@runtime_checkable
class CheckpointStore(Protocol):
    """Persistence only — no interpretation of checkpoint contents."""

    def save(self, checkpoint: Checkpoint) -> None: ...
    def load(self, checkpoint_id: str) -> Checkpoint: ...
    def latest(self, owner: str) -> Checkpoint | None: ...
    def list(self, owner: str | None = None) -> Sequence[Checkpoint]: ...


@runtime_checkable
class IdentityProvider(Protocol):
    """Create-once, immutable identity (no ``set``/``replace`` by design)."""

    def establish(self, name: str, core: Mapping[str, Any]) -> Identity: ...
    def identity(self) -> Identity: ...
    def is_established(self) -> bool: ...


@runtime_checkable
class ConstitutionRegistry(Protocol):
    """Read-only registry of frozen constitutional law."""

    def version(self) -> ConstitutionVersion: ...
    def laws(self, *, phase: str | None = None) -> Sequence[Law]: ...
    def law(self, code: str) -> Law: ...
    def has(self, code: str) -> bool: ...


@runtime_checkable
class CapabilityRegistry(Protocol):
    """Integration seam to the existing platforms' Capability Registry.

    The kernel *discovers* faculties here; it never duplicates the registry.
    """

    def register(self, capability: Capability) -> None: ...
    def discover(self) -> Sequence[Capability]: ...
    def get(self, name: str) -> Capability: ...
    def has(self, name: str) -> bool: ...


@runtime_checkable
class Observability(Protocol):
    def logger(self, name: str) -> "StructuredLogger": ...
    def counter(self, name: str, amount: int = 1, **tags: str) -> None: ...
    def gauge(self, name: str, value: float, **tags: str) -> None: ...
    def span(self, name: str, context: ExecutionContext) -> "Span": ...


@runtime_checkable
class StructuredLogger(Protocol):
    def info(self, message: str, **fields: Any) -> None: ...
    def warning(self, message: str, **fields: Any) -> None: ...
    def error(self, message: str, **fields: Any) -> None: ...
    def debug(self, message: str, **fields: Any) -> None: ...


@runtime_checkable
class Span(Protocol):
    def __enter__(self) -> "Span": ...
    def __exit__(self, *exc: Any) -> None: ...
    def set(self, key: str, value: Any) -> None: ...


@runtime_checkable
class CognitiveEngine(Protocol):
    """The contract EVERY future cognitive engine implements.

    This phase implements NO engine — only this contract and the registry that
    will host them. Engines receive :class:`KernelServices` at ``initialize``
    (dependency injection); they never instantiate one another (P1/P6/OL8).
    """

    @property
    def metadata(self) -> EngineMetadata: ...
    def initialize(self, services: "KernelServices") -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health(self) -> HealthReport: ...


EngineFactory = Callable[["KernelServices"], CognitiveEngine]


@runtime_checkable
class EngineRegistry(Protocol):
    """Registry of engine *contracts* (never concrete singletons)."""

    def register(self, metadata: EngineMetadata, factory: EngineFactory) -> None: ...
    def metadata(self, name: str) -> EngineMetadata: ...
    def factory(self, name: str) -> EngineFactory: ...
    def names(self) -> Sequence[str]: ...
    def initialization_order(self) -> Sequence[str]: ...


@dataclass(frozen=True, slots=True)
class KernelServices:
    """The infrastructure bundle injected into every engine at ``initialize``.

    This is the sole surface through which an engine touches the kernel. It
    exposes abstractions only — the engine can no more reach kernel internals
    than a user-space process can touch kernel memory directly.
    """

    clock: LogicalClock
    events: EventBus
    ledger: Ledger
    scheduler: Scheduler
    health: HealthMonitor
    checkpoints: CheckpointStore
    identity: IdentityProvider
    constitution: ConstitutionRegistry
    capabilities: CapabilityRegistry
    observability: Observability
    container: Container
    new_context: Callable[..., ExecutionContext]
