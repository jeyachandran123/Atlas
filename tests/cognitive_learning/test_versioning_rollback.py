"""Versioned knowledge updates and rollback (LeL13/LeL21/LeL27)."""

from __future__ import annotations

from app.cognitive_kernel.state import ObjectStatus, ObjectType

from ._ln import episodes, learned, make_learning, reconciled, teardown


def _proposed_belief(state, ctx, statement):
    tx = state.begin_transaction(ctx)
    h = tx.create(ObjectType.BELIEF, payload={"statement": statement, "negated": False},
                  status=ObjectStatus.PROPOSED, confidence=0.4)
    tx.commit()
    return h


def test_promotion_creates_a_new_version() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        belief = _proposed_belief(state, ctx, "x")
        episodes(state, ctx, "x", 3)
        learn.learn(ctx)
        obj = state.get(belief)
        assert obj.status is ObjectStatus.ACTIVE and obj.version >= 2       # versioned (LeL21)
        assert len(state.history(belief)) >= 2                              # prior versions preserved
    finally:
        teardown(kernel, rt, state, learn)


def test_rollback_reverts_a_promotion() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        belief = _proposed_belief(state, ctx, "y")
        episodes(state, ctx, "y", 3)
        learn.learn(ctx)
        assert state.get(belief).status is ObjectStatus.ACTIVE
        rid = [r for r in learn.records() if r.committed and r.revision][0].record_id
        assert learn.rollback(rid, ctx)
        assert state.get(belief).status is ObjectStatus.PROPOSED           # reverted (LeL13)
    finally:
        teardown(kernel, rt, state, learn)


def test_rollback_of_new_belief_deprecates_not_deletes() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        episodes(state, ctx, "z", 3)
        learn.learn(ctx)
        belief = learned(state, "z")[0]
        rid = [r for r in learn.records() if r.committed and r.revision][0].record_id
        learn.rollback(rid, ctx)
        assert state.get(belief.handle).status is ObjectStatus.ARCHIVED    # deprecated, never deleted (LeL27)
    finally:
        teardown(kernel, rt, state, learn)


def test_calibration_rollback() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        before = learn.calibration()
        for i in range(6):
            reconciled(kernel.services(), f"r{i}", surprise=0.4)
        learn.learn(ctx)
        assert learn.calibration() != before
        rid = [r for r in learn.records() if r.kind.value == "calibration"][0].record_id
        learn.rollback(rid, ctx)
        assert learn.calibration() == before                               # calibration reverted (LeL13)
    finally:
        teardown(kernel, rt, state, learn)
