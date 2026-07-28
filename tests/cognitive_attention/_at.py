"""Shared helpers for Attention tests."""

from __future__ import annotations

from typing import Any

from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel.contracts import SecurityContext
from app.cognitive_kernel.runtime import CognitiveRuntime
from app.cognitive_kernel.state import CognitiveStateManager, ObjectType
from app.cognitive_kernel.engines.working_memory import WorkingMemoryEngine
from app.cognitive_kernel.engines.working_memory.api import WorkingMemoryRuntimeApi
from app.cognitive_kernel.engines.attention import (
    AttentionConfig,
    AttentionEngine,
    AttentionWMPort,
    Candidate,
    SalienceVector,
)


def make_attention(focus: int = 4, **att_cfg: Any):
    kernel = Bootstrapper().boot(KernelConfig(identity_name="Atlas", identity_core={"safety_first": True}))
    runtime = CognitiveRuntime(kernel.services())
    runtime.start()
    state = CognitiveStateManager(kernel.services())
    state.start()
    from app.cognitive_kernel.engines.working_memory import WMConfig

    wm = WorkingMemoryEngine(kernel.services(), state, WMConfig(focus_capacity=focus, periphery_capacity=focus))
    wm.register(kernel, runtime)
    port = AttentionWMPort(wm, WorkingMemoryRuntimeApi(runtime))
    cfg = AttentionConfig(coalition_capacity=focus, **att_cfg) if att_cfg else AttentionConfig(coalition_capacity=focus)
    att = AttentionEngine(kernel.services(), state, port, cfg)
    att.register(kernel, runtime)
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    return kernel, runtime, state, wm, att, ctx


def make_targets(state, ctx, n: int, kind=ObjectType.BELIEF) -> list[str]:
    tx = state.begin_transaction(ctx)
    handles = [tx.create(kind, payload={"i": i}) for i in range(n)]
    tx.commit()
    return handles


def cand(target: str, **dims: Any) -> Candidate:
    return Candidate(target=target, vector=SalienceVector(**dims))


def teardown(kernel, runtime, state, wm, att) -> None:
    att.stop()
    wm.stop()
    state.stop()
    runtime.stop()
    kernel.shutdown()
