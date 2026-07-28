"""Versioning, history, diff, checkpoint, restore, recovery, rollback, merge."""

from __future__ import annotations

import dataclasses

import pytest

from app.cognitive_kernel.state import ObjectStatus, ObjectType, StateError

from ._st import make_state


def _make_goal(sm, ctx, **payload):
    tx = sm.begin_transaction(ctx)
    h = tx.create(ObjectType.GOAL, payload=payload)
    tx.commit()
    return h


# --- versioning & history -------------------------------------------------- #


def test_versions_are_monotonic_and_history_retained() -> None:
    kernel, sm, ctx = make_state()
    g = _make_goal(sm, ctx, n=0)
    for i in range(1, 4):
        tx = sm.begin_transaction(ctx)
        tx.update(g, payload_merge={"n": i})
        tx.commit()
    versions = sm.history(g)
    assert [v.version for v in versions] == [1, 2, 3, 4]
    assert sm.get(g).version == 4 and sm.get(g).payload["n"] == 3
    assert sm.get_version(g, 1).payload["n"] == 0  # old versions still readable
    sm.stop()


def test_diff_between_versions() -> None:
    kernel, sm, ctx = make_state()
    g = _make_goal(sm, ctx, n=0)
    tx = sm.begin_transaction(ctx)
    tx.update(g, payload_merge={"n": 5}, salience=0.7, status=ObjectStatus.SUSPENDED)
    tx.commit()
    d = sm.diff(g, 1, 2)
    assert d.changed_fields["payload.n"] == (0, 5)
    assert d.changed_fields["salience"] == (0.0, 0.7)
    assert d.changed_fields["status"][1] is ObjectStatus.SUSPENDED
    sm.stop()


# --- checkpoint / restore / serialization ---------------------------------- #


def test_checkpoint_and_restore_roundtrip() -> None:
    kernel, sm, ctx = make_state()
    g = _make_goal(sm, ctx, n=1)
    cid = sm.checkpoint()
    tx = sm.begin_transaction(ctx)
    tx.update(g, payload_merge={"n": 999})
    tx.commit()
    assert sm.get(g).payload["n"] == 999
    restored = sm.restore(cid)
    assert restored == 1 and sm.get(g).payload["n"] == 1  # back to checkpoint state
    sm.stop()


def test_serialize_and_restore_from_bytes() -> None:
    kernel, sm, ctx = make_state()
    _make_goal(sm, ctx, n=1)
    _make_goal(sm, ctx, n=2)
    blob = sm.serialize()
    sm2_kernel, sm2, sm2_ctx = make_state()
    n = sm2.restore_from_bytes(blob)
    assert n == 2 and sm2.metrics().object_count == 2
    sm.stop()
    sm2.stop()


def test_restore_without_checkpoint_raises() -> None:
    kernel, sm, ctx = make_state()
    with pytest.raises(StateError):
        sm.restore()  # nothing checkpointed
    sm.stop()


# --- recovery via ledger replay -------------------------------------------- #


def test_recover_rebuilds_state_from_ledger() -> None:
    kernel, sm, ctx = make_state()
    g = _make_goal(sm, ctx, n=1)
    tx = sm.begin_transaction(ctx)
    tx.update(g, payload_merge={"n": 2})
    tx.commit()
    b_tx = sm.begin_transaction(ctx)
    b_tx.create(ObjectType.BELIEF, payload={"p": True})
    b_tx.commit()
    before = sm.snapshot()
    applied = sm.recover()  # rebuild projection from ledger events (RL8)
    after = sm.snapshot()
    assert applied >= 3  # 1 create-goal + 1 update-goal + 1 create-belief
    # Reconstructed state matches (same objects, same current versions).
    assert {o.handle: o.version for o in before.objects} == {o.handle: o.version for o in after.objects}
    assert sm.get(g).version == 2 and sm.get(g).payload["n"] == 2
    sm.stop()


# --- rollback -------------------------------------------------------------- #


def test_rollback_creates_new_version_with_old_content() -> None:
    kernel, sm, ctx = make_state()
    g = _make_goal(sm, ctx, n=0)
    tx = sm.begin_transaction(ctx)
    tx.update(g, payload_merge={"n": 42})
    tx.commit()  # v2
    restored = sm.rollback(g, 1, ctx)  # -> v3 with v1 content
    assert restored.version == 3 and restored.payload["n"] == 0
    assert len(sm.history(g)) == 3  # history preserved (OL4)
    assert sm.metrics().rollbacks == 1
    sm.stop()


# --- merge (branch reconciliation, e.g. from simulation) ------------------- #


def test_merge_version_wins_and_adds_new() -> None:
    kernel, sm, ctx = make_state()
    g = _make_goal(sm, ctx, n=0)
    branch = sm.snapshot()
    # Simulate a branch that advanced the goal and introduced a new object.
    advanced_goal = dataclasses.replace(
        sm.get(g), version=5, payload=type(sm.get(g).payload)({"n": 7})
    )
    from app.cognitive_kernel.state.objects import new_object

    new_belief = new_object("branch-belief", ObjectType.BELIEF, payload={"p": 1}, status=ObjectStatus.ACTIVE)
    incoming = dataclasses.replace(branch, objects=(advanced_goal, new_belief))
    applied = sm.merge(incoming, ctx, strategy="version_wins")
    assert applied == 2
    assert sm.get(g).payload["n"] == 7 and sm.get(g).version == 2  # cur v1 + 1
    assert sm.exists("branch-belief")
    assert sm.metrics().merges == 1
    sm.stop()
