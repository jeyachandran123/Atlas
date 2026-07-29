"""Shared helpers for Development tests."""

from __future__ import annotations

from typing import Any

from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel.contracts import CognitiveEvent, SecurityContext
from app.cognitive_kernel.runtime import CognitiveRuntime
from app.cognitive_kernel.state import CognitiveStateManager
from app.cognitive_kernel.engines.development import DevelopmentConfig, DevelopmentEngine
from app.cognitive_kernel.engines.development.contracts import DevelopmentWindow


def _boot():
    kernel = Bootstrapper().boot(KernelConfig(identity_name="Atlas", identity_core={"safety_first": True}))
    runtime = CognitiveRuntime(kernel.services())
    runtime.start()
    state = CognitiveStateManager(kernel.services())
    state.start()
    return kernel, runtime, state


def make_development(**cfg: Any):
    kernel, runtime, state = _boot()
    dev = DevelopmentEngine(kernel.services(), state, DevelopmentConfig(**cfg) if cfg else None)
    dev.register(kernel, runtime)
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    admin = kernel.services().new_context(security=SecurityContext("dev", "org", frozenset({"state:admin"})))
    return kernel, runtime, state, dev, ctx, admin


def make_development_executive(**cfg: Any):
    from app.cognitive_kernel.engines.executive import ExecutiveEngine

    kernel, runtime, state = _boot()
    ex = ExecutiveEngine(kernel.services(), state)
    ex.register(kernel, runtime)
    dev = DevelopmentEngine(kernel.services(), state, DevelopmentConfig(**cfg) if cfg else None)
    dev.register(kernel, runtime)
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    return kernel, runtime, state, ex, dev, ctx


def emit(services, event_type: str, source: str, **payload: Any) -> None:
    services.events.publish(CognitiveEvent(
        event_id="e-" + str(services.clock.current()), type=event_type, sequence=services.clock.tick(),
        source=source, correlation_id="t", payload=payload))


def strong_reasoning(services, n=20) -> None:
    for _ in range(n):
        emit(services, "reasoning.concluded", "reasoning", confidence=0.9)


def wm_churn(services, n=20) -> None:
    for _ in range(n):
        emit(services, "working_memory.loaded", "working_memory")
        emit(services, "working_memory.evicted", "working_memory")
        emit(services, "working_memory.evicted", "working_memory")


def window(*, rates=None, event_counts=None, state_facts=None, horizon=100) -> DevelopmentWindow:
    return DevelopmentWindow(window_id="w", horizon=horizon, event_counts=dict(event_counts or {}),
                             by_source={}, rates=dict(rates or {}), state_facts=dict(state_facts or {}))


def teardown(kernel, runtime, state, *engines) -> None:
    for e in engines:
        try:
            e.stop()
        except Exception:
            pass
    state.stop()
    runtime.stop()
    kernel.shutdown()
