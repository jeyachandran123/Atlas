"""Integration — the learning pipeline, knowledge revision, provenance, events."""

from __future__ import annotations

from app.cognitive_kernel.runtime import ExecutionRequest
from app.cognitive_kernel.state import ObjectStatus
from app.cognitive_kernel.state.contracts import RelationshipType

from ._ln import candidate, episodes, learned, make_learning, teardown


def test_single_event_produces_no_change() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        candidate(state, ctx, "swans_white", "ep1")   # one event only
        report = learn.learn(ctx)
        assert report.committed == 0 and not learned(state, "swans_white")  # LeL7/LeL9
    finally:
        teardown(kernel, rt, state, learn)


def test_multi_episode_evidence_is_consolidated() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        episodes(state, ctx, "swans_white", 3)
        report = learn.learn(ctx)
        assert report.committed == 1
        beliefs = learned(state, "swans_white")
        assert beliefs and beliefs[0].status is ObjectStatus.ACTIVE and beliefs[0].payload["consolidated"]
    finally:
        teardown(kernel, rt, state, learn)


def test_committed_belief_carries_provenance() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        srcs = episodes(state, ctx, "grass_green", 3)
        learn.learn(ctx)
        belief = learned(state, "grass_green")[0]
        # provenance: learned_by record + episodes + INFLUENCE edges to the evidence (LeL24)
        assert belief.payload["learned_by"] and belief.payload["episodes"]
        deps = {e.target for e in belief.relationships if e.rel_type is RelationshipType.INFLUENCE}
        assert deps & set(srcs)  # dependency edges to the consumed candidate evidence
    finally:
        teardown(kernel, rt, state, learn)


def test_consumed_candidates_are_archived_not_deleted() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        srcs = episodes(state, ctx, "roses_red", 3)
        learn.learn(ctx)
        assert all(state.get(s).status is ObjectStatus.ARCHIVED for s in srcs)  # LeL27
    finally:
        teardown(kernel, rt, state, learn)


def test_learning_records_are_immutable_and_include_rejections() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        candidate(state, ctx, "one_off", "ep1")          # will be rejected (one event)
        episodes(state, ctx, "corroborated", 3)          # will be committed
        learn.learn(ctx)
        records = learn.records()
        assert any(r.committed for r in records) and any(not r.committed for r in records)  # LeL20
        assert all(r.digest and r.trace for r in records)                                   # explainable
    finally:
        teardown(kernel, rt, state, learn)


def test_learning_events_published() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        episodes(state, ctx, "fact", 3)
        before = kernel.services().ledger.head()
        learn.learn(ctx)
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "learning.cycle" in types and "learning.committed" in types
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, learn)


def test_learn_via_runtime_execution() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        episodes(state, ctx, "fact", 3)
        h = rt.submit(ExecutionRequest(engine="learning", operation="learn", payload={}))
        rt.drain()
        result = h.result()
        assert result.state.value == "completed" and result.value["committed"] == 1
    finally:
        teardown(kernel, rt, state, learn)


def test_learning_is_deterministic() -> None:
    def run():
        kernel, rt, state, learn, ctx, admin = make_learning()
        try:
            episodes(state, ctx, "claim", 4, confidence=0.75)
            report = learn.learn(ctx)
            belief = learned(state, "claim")[0]
            return report.committed, round(belief.confidence, 6)
        finally:
            teardown(kernel, rt, state, learn)

    assert run() == run()
