"""End-to-end kernel tests: boot, host an engine, record, recover, shut down."""

from __future__ import annotations

import pytest

from app.cognitive_kernel import (
    Bootstrapper,
    CognitiveKernel,
    KernelConfig,
    KernelState,
)
from app.cognitive_kernel.contracts import (
    CognitiveEvent,
    EngineMetadata,
    HealthReport,
    HealthStatus,
    KernelServices,
    SecurityContext,
)
from app.cognitive_kernel.errors import BootstrapError, LifecycleError


def _config(**kw) -> KernelConfig:
    base = dict(identity_name="Atlas", identity_core={"role": "engineering intelligence", "safety_first": True})
    base.update(kw)
    return KernelConfig(**base)


def _ctx(kernel: CognitiveKernel):
    return kernel.services().new_context(security=SecurityContext("user", "org"))


# --------------------------------------------------------------------------- #
# A trivial faculty engine used only to prove the kernel *hosts* engines and
# that engines communicate ONLY via the event bus (never direct calls).
# --------------------------------------------------------------------------- #


class EchoEngine:
    """On 'ping' it emits 'pong' — purely via the bus. Performs no cognition."""

    def __init__(self) -> None:
        self._services: KernelServices | None = None
        self._sub = None
        self._started = False

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(name="echo", version="1.0", provides=("echo",))

    def initialize(self, services: KernelServices) -> None:
        self._services = services

        def on_ping(event: CognitiveEvent) -> None:
            s = self._services
            assert s is not None
            s.events.publish(
                CognitiveEvent(
                    event_id="pong-" + event.event_id,
                    type="pong",
                    sequence=s.clock.tick(),
                    source="echo",
                    correlation_id=event.correlation_id,
                    causation_id=event.event_id,
                )
            )

        self._sub = services.events.subscribe("ping", on_ping)

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        if self._sub is not None:
            self._sub.unsubscribe()
        self._started = False

    def health(self) -> HealthReport:
        status = HealthStatus.HEALTHY if self._started else HealthStatus.DEGRADED
        return HealthReport("engine.echo", status)


def test_boot_reaches_running_and_establishes_identity() -> None:
    kernel = Bootstrapper().boot(_config())
    try:
        assert kernel.state == KernelState.RUNNING
        assert kernel.services().identity.is_established()
        assert kernel.services().identity.identity().name == "Atlas"
        assert kernel.services().ledger.verify()
        # Constitution is loaded and read-only.
        assert kernel.services().constitution.version().law_count > 0
        # Health overall is healthy right after boot.
        assert kernel.services().health.overall() == HealthStatus.HEALTHY
    finally:
        kernel.shutdown()
        assert kernel.state == KernelState.STOPPED


def test_engine_hosting_and_bus_only_communication_recorded_to_ledger() -> None:
    kernel = Bootstrapper().boot(_config())
    try:
        kernel.register_engine(EchoEngine().metadata, lambda services: EchoEngine())
        kernel.start_engines()
        before = kernel.services().ledger.head()
        kernel.emit("ping", {"n": 1}, _ctx(kernel), source="test")
        after = kernel.services().ledger.head()
        # ping recorded, echo published pong via the bus, pong recorded.
        assert after >= before + 2
        types = [e.event.type for e in kernel.services().ledger.read(since=before)]
        assert "ping" in types and "pong" in types
        # engine health probe is registered and reports healthy
        assert kernel.services().health.report()["engine.echo"].status == HealthStatus.HEALTHY
    finally:
        kernel.shutdown()


def test_recovery_replays_the_ledger_deterministically() -> None:
    kernel = Bootstrapper().boot(_config())
    try:
        ctx = _ctx(kernel)
        for i in range(4):
            kernel.emit("thought", {"i": i}, ctx, source="test")
        recovery = kernel.recovery()
        recovery.verify_integrity()  # integrity gate passes
        rebuilt: list[str] = []
        count = recovery.replay(lambda e: rebuilt.append(e.type))
        assert count == kernel.services().ledger.head()  # every event replayed
        assert rebuilt.count("thought") == 4
    finally:
        kernel.shutdown()


def test_boot_fails_safely_on_bad_config() -> None:
    with pytest.raises(BootstrapError):
        Bootstrapper().boot(_config(identity_name=""))


def test_illegal_transition_after_running() -> None:
    kernel = Bootstrapper().boot(_config())
    try:
        with pytest.raises(LifecycleError):
            kernel.lifecycle.transition(KernelState.INITIALIZING)
    finally:
        kernel.shutdown()


def test_shutdown_is_idempotent() -> None:
    kernel = Bootstrapper().boot(_config())
    kernel.shutdown()
    kernel.shutdown()  # no error the second time
    assert kernel.state == KernelState.STOPPED
