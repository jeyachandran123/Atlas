"""Shared helpers for Prediction tests."""

from __future__ import annotations

from typing import Any

from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel.contracts import SecurityContext
from app.cognitive_kernel.runtime import CognitiveRuntime
from app.cognitive_kernel.state import CognitiveStateManager
from app.cognitive_kernel.engines.prediction import (
    Driver,
    PredictionConfig,
    PredictionEngine,
    PredictionRequest,
)


def _boot():
    kernel = Bootstrapper().boot(KernelConfig(identity_name="Atlas", identity_core={"safety_first": True}))
    runtime = CognitiveRuntime(kernel.services())
    runtime.start()
    state = CognitiveStateManager(kernel.services())
    state.start()
    return kernel, runtime, state


def make_prediction(**cfg: Any):
    kernel, runtime, state = _boot()
    pred = PredictionEngine(kernel.services(), state, PredictionConfig(**cfg) if cfg else None)
    pred.register(kernel, runtime)
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    admin = kernel.services().new_context(security=SecurityContext("dev", "org", frozenset({"state:admin"})))
    return kernel, runtime, state, pred, ctx, admin


def make_prediction_wired():
    """Prediction + Working Memory (for conscious-context loading)."""
    from app.cognitive_kernel.engines.working_memory import WMConfig, WorkingMemoryEngine
    from app.cognitive_kernel.engines.working_memory.api import WorkingMemoryRuntimeApi

    kernel, runtime, state = _boot()
    wm = WorkingMemoryEngine(kernel.services(), state, WMConfig(focus_capacity=12, periphery_capacity=12))
    wm.register(kernel, runtime)
    wm_api = WorkingMemoryRuntimeApi(runtime)
    pred = PredictionEngine(kernel.services(), state)
    pred.register(kernel, runtime)
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    return kernel, runtime, state, wm, wm_api, pred, ctx


def make_prediction_executive():
    """Prediction wired behind the Executive's risk port (runtime-routed)."""
    from app.cognitive_kernel.engines.executive import ExecutiveEngine
    from app.cognitive_kernel.engines.prediction import RuntimePredictionPort

    kernel, runtime, state = _boot()
    pred = PredictionEngine(kernel.services(), state)
    pred.register(kernel, runtime)
    ex = ExecutiveEngine(kernel.services(), state, prediction_port=RuntimePredictionPort(runtime))
    ex.register(kernel, runtime)
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    return kernel, runtime, state, pred, ex, ctx


def driver(name: str, probability: float, impact: float, **kw: Any) -> Driver:
    return Driver(name=name, probability=probability, impact=impact, **kw)


def request(rid: str, **kw: Any) -> PredictionRequest:
    return PredictionRequest(request_id=rid, **kw)


def teardown(kernel, runtime, state, pred) -> None:
    pred.stop()
    state.stop()
    runtime.stop()
    kernel.shutdown()


def teardown_wired(kernel, runtime, state, *engines) -> None:
    for e in engines:
        e.stop()
    state.stop()
    runtime.stop()
    kernel.shutdown()
