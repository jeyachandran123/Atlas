"""Shared helpers for Executive tests."""

from __future__ import annotations

from typing import Any

from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel.contracts import SecurityContext
from app.cognitive_kernel.runtime import CognitiveRuntime
from app.cognitive_kernel.state import CognitiveStateManager
from app.cognitive_kernel.engines.executive import ExecutiveConfig, ExecutiveEngine, ReasoningProposal


def _boot():
    kernel = Bootstrapper().boot(KernelConfig(identity_name="Atlas", identity_core={"safety_first": True}))
    runtime = CognitiveRuntime(kernel.services())
    runtime.start()
    state = CognitiveStateManager(kernel.services())
    state.start()
    return kernel, runtime, state


def make_executive(**cfg: Any):
    """A standalone executive (no faculties wired — coordination degrades gracefully)."""
    kernel, runtime, state = _boot()
    ex = ExecutiveEngine(kernel.services(), state, ExecutiveConfig(**cfg) if cfg else None)
    ex.register(kernel, runtime)
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    admin = kernel.services().new_context(security=SecurityContext("dev", "org", frozenset({"state:admin"})))
    return kernel, runtime, state, ex, ctx, admin


def make_executive_wired(**cfg: Any):
    """The full governed stack: WM + Attention + Reasoning + Executive."""
    from app.cognitive_kernel.engines.working_memory import WMConfig, WorkingMemoryEngine
    from app.cognitive_kernel.engines.working_memory.api import WorkingMemoryRuntimeApi
    from app.cognitive_kernel.engines.attention import AttentionEngine, AttentionWMPort
    from app.cognitive_kernel.engines.reasoning import ReasoningEngine, ReasoningWMPort

    kernel, runtime, state = _boot()
    wm = WorkingMemoryEngine(kernel.services(), state, WMConfig(focus_capacity=12, periphery_capacity=12))
    wm.register(kernel, runtime)
    wm_api = WorkingMemoryRuntimeApi(runtime)
    att = AttentionEngine(kernel.services(), state, AttentionWMPort(wm, wm_api))
    att.register(kernel, runtime)
    rz = ReasoningEngine(kernel.services(), state, ReasoningWMPort(wm))
    rz.register(kernel, runtime)
    ex = ExecutiveEngine(kernel.services(), state, ExecutiveConfig(**cfg) if cfg else None)
    ex.register(kernel, runtime)
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    return kernel, runtime, state, wm, wm_api, att, rz, ex, ctx


def proposal(pid: str, statement: str, confidence: float, **kw: Any) -> ReasoningProposal:
    return ReasoningProposal(proposal_id=pid, statement=statement, confidence=confidence, **kw)


def teardown(kernel, runtime, state, ex) -> None:
    ex.stop()
    state.stop()
    runtime.stop()
    kernel.shutdown()


def teardown_wired(kernel, runtime, state, wm, att, rz, ex) -> None:
    ex.stop(); rz.stop(); att.stop(); wm.stop(); state.stop(); runtime.stop(); kernel.shutdown()
