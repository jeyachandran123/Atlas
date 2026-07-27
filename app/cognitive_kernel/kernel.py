"""The Cognitive Kernel — the Mind's execution environment.

The kernel performs **no cognition**. It provides the runtime infrastructure in
which every future cognitive engine will live: a dependency-injection container,
the nervous system (event bus), the append-only ledger, logical time, the
scheduler, identity, the constitution registry, capability discovery, the engine
registry, health, checkpoints, recovery, and observability.

Nothing initializes itself; the kernel bootstraps everything (see
:mod:`.bootstrap`). Engines self-register (contracts only) and are resolved by
the kernel via DI, wired together *only* through the event bus (P1/P6/OL8).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from . import contracts as C
from .checkpoint import InMemoryCheckpointStore
from .clock import MonotonicLogicalClock
from .constitution import FrozenConstitution
from .container import KernelContainer
from .context import ContextFactory
from .errors import LifecycleError
from .events import CognitiveEventBus
from .health import KernelHealthMonitor
from .identity import KernelIdentityProvider
from .ledger import CognitiveLedger
from .lifecycle import LifecycleMachine
from .observability import KernelObservability
from .recovery import RecoveryManager
from .registry import KernelCapabilityRegistry, KernelEngineRegistry
from .scheduler import KernelScheduler

KERNEL_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class KernelConfig:
    """Boot configuration (the 'Load Configuration' step)."""

    identity_name: str
    identity_core: Mapping[str, Any] = field(default_factory=dict)
    scheduler_tick: float = 0.01
    run_scheduler_thread: bool = False


class CognitiveKernel:
    """The root object. Holds infrastructure; hosts engines; owns lifecycle."""

    def __init__(self, config: KernelConfig, container: C.Container | None = None) -> None:
        self._config = config
        self._container: C.Container = container or KernelContainer()
        self._lifecycle = LifecycleMachine()
        self._obs = KernelObservability()
        self._log = self._obs.logger("kernel")
        self._services: C.KernelServices | None = None
        self._engines: dict[str, C.CognitiveEngine] = {}
        self._bridge: C.Subscription | None = None
        self._lock = threading.RLock()

    # --- lifecycle -------------------------------------------------------- #

    @property
    def state(self) -> C.KernelState:
        return self._lifecycle.state

    @property
    def container(self) -> C.Container:
        return self._container

    @property
    def lifecycle(self) -> LifecycleMachine:
        return self._lifecycle

    @property
    def observability(self) -> KernelObservability:
        return self._obs

    def services(self) -> C.KernelServices:
        if self._services is None:
            raise LifecycleError("Kernel services requested before initialization.")
        return self._services

    # --- construction of the infrastructure graph ------------------------ #

    def register_infrastructure(self) -> None:
        """Register default infra factories in the container (DI, no self-init)."""
        c = self._container
        c.register_instance(C.LogicalClock, MonotonicLogicalClock())
        c.register_instance(C.Observability, self._obs)
        c.register(C.EventBus, lambda _c: CognitiveEventBus(on_error=self._on_bus_error))
        c.register(C.Ledger, lambda _c: CognitiveLedger())
        c.register(
            C.Scheduler,
            lambda _c: KernelScheduler(tick_interval=self._config.scheduler_tick),
        )
        c.register(C.HealthMonitor, lambda _c: KernelHealthMonitor())
        c.register(C.CheckpointStore, lambda _c: InMemoryCheckpointStore())
        c.register(C.IdentityProvider, lambda _c: KernelIdentityProvider())
        c.register(C.ConstitutionRegistry, lambda _c: FrozenConstitution())
        c.register(C.CapabilityRegistry, lambda _c: KernelCapabilityRegistry())
        c.register(C.EngineRegistry, lambda _c: KernelEngineRegistry())

    def build_services(self) -> C.KernelServices:
        """Resolve infrastructure and assemble the injectable service bundle."""
        c = self._container
        identity = c.resolve(C.IdentityProvider)
        ctx_factory = ContextFactory(identity)
        services = C.KernelServices(
            clock=c.resolve(C.LogicalClock),
            events=c.resolve(C.EventBus),
            ledger=c.resolve(C.Ledger),
            scheduler=c.resolve(C.Scheduler),
            health=c.resolve(C.HealthMonitor),
            checkpoints=c.resolve(C.CheckpointStore),
            identity=identity,
            constitution=c.resolve(C.ConstitutionRegistry),
            capabilities=c.resolve(C.CapabilityRegistry),
            observability=self._obs,
            container=c,
            new_context=ctx_factory.new,
        )
        self._services = services
        return services

    def wire_ledger_bridge(self) -> None:
        """The nervous-system → record bridge: every bus event is recorded (OL6).

        Communication happens via the bus; the ledger is the append-only record.
        Replay does not go through the bus, so history is never double-recorded.
        """
        s = self.services()

        def record(event: C.CognitiveEvent) -> None:
            s.ledger.append(event)

        self._bridge = s.events.subscribe("*", record)

    def register_health_probes(self) -> None:
        s = self.services()

        def ledger_probe() -> C.HealthReport:
            ok = s.ledger.verify()
            return C.HealthReport(
                component="ledger",
                status=C.HealthStatus.HEALTHY if ok else C.HealthStatus.UNHEALTHY,
                detail="hash-chain intact" if ok else "INTEGRITY FAILURE",
                metrics={"head": float(s.ledger.head())},
            )

        def identity_probe() -> C.HealthReport:
            ok = s.identity.is_established()
            return C.HealthReport(
                component="identity",
                status=C.HealthStatus.HEALTHY if ok else C.HealthStatus.UNHEALTHY,
                detail="established" if ok else "not established",
            )

        def runtime_probe() -> C.HealthReport:
            healthy = self._lifecycle.state in (C.KernelState.RUNNING,)
            status = C.HealthStatus.HEALTHY if healthy else C.HealthStatus.DEGRADED
            return C.HealthReport(component="runtime", status=status, detail=self._lifecycle.state.value)

        s.health.register_probe("ledger", ledger_probe)
        s.health.register_probe("identity", identity_probe)
        s.health.register_probe("runtime", runtime_probe)

    def establish_identity(self) -> C.Identity:
        return self.services().identity.establish(
            self._config.identity_name, self._config.identity_core
        )

    def recovery(self) -> RecoveryManager:
        s = self.services()
        return RecoveryManager(s.ledger, s.checkpoints, s.identity)

    # --- engine hosting (infra to host future engines; hosts none yet) ---- #

    def engine_registry(self) -> C.EngineRegistry:
        return self._container.resolve(C.EngineRegistry)

    def register_engine(self, metadata: C.EngineMetadata, factory: C.EngineFactory) -> None:
        self.engine_registry().register(metadata, factory)

    def start_engines(self) -> None:
        """Resolve and start engines in dependency order (none registered → no-op)."""
        registry = self.engine_registry()
        services = self.services()
        for name in registry.initialization_order():
            factory = registry.factory(name)
            engine = factory(services)
            engine.initialize(services)
            engine.start()
            self._engines[name] = engine
            services.health.register_probe(f"engine.{name}", engine.health)
            self._log.info("engine started", engine=name)

    def stop_engines(self) -> None:
        for name in reversed(list(self._engines)):
            try:
                self._engines[name].stop()
            except Exception as exc:  # graceful: one engine's failure must not block shutdown
                self._log.error("engine stop failed", engine=name, error=repr(exc))
        self._engines.clear()

    # --- degradation / recovery transitions ------------------------------ #

    def to_degraded(self, reason: str) -> None:
        self._lifecycle.transition(C.KernelState.DEGRADED)
        self._log.warning("kernel degraded", reason=reason)

    def begin_recovery(self) -> None:
        self._lifecycle.transition(C.KernelState.RECOVERING)

    def resume(self) -> None:
        self._lifecycle.transition(C.KernelState.RUNNING)

    # --- graceful shutdown ------------------------------------------------ #

    def shutdown(self) -> None:
        with self._lock:
            if self._lifecycle.state in (C.KernelState.STOPPED,):
                return
            self._lifecycle.transition(C.KernelState.STOPPING)
            self.stop_engines()
            if self._services is not None:
                try:
                    self._services.scheduler.stop()
                except Exception:  # best-effort during shutdown
                    pass
            if self._bridge is not None:
                self._bridge.unsubscribe()
                self._bridge = None
            self._lifecycle.transition(C.KernelState.STOPPED)
            self._log.info("kernel stopped")

    # --- helpers ---------------------------------------------------------- #

    def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        context: C.ExecutionContext,
        *,
        source: str = "kernel",
        priority: C.EventPriority = C.EventPriority.NORMAL,
        causation_id: str | None = None,
    ) -> C.CognitiveEvent:
        """Stamp logical time and publish (recorded to the ledger by the bridge)."""
        s = self.services()
        event = C.CognitiveEvent(
            event_id=uuid.uuid4().hex,
            type=event_type,
            sequence=s.clock.tick(),
            source=source,
            correlation_id=context.correlation_id,
            payload=payload,
            priority=priority,
            causation_id=causation_id,
            context_id=context.correlation_id,
        )
        s.events.publish(event)
        return event

    def _on_bus_error(self, event: C.CognitiveEvent, handler: Any, exc: BaseException) -> None:
        self._log.error("event handler failed", event_type=event.type, error=repr(exc))
        self._obs.counter("bus.handler_error")
