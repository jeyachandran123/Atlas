"""Shared helpers for Reasoning tests."""

from __future__ import annotations

from typing import Any

from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel.contracts import SecurityContext
from app.cognitive_kernel.runtime import CognitiveRuntime
from app.cognitive_kernel.state import CognitiveStateManager, ObjectType
from app.cognitive_kernel.engines.working_memory import WMConfig, WorkingMemoryEngine
from app.cognitive_kernel.engines.working_memory.api import WorkingMemoryRuntimeApi
from app.cognitive_kernel.engines.reasoning import (
    ReasoningConfig,
    ReasoningEngine,
    ReasoningWMPort,
)
from app.cognitive_kernel.engines.reasoning.inference import CONTRADICTION


def make_reasoning(focus: int = 16, **cfg: Any):
    kernel = Bootstrapper().boot(KernelConfig(identity_name="Atlas", identity_core={"safety_first": True}))
    runtime = CognitiveRuntime(kernel.services())
    runtime.start()
    state = CognitiveStateManager(kernel.services())
    state.start()
    wm = WorkingMemoryEngine(kernel.services(), state, WMConfig(focus_capacity=focus, periphery_capacity=focus))
    wm.register(kernel, runtime)
    wm_api = WorkingMemoryRuntimeApi(runtime)
    rconf = ReasoningConfig(**cfg) if cfg else ReasoningConfig()
    rz = ReasoningEngine(kernel.services(), state, ReasoningWMPort(wm), rconf)
    rz.register(kernel, runtime)
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    return kernel, runtime, state, wm, wm_api, rz, ctx


# --- conscious-content builders (each returns a State handle) --------------- #


def assertion(state, ctx, statement, *, negated=False, confidence=1.0, reliability=1.0,
              kind=ObjectType.EVIDENCE) -> str:
    tx = state.begin_transaction(ctx)
    h = tx.create(kind, payload={"statement": statement, "negated": negated, "reliability": reliability},
                  confidence=confidence)
    tx.commit()
    return h


def rule(state, ctx, antecedents, consequent, *, negated=False, reliability=1.0) -> str:
    tx = state.begin_transaction(ctx)
    h = tx.create(ObjectType.CONSTRAINT, payload={
        "rule": {"if": list(antecedents), "then": consequent, "negated": negated, "reliability": reliability}
    })
    tx.commit()
    return h


def forbid(state, ctx, antecedents) -> str:
    return rule(state, ctx, antecedents, CONTRADICTION)


def cause(state, ctx, c, e, *, strength=1.0) -> str:
    tx = state.begin_transaction(ctx)
    h = tx.create(ObjectType.BELIEF, payload={"causes": {"cause": c, "effect": e, "strength": strength}})
    tx.commit()
    return h


def analogy(state, ctx, relation, conclusion, *, negated=False, strength=1.0) -> str:
    tx = state.begin_transaction(ctx)
    h = tx.create(ObjectType.BELIEF, payload={
        "analogy": {"relation": relation, "conclusion": conclusion, "negated": negated, "strength": strength}
    })
    tx.commit()
    return h


def conscious(wm_api, handles, ctx) -> None:
    for h in handles:
        wm_api.load(h, ctx)


def teardown(kernel, runtime, state, wm, rz) -> None:
    rz.stop()
    wm.stop()
    state.stop()
    runtime.stop()
    kernel.shutdown()
