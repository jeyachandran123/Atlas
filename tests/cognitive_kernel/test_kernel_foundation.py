"""Unit + integration tests for the Cognitive Kernel infrastructure."""

from __future__ import annotations

import uuid

import pytest

from app.cognitive_kernel.checkpoint import InMemoryCheckpointStore, seal
from app.cognitive_kernel.clock import MonotonicLogicalClock
from app.cognitive_kernel.constitution import FrozenConstitution
from app.cognitive_kernel.container import KernelContainer
from app.cognitive_kernel.context import ContextFactory
from app.cognitive_kernel.contracts import (
    Checkpoint,
    CognitiveEvent,
    EngineMetadata,
    EventPriority,
    ExecutionBudget,
    ExecutionContext,
    HealthReport,
    HealthStatus,
    KernelState,
    ScheduleKind,
    SecurityContext,
    TraceInfo,
)
from app.cognitive_kernel.errors import (
    ConstitutionViolation,
    DependencyResolutionError,
    EngineRegistrationError,
    LedgerIntegrityError,
    LifecycleError,
)
from app.cognitive_kernel.events import CognitiveEventBus
from app.cognitive_kernel.health import KernelHealthMonitor
from app.cognitive_kernel.identity import (
    IdentityAlreadyEstablished,
    IdentityNotEstablished,
    KernelIdentityProvider,
)
from app.cognitive_kernel.ledger import CognitiveLedger
from app.cognitive_kernel.lifecycle import LifecycleMachine
from app.cognitive_kernel.registry import KernelEngineRegistry
from app.cognitive_kernel.scheduler import KernelScheduler


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        correlation_id="cid",
        identity_id="id",
        security=SecurityContext(principal="p", org_id="o"),
        trace=TraceInfo(trace_id="t", span_id="s"),
    )


def _event(clock: MonotonicLogicalClock, etype: str = "e", priority: EventPriority = EventPriority.NORMAL) -> CognitiveEvent:
    return CognitiveEvent(
        event_id=uuid.uuid4().hex,
        type=etype,
        sequence=clock.tick(),
        source="test",
        correlation_id="cid",
        priority=priority,
    )


# --------------------------------------------------------------------------- #
# DI container
# --------------------------------------------------------------------------- #


class _IBus:  # a contract marker
    pass


def test_container_singleton_vs_transient() -> None:
    c = KernelContainer()
    c.register(_IBus, lambda _c: object(), singleton=True)
    assert c.resolve(_IBus) is c.resolve(_IBus)

    class _IOther:
        pass

    c.register(_IOther, lambda _c: object(), singleton=False)
    assert c.resolve(_IOther) is not c.resolve(_IOther)


def test_container_unregistered_raises() -> None:
    with pytest.raises(DependencyResolutionError):
        KernelContainer().resolve(_IBus)


def test_container_detects_circular_dependency() -> None:
    c = KernelContainer()

    class A:
        pass

    class B:
        pass

    c.register(A, lambda cc: cc.resolve(B))
    c.register(B, lambda cc: cc.resolve(A))
    with pytest.raises(DependencyResolutionError):
        c.resolve(A)


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #


def test_logical_clock_monotonic() -> None:
    clk = MonotonicLogicalClock()
    seq = [clk.tick() for _ in range(5)]
    assert seq == [1, 2, 3, 4, 5]
    assert clk.current() == 5


# --------------------------------------------------------------------------- #
# Event bus
# --------------------------------------------------------------------------- #


def test_event_bus_typed_subscribe_and_filter() -> None:
    clk = MonotonicLogicalClock()
    bus = CognitiveEventBus()
    received: list[str] = []
    bus.subscribe("ping", lambda e: received.append(e.type))
    bus.publish(_event(clk, "ping"))
    bus.publish(_event(clk, "pong"))  # not subscribed
    assert received == ["ping"]


def test_event_bus_priority_filter() -> None:
    clk = MonotonicLogicalClock()
    bus = CognitiveEventBus()
    got: list[int] = []
    # Only accept HIGH or better (<= HIGH).
    bus.subscribe("*", lambda e: got.append(int(e.priority)), max_priority=EventPriority.HIGH)
    bus.publish(_event(clk, "a", EventPriority.INTERRUPT))
    bus.publish(_event(clk, "b", EventPriority.NORMAL))  # filtered out
    assert got == [int(EventPriority.INTERRUPT)]


def test_event_bus_replay_and_unsubscribe() -> None:
    clk = MonotonicLogicalClock()
    bus = CognitiveEventBus()
    seen: list[str] = []
    sub = bus.subscribe("*", lambda e: seen.append(e.type))
    bus.publish(_event(clk, "one"))
    sub.unsubscribe()
    bus.publish(_event(clk, "two"))
    assert seen == ["one"]
    replayed: list[str] = []
    count = bus.replay(lambda e: replayed.append(e.type))
    assert count == 2 and replayed == ["one", "two"]


def test_event_bus_handler_error_isolated() -> None:
    clk = MonotonicLogicalClock()
    errors: list[str] = []
    bus = CognitiveEventBus(on_error=lambda e, h, exc: errors.append(str(exc)))

    def boom(_e: CognitiveEvent) -> None:
        raise RuntimeError("bad handler")

    ok: list[str] = []
    bus.subscribe("*", boom)
    bus.subscribe("*", lambda e: ok.append(e.type))
    bus.publish(_event(clk, "x"))
    assert ok == ["x"] and len(errors) == 1  # bad handler did not break the bus


# --------------------------------------------------------------------------- #
# Ledger
# --------------------------------------------------------------------------- #


def test_ledger_append_verify_and_read() -> None:
    clk = MonotonicLogicalClock()
    ledger = CognitiveLedger()
    assert ledger.verify() and ledger.head() == 0
    e1, e2 = _event(clk), _event(clk)
    ledger.append(e1)
    ledger.append(e2)
    assert ledger.head() == e2.sequence
    assert ledger.verify()
    entries = list(ledger.read(since=e1.sequence))
    assert [x.event.event_id for x in entries] == [e2.event_id]


def test_ledger_rejects_non_monotonic() -> None:
    clk = MonotonicLogicalClock()
    ledger = CognitiveLedger()
    e = _event(clk)
    ledger.append(e)
    with pytest.raises(LedgerIntegrityError):
        ledger.append(e)  # same sequence again


def test_ledger_detects_tampering() -> None:
    clk = MonotonicLogicalClock()
    ledger = CognitiveLedger()
    ledger.append(_event(clk))
    ledger.append(_event(clk))
    assert ledger.verify()
    # White-box tamper: replace a stored entry's event, keeping its old digest.
    original = ledger._entries[0]  # noqa: SLF001 - integrity test
    from app.cognitive_kernel.contracts import LedgerEntry

    forged_event = _event(MonotonicLogicalClock(start=original.sequence - 1), "forged")
    ledger._entries[0] = LedgerEntry(  # noqa: SLF001
        sequence=original.sequence, event=forged_event, digest=original.digest
    )
    assert ledger.verify() is False


# --------------------------------------------------------------------------- #
# Identity (create-once, immutable)
# --------------------------------------------------------------------------- #


def test_identity_create_once_and_immutable() -> None:
    p = KernelIdentityProvider()
    assert not p.is_established()
    with pytest.raises(IdentityNotEstablished):
        p.identity()
    ident = p.establish("Atlas", {"role": "engineering intelligence", "safety_first": True})
    assert p.is_established() and p.identity().identity_id == ident.identity_id
    # Idempotent re-establish with identical core.
    assert p.establish("Atlas", {"role": "engineering intelligence", "safety_first": True}) is ident
    # Any change is refused (DeL1/ExL12).
    with pytest.raises(IdentityAlreadyEstablished):
        p.establish("Atlas", {"role": "different"})
    with pytest.raises(TypeError):
        ident.core["role"] = "hacked"  # core is an immutable mapping


# --------------------------------------------------------------------------- #
# Constitution registry (read-only, versioned)
# --------------------------------------------------------------------------- #


def test_constitution_readonly_versioned() -> None:
    con = FrozenConstitution()
    v = con.version()
    assert v.law_count == len(con.laws()) and v.version == "1.0.0"
    assert con.has("P1") and con.law("P9").phase == "Phase 0"
    assert len(con.laws(phase="Phase 0")) == 12  # the twelve principles
    with pytest.raises(ConstitutionViolation):
        con.law("NOPE")
    # There is no mutation API on the registry.
    assert not hasattr(con, "add") and not hasattr(con, "set")


# --------------------------------------------------------------------------- #
# Engine registry (contracts, topo order, cycles)
# --------------------------------------------------------------------------- #


def test_engine_registry_topological_order() -> None:
    reg = KernelEngineRegistry()
    reg.register(EngineMetadata("A"), lambda s: object())  # type: ignore[arg-type,return-value]
    reg.register(EngineMetadata("B", depends_on=("A",)), lambda s: object())  # type: ignore[arg-type,return-value]
    reg.register(EngineMetadata("C", depends_on=("A", "B")), lambda s: object())  # type: ignore[arg-type,return-value]
    assert list(reg.initialization_order()) == ["A", "B", "C"]


def test_engine_registry_rejects_duplicate_and_cycles() -> None:
    reg = KernelEngineRegistry()
    reg.register(EngineMetadata("A"), lambda s: object())  # type: ignore[arg-type,return-value]
    with pytest.raises(EngineRegistrationError):
        reg.register(EngineMetadata("A"), lambda s: object())  # type: ignore[arg-type,return-value]

    reg2 = KernelEngineRegistry()
    reg2.register(EngineMetadata("X", depends_on=("Y",)), lambda s: object())  # type: ignore[arg-type,return-value]
    reg2.register(EngineMetadata("Y", depends_on=("X",)), lambda s: object())  # type: ignore[arg-type,return-value]
    with pytest.raises(EngineRegistrationError):
        reg2.initialization_order()

    reg3 = KernelEngineRegistry()
    reg3.register(EngineMetadata("P", depends_on=("Q",)), lambda s: object())  # type: ignore[arg-type,return-value]
    with pytest.raises(EngineRegistrationError):
        reg3.initialization_order()  # depends on unregistered Q


# --------------------------------------------------------------------------- #
# Scheduler (all kinds; deterministic drive)
# --------------------------------------------------------------------------- #


def test_scheduler_immediate_and_drain() -> None:
    sched = KernelScheduler()
    hits: list[str] = []
    sched.schedule(lambda c: hits.append("now"), _ctx(), kind=ScheduleKind.IMMEDIATE)
    assert sched.drain() == 1 and hits == ["now"]


def test_scheduler_delayed_not_yet_due() -> None:
    sched = KernelScheduler()
    hits: list[str] = []
    sched.schedule(lambda c: hits.append("later"), _ctx(), kind=ScheduleKind.DELAYED, delay=100.0)
    assert sched.tick() == 0 and hits == []


def test_scheduler_event_driven_fire() -> None:
    sched = KernelScheduler()
    hits: list[str] = []
    handle = sched.schedule(lambda c: hits.append("fired"), _ctx(), kind=ScheduleKind.EVENT_DRIVEN)
    assert sched.tick() == 0  # never time-due
    assert sched.fire(handle.id) is True and hits == ["fired"]


def test_scheduler_periodic_reschedules() -> None:
    sched = KernelScheduler()
    hits: list[int] = []
    h = sched.schedule(lambda c: hits.append(1), _ctx(), kind=ScheduleKind.PERIODIC, interval=1000.0)
    sched.tick()  # runs once, reschedules far in the future
    assert hits == [1]
    assert h.id in [t for t in sched._tasks]  # noqa: SLF001 - still scheduled
    h.cancel()


# --------------------------------------------------------------------------- #
# Health, checkpoint, context, lifecycle
# --------------------------------------------------------------------------- #


def test_health_overall_is_worst_of() -> None:
    hm = KernelHealthMonitor()
    hm.register_probe("a", lambda: HealthReport("a", HealthStatus.HEALTHY))
    hm.register_probe("b", lambda: HealthReport("b", HealthStatus.DEGRADED))
    assert hm.overall() == HealthStatus.DEGRADED
    hm.register_probe("boom", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert hm.overall() == HealthStatus.UNHEALTHY  # failing probe -> unhealthy


def test_checkpoint_roundtrip_and_corruption() -> None:
    store = InMemoryCheckpointStore()
    blob = b"opaque-engine-state"
    cp = Checkpoint(
        checkpoint_id="cp1", owner="working_memory", kind="frame", sequence=7,
        blob=blob, digest=seal(blob),
    )
    store.save(cp)
    assert store.load("cp1").blob == blob
    assert store.latest("working_memory").checkpoint_id == "cp1"
    with pytest.raises(Exception):
        store.save(Checkpoint("bad", "o", "k", 1, b"data", digest="wrong"))


def test_context_factory_stamps_correlation_and_identity() -> None:
    p = KernelIdentityProvider()
    p.establish("Atlas", {})
    factory = ContextFactory(p)
    ctx = factory.new(security=SecurityContext("u", "org"), workspace_id="ws")
    assert ctx.correlation_id and ctx.identity_id == p.identity().identity_id
    child = ctx.child(active_engine="reasoning")
    assert child.active_engine == "reasoning" and child.correlation_id == ctx.correlation_id


def test_lifecycle_legal_and_illegal_transitions() -> None:
    m = LifecycleMachine()
    assert m.state == KernelState.CREATED
    m.transition(KernelState.INITIALIZING)
    m.transition(KernelState.STARTING)
    m.transition(KernelState.RUNNING)
    with pytest.raises(LifecycleError):
        m.transition(KernelState.INITIALIZING)  # illegal from RUNNING
    m.transition(KernelState.STOPPING)
    m.transition(KernelState.STOPPED)
    assert len(m.history) == 5


def test_execution_budget_exhaustion() -> None:
    b = ExecutionBudget(max_steps=3)
    assert not b.exhausted
    b.consume(3)
    assert b.exhausted
