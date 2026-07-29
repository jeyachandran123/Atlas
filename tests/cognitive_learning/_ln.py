"""Shared helpers for Learning tests."""

from __future__ import annotations

from typing import Any

from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel.contracts import CognitiveEvent, SecurityContext
from app.cognitive_kernel.runtime import CognitiveRuntime
from app.cognitive_kernel.state import CognitiveStateManager, ObjectStatus, ObjectType, Region
from app.cognitive_kernel.engines.learning import LearningConfig, LearningEngine


def _boot():
    kernel = Bootstrapper().boot(KernelConfig(identity_name="Atlas", identity_core={"safety_first": True}))
    runtime = CognitiveRuntime(kernel.services())
    runtime.start()
    state = CognitiveStateManager(kernel.services())
    state.start()
    return kernel, runtime, state


def make_learning(**cfg: Any):
    kernel, runtime, state = _boot()
    learn = LearningEngine(kernel.services(), state, LearningConfig(**cfg) if cfg else None)
    learn.register(kernel, runtime)
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    admin = kernel.services().new_context(security=SecurityContext("dev", "org", frozenset({"state:admin"})))
    return kernel, runtime, state, learn, ctx, admin


def make_learning_executive(**cfg: Any):
    """Learning wired to the Executive for authorization (runtime-routed)."""
    from app.cognitive_kernel.engines.executive import ExecutiveEngine

    kernel, runtime, state = _boot()
    ex = ExecutiveEngine(kernel.services(), state)
    ex.register(kernel, runtime)
    learn = LearningEngine(kernel.services(), state, LearningConfig(**cfg) if cfg else None)
    learn.register(kernel, runtime)
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    return kernel, runtime, state, ex, learn, ctx


def candidate(state, ctx, statement, episode, *, confidence=0.8, negated=False, kind=None) -> str:
    payload = {"generalization": statement, "episode": episode, "confidence": confidence, "negated": negated}
    if kind is not None:
        payload["kind"] = kind
    tx = state.begin_transaction(ctx)
    h = tx.create(ObjectType.LEARNING_CANDIDATE, payload=payload, status=ObjectStatus.PROPOSED)
    tx.commit()
    return h


def episodes(state, ctx, statement, n, *, confidence=0.8, negated=False, kind=None) -> list[str]:
    return [candidate(state, ctx, statement, f"{statement}-ep{i}", confidence=confidence, negated=negated, kind=kind)
            for i in range(n)]


def active_belief(state, ctx, statement, *, confidence=0.9, negated=False) -> str:
    tx = state.begin_transaction(ctx)
    h = tx.create(ObjectType.BELIEF, payload={"statement": statement, "negated": negated},
                  status=ObjectStatus.ACTIVE, confidence=confidence)
    tx.commit()
    return h


def reconciled(services, request_id, surprise) -> None:
    services.events.publish(CognitiveEvent(
        event_id="rc-" + request_id, type="prediction.reconciled", sequence=services.clock.tick(),
        source="prediction", correlation_id="t", payload={"request_id": request_id, "surprise": surprise}))


def learned(state, statement):
    return [b for b in state.query(region=Region.R5_BELIEF, type=ObjectType.BELIEF, status=ObjectStatus.ACTIVE)
            if b.payload.get("statement") == statement]


def teardown(kernel, runtime, state, *engines) -> None:
    for e in engines:
        try:
            e.stop()
        except Exception:
            pass
    state.stop()
    runtime.stop()
    kernel.shutdown()
