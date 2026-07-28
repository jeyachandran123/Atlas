"""Shared helpers for Working Memory tests."""

from __future__ import annotations

from typing import Any

from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel.contracts import SecurityContext
from app.cognitive_kernel.runtime import CognitiveRuntime
from app.cognitive_kernel.state import CognitiveStateManager, ObjectType
from app.cognitive_kernel.engines.working_memory import WMConfig, WorkingMemoryEngine


def make_wm(focus: int = 4, periphery: int = 3, **cfg: Any):
    kernel = Bootstrapper().boot(KernelConfig(identity_name="Atlas", identity_core={"safety_first": True}))
    runtime = CognitiveRuntime(kernel.services())
    runtime.start()
    state = CognitiveStateManager(kernel.services())
    state.start()
    wm = WorkingMemoryEngine(
        kernel.services(), state, WMConfig(focus_capacity=focus, periphery_capacity=periphery, **cfg)
    )
    wm.register(kernel, runtime)
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    return kernel, runtime, state, wm, ctx


def make_targets(state, ctx, n: int, kind=ObjectType.BELIEF) -> list[str]:
    tx = state.begin_transaction(ctx)
    handles = [tx.create(kind, payload={"i": i}) for i in range(n)]
    tx.commit()
    return handles


def tick(kernel, n: int) -> None:
    for _ in range(n):
        kernel.services().clock.tick()


def idx(state, slot) -> int:
    return state.get(slot.target).payload["i"]


def teardown(kernel, runtime, state, wm) -> None:
    wm.stop()
    state.stop()
    runtime.stop()
    kernel.shutdown()
