"""Integration: the full reasoning pipeline, state products, events, runtime."""

from __future__ import annotations

from app.cognitive_kernel.runtime import ExecutionRequest
from app.cognitive_kernel.state import ObjectStatus, ObjectType, Region
from app.cognitive_kernel.state.contracts import RelationshipType
from app.cognitive_kernel.engines.reasoning import ReasoningRequest, ReasoningType

from ._rz import assertion, cause, conscious, make_reasoning, rule, teardown


def test_deductive_pipeline_concludes_multi_step() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        a = assertion(state, ctx, "a", confidence=0.9)
        r1 = rule(state, ctx, ["a"], "b", reliability=0.9)
        r2 = rule(state, ctx, ["b"], "c", reliability=0.8)
        conscious(wm_api, [a, r1, r2], ctx)
        res = rz.reason(ReasoningRequest(goal="derive c", question="c"), ctx)
        assert res.concluded and res.conclusion.statement == "c"
        assert res.conclusion.confidence == 0.8          # min premise (ReL4)
        assert len(res.steps) >= 3                        # a -> b -> c is multi-step
        assert res.termination.value == "converged"
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_abductive_pipeline_writes_proposed_belief_with_evidence_dependency() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        e1 = assertion(state, ctx, "effect1", kind=ObjectType.PERCEPT)
        e2 = assertion(state, ctx, "effect2", kind=ObjectType.PERCEPT)
        c1a = cause(state, ctx, "C1", "effect1", strength=0.95)
        c1b = cause(state, ctx, "C1", "effect2", strength=0.95)
        conscious(wm_api, [e1, e2, c1a, c1b], ctx)
        res = rz.reason(ReasoningRequest(goal="explain the symptoms"), ctx)
        assert res.concluded and res.conclusion.statement == "C1"  # best explanation
        # The product is a PROPOSED belief (ReL9), never committed.
        assert len(res.products) == 1
        belief = state.get(res.products[0])
        assert belief.type is ObjectType.BELIEF and belief.status is ObjectStatus.PROPOSED
        assert belief.region is Region.R5_BELIEF
        # It depends on the evidence that supports it (traceability, item 24).
        deps = {e.target for e in belief.relationships if e.rel_type is RelationshipType.DEPENDENCY}
        assert deps  # dependency edges to supporting evidence
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_reasoning_acts_only_on_conscious_content() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        a = assertion(state, ctx, "a", confidence=0.9)
        r1 = rule(state, ctx, ["a"], "b", reliability=0.9)  # exists in State...
        conscious(wm_api, [a], ctx)                          # ...but only 'a' is conscious
        res = rz.reason(ReasoningRequest(goal="derive b", question="b"), ctx)
        assert not res.concluded  # cannot use a rule it is not conscious of (ReL12)
        conscious(wm_api, [r1], ctx)  # now the rule is conscious
        res2 = rz.reason(ReasoningRequest(goal="derive b", question="b"), ctx)
        assert res2.concluded and res2.conclusion.statement == "b"
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_episode_recorded_in_R6_reasoning_state() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        a = assertion(state, ctx, "a", confidence=0.9)
        r1 = rule(state, ctx, ["a"], "b")
        conscious(wm_api, [a, r1], ctx)
        res = rz.reason(ReasoningRequest(goal="derive b", question="b"), ctx)
        episodes = state.query(region=Region.R6_DELIBERATIVE, type=ObjectType.REASONING_STATE)
        assert any(o.handle == res.episode_id for o in episodes)
        episode = state.get(res.episode_id)
        assert episode.payload["concluded"] and episode.payload["trace_digest"]
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_reasoning_events_are_published() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        a = assertion(state, ctx, "a", confidence=0.9)
        r1 = rule(state, ctx, ["a"], "b")
        conscious(wm_api, [a, r1], ctx)
        before = kernel.services().ledger.head()
        rz.reason(ReasoningRequest(goal="derive b", question="b"), ctx)
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "reasoning.initiated" in types and "reasoning.concluded" in types
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_reason_via_runtime_execution() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        a = assertion(state, ctx, "a", confidence=0.9)
        r1 = rule(state, ctx, ["a"], "b")
        conscious(wm_api, [a, r1], ctx)
        handle = rt.submit(ExecutionRequest(
            engine="reasoning", operation="reason",
            payload={"goal": "derive b", "question": "b"},
        ))
        rt.drain()
        result = handle.result()
        assert result.state.value == "completed" and result.value["concluded"]
        assert result.value["statement"] == "b"
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_pipeline_is_deterministic() -> None:
    def run():
        kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
        try:
            e1 = assertion(state, ctx, "effect1", kind=ObjectType.PERCEPT)
            c1 = cause(state, ctx, "C1", "effect1", strength=0.9)
            conscious(wm_api, [e1, c1], ctx)
            res = rz.reason(ReasoningRequest(goal="explain"), ctx)
            return res.conclusion.statement, res.conclusion.confidence
        finally:
            teardown(kernel, rt, state, wm, rz)

    assert run() == run()  # same conscious content -> same conclusion (ReL6 determinism)
