"""Shared helpers for Meta-Cognition tests."""

from __future__ import annotations

from typing import Any

from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel.contracts import CognitiveEvent, SecurityContext
from app.cognitive_kernel.runtime import CognitiveRuntime
from app.cognitive_kernel.state import CognitiveStateManager
from app.cognitive_kernel.engines.metacognition import MetaCognitionEngine, MetaConfig
from app.cognitive_kernel.engines.metacognition.contracts import ObservationWindow


def _boot():
    kernel = Bootstrapper().boot(KernelConfig(identity_name="Atlas", identity_core={"safety_first": True}))
    runtime = CognitiveRuntime(kernel.services())
    runtime.start()
    state = CognitiveStateManager(kernel.services())
    state.start()
    return kernel, runtime, state


def make_meta(**cfg: Any):
    kernel, runtime, state = _boot()
    meta = MetaCognitionEngine(kernel.services(), state, MetaConfig(**cfg) if cfg else None)
    meta.register(kernel, runtime)
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    admin = kernel.services().new_context(security=SecurityContext("dev", "org", frozenset({"state:admin"})))
    return kernel, runtime, state, meta, ctx, admin


def make_meta_wired(**cfg: Any):
    """The full mind under Meta oversight."""
    from app.cognitive_kernel.engines.working_memory import WMConfig, WorkingMemoryEngine
    from app.cognitive_kernel.engines.working_memory.api import WorkingMemoryRuntimeApi
    from app.cognitive_kernel.engines.attention import AttentionEngine, AttentionWMPort
    from app.cognitive_kernel.engines.reasoning import ReasoningEngine, ReasoningWMPort
    from app.cognitive_kernel.engines.prediction import PredictionEngine, RuntimePredictionPort
    from app.cognitive_kernel.engines.executive import ExecutiveEngine

    kernel, runtime, state = _boot()
    wm = WorkingMemoryEngine(kernel.services(), state, WMConfig(focus_capacity=12, periphery_capacity=12))
    wm.register(kernel, runtime)
    wm_api = WorkingMemoryRuntimeApi(runtime)
    att = AttentionEngine(kernel.services(), state, AttentionWMPort(wm, wm_api))
    att.register(kernel, runtime)
    rz = ReasoningEngine(kernel.services(), state, ReasoningWMPort(wm))
    rz.register(kernel, runtime)
    pred = PredictionEngine(kernel.services(), state)
    pred.register(kernel, runtime)
    ex = ExecutiveEngine(kernel.services(), state, prediction_port=RuntimePredictionPort(runtime))
    ex.register(kernel, runtime)
    meta = MetaCognitionEngine(kernel.services(), state, MetaConfig(**cfg) if cfg else None)
    meta.register(kernel, runtime)
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    engines = {"wm": wm, "wm_api": wm_api, "att": att, "rz": rz, "pred": pred, "ex": ex, "meta": meta}
    return kernel, runtime, state, engines, ctx


def emit(services, event_type: str, source: str, **payload: Any) -> None:
    services.events.publish(CognitiveEvent(
        event_id="ev-" + event_type, type=event_type, sequence=services.clock.tick(),
        source=source, correlation_id="test", payload=payload,
    ))


def window(*, event_counts=None, samples=None, health_status=None, health_metrics=None,
           runtime_metrics=None, since=0, until=0) -> ObservationWindow:
    return ObservationWindow(
        window_id="w", since_seq=since, until_seq=until, event_counts=dict(event_counts or {}),
        by_source={}, samples={k: tuple(v) for k, v in (samples or {}).items()},
        health_status=dict(health_status or {}), health_metrics=dict(health_metrics or {}),
        runtime_metrics=dict(runtime_metrics or {}),
    )


def teardown(kernel, runtime, state, *engines) -> None:
    for e in engines:
        try:
            e.stop()
        except Exception:
            pass
    state.stop()
    runtime.stop()
    kernel.shutdown()
