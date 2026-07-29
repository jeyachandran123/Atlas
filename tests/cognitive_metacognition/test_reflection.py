"""Reflection pipeline — artifacts, trace, repository, history, events, runtime."""

from __future__ import annotations

from app.cognitive_kernel.runtime import ExecutionRequest
from app.cognitive_kernel.engines.reasoning import ReasoningRequest
from app.cognitive_kernel.engines.executive import ReasoningProposal
from app.cognitive_kernel.state import ObjectType

from ._mc import make_meta, make_meta_wired, teardown


def _activity(state, engines, ctx):
    tx = state.begin_transaction(ctx)
    a = tx.create(ObjectType.BELIEF, payload={"statement": "a"}, confidence=0.9)
    r = tx.create(ObjectType.CONSTRAINT, payload={"rule": {"if": ["a"], "then": "b"}})
    tx.commit()
    engines["wm_api"].load(a, ctx)
    engines["wm_api"].load(r, ctx)
    engines["rz"].reason(ReasoningRequest(goal="derive b", question="b"), ctx)
    engines["ex"].govern(ReasoningProposal("p", "ok", 0.9, stakes=0.1), ctx)


def test_reflection_produces_a_complete_artifact() -> None:
    kernel, rt, state, engines, ctx = make_meta_wired()
    try:
        _activity(state, engines, ctx)
        art = engines["meta"].reflect(ctx)
        assert len(art.assessments) == 8              # every faculty assessed
        assert art.audit is not None and art.trace    # compliance + explainable trace (MeL21)
        assert 0.0 <= art.confidence <= 1.0           # confidence-qualified (MeL18)
        assert art.digest and art.summary
    finally:
        teardown(kernel, rt, state, *engines.values())


def test_reflection_artifacts_are_recorded_and_retrievable() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        art = meta.reflect(ctx)
        assert meta.artifact(art.artifact_id) is art     # repository (item 42)
        assert art in meta.artifacts()
    finally:
        teardown(kernel, rt, state, meta)


def test_reflection_writes_no_canonical_state() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        before = meta.canonical_watermark()
        for _ in range(5):
            meta.reflect(ctx)
        assert meta.canonical_watermark() == before and meta.canonical_writes() == 0  # MeL9/MeL13
    finally:
        teardown(kernel, rt, state, meta)


def test_reflection_events_published() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        before = kernel.services().ledger.head()
        meta.reflect(ctx)
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "metacognition.reflection" in types and "metacognition.audit" in types  # MeL19
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, meta)


def test_reflection_history_accumulates() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        for _ in range(3):
            meta.reflect(ctx)
        assert meta.metrics().reflections == 3
    finally:
        teardown(kernel, rt, state, meta)


def test_reflect_via_runtime_execution() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        h = rt.submit(ExecutionRequest(engine="metacognition", operation="reflect", payload={}))
        rt.drain()
        result = h.result()
        assert result.state.value == "completed" and result.value["assessments"] == 8
    finally:
        teardown(kernel, rt, state, meta)
