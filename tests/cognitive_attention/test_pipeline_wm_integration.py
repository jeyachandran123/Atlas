"""Integration: the full attention pipeline and Working Memory gating."""

from __future__ import annotations

from app.cognitive_kernel.runtime import ExecutionRequest
from app.cognitive_kernel.state import ObjectStatus, ObjectType, Region

from ._at import cand, make_attention, make_targets, teardown


def _focus_targets(wm):
    return {s.target for s in wm.read_focus()}


def test_attention_gates_working_memory() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention(focus=4)
    try:
        t = make_targets(sm, ctx, 3)
        r = att.attend([cand(t[0], goal_relevance=0.9), cand(t[1], urgency=0.8), cand(t[2], user_importance=0.7)], ctx)
        assert set(r.coalition) == _focus_targets(wm)  # nothing conscious except what attention ignited (AL16)
        assert r.ignited
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_coalition_is_capacity_bounded() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention(focus=2)
    try:
        t = make_targets(sm, ctx, 5)
        r = att.attend([cand(h, goal_relevance=0.95) for h in t], ctx)
        assert len(r.coalition) == 2 and len(r.inhibited) == 3  # bounded; losers inhibited
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_ignite_nothing_when_all_below_threshold() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        t = make_targets(sm, ctx, 2)
        r = att.attend([cand(t[0], novelty=0.2), cand(t[1], recency=0.2)], ctx)
        assert not r.ignited and _focus_targets(wm) == set()  # AL11 rest
        assert att.metrics().empty_ignitions == 1
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_inhibition_before_replacement_evicts_lost_incumbent() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        t = make_targets(sm, ctx, 2)
        att.attend([cand(t[0], goal_relevance=0.9)], ctx)      # X conscious
        assert t[0] in _focus_targets(wm)
        r = att.attend([cand(t[1], goal_relevance=0.9)], ctx)  # Y competes; X not a candidate
        assert t[0] in r.evicted and t[0] not in _focus_targets(wm)  # AL7: X evicted
        assert t[1] in _focus_targets(wm)
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_sustained_attention_refreshes_incumbent() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        t = make_targets(sm, ctx, 2)
        att.attend([cand(t[0], goal_relevance=0.9)], ctx)
        r = att.attend([cand(t[0], goal_relevance=0.9), cand(t[1], urgency=0.8)], ctx)
        assert t[0] in r.sustained and t[1] in r.newly_ignited
        assert _focus_targets(wm) == {t[0], t[1]}  # both conscious (divided attention)
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_broadcast_and_events_recorded() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        t = make_targets(sm, ctx, 1)
        before = kernel.services().ledger.head()
        att.attend([cand(t[0], goal_relevance=0.9)], ctx)
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "attention.ignition" in types
        assert "working_memory.broadcast" in types  # Global Workspace broadcast
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_attention_state_written_to_R3() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        t = make_targets(sm, ctx, 2)
        att.attend([cand(t[0], goal_relevance=0.9), cand(t[1], novelty=0.1)], ctx)
        focus = sm.query(region=Region.R3_ATTENTION, type=ObjectType.ATTENTION_FOCUS, status=ObjectStatus.ACTIVE)
        salience = sm.query(region=Region.R3_ATTENTION, type=ObjectType.SALIENCE, status=ObjectStatus.ACTIVE)
        inhibition = sm.query(region=Region.R3_ATTENTION, type=ObjectType.INHIBITION, status=ObjectStatus.ACTIVE)
        assert len(focus) == 1 and t[0] in focus[0].payload["coalition"]
        assert len(salience) == 1 and len(inhibition) == 1
        # A second cycle appends a new version (attention history, AL26/OL4).
        att.attend([cand(t[0], goal_relevance=0.9)], ctx)
        assert sm.get(focus[0].handle).version == 2
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_wm_writes_flow_through_the_runtime() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        t = make_targets(sm, ctx, 1)
        att.attend([cand(t[0], goal_relevance=0.9)], ctx)
        # The WM activation was a runtime execution (not a direct engine call).
        assert "working_memory" in rt.metrics().engine_utilization
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_attend_via_runtime_execution() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        t = make_targets(sm, ctx, 1)
        h = rt.submit(ExecutionRequest(
            engine="attention", operation="attend",
            payload={"candidates": [{"target": t[0], "vector": {"goal_relevance": 0.9}}]},
        ))
        rt.drain()
        result = h.result()
        assert result.state.value == "completed" and result.value["ignited"]
        assert t[0] in _focus_targets(wm)
    finally:
        teardown(kernel, rt, sm, wm, att)
