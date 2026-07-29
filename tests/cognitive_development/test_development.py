"""Integration — the development pipeline, artifacts, proposals, roadmap, events."""

from __future__ import annotations

from app.cognitive_kernel.runtime import ExecutionRequest
from app.cognitive_kernel.engines.development.contracts import Capability

from ._dv import make_development, strong_reasoning, teardown, wm_churn


def test_development_produces_a_complete_artifact() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 25)
        art = dev.develop(ctx)
        assert len(art.assessments) == len(list(Capability))   # every capability certified (DeL9)
        assert art.roadmap is not None and art.summary and art.digest
        assert 0.0 <= art.confidence <= 1.0
    finally:
        teardown(kernel, rt, state, dev)


def test_proposals_are_evidence_backed() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        wm_churn(kernel.services(), 20)     # creates a capacity limitation -> a proposal
        art = dev.develop(ctx)
        assert art.proposals
        for p in art.proposals:
            assert p.evidence and p.state.value == "evidence_backed"  # DeL12/DeL15
    finally:
        teardown(kernel, rt, state, dev)


def test_development_writes_no_canonical_state() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 20)
        before = dev.canonical_watermark()
        for _ in range(5):
            dev.develop(ctx)
        assert dev.canonical_watermark() == before and dev.canonical_writes() == 0  # DeL13
    finally:
        teardown(kernel, rt, state, dev)


def test_development_events_published() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 20)
        before = kernel.services().ledger.head()
        dev.develop(ctx)
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "development.cycle" in types
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, dev)


def test_develop_via_runtime_execution() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 20)
        h = rt.submit(ExecutionRequest(engine="development", operation="develop", payload={}))
        rt.drain()
        result = h.result()
        assert result.state.value == "completed" and result.value["assessments"] == len(list(Capability))
    finally:
        teardown(kernel, rt, state, dev)


def test_capability_assessment_via_hook() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 25)
        a = dev.assess_capability(Capability.REASONING)
        assert a.capability is Capability.REASONING and a.maturity.name in (
            "PROFICIENT", "MATURE", "OPTIMIZING")
    finally:
        teardown(kernel, rt, state, dev)


def test_development_is_deterministic() -> None:
    def run():
        kernel, rt, state, dev, ctx, admin = make_development()
        try:
            strong_reasoning(kernel.services(), 22)
            art = dev.develop(ctx)
            return len(art.proposals), art.assessments[2].score
        finally:
            teardown(kernel, rt, state, dev)

    assert run() == run()
