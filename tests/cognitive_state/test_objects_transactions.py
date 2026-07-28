"""Unit tests: objects, placement, immutability, transactions, OCC, invariants."""

from __future__ import annotations

import pytest

from app.cognitive_kernel.state import (
    ImmutableObjectError,
    ObjectStatus,
    ObjectType,
    Region,
    RelationshipType,
    StateConflictError,
    StateConsistencyError,
    StateSecurityError,
)
from app.cognitive_kernel.state.invariants import _check_placement  # noqa: PLC2701
from app.cognitive_kernel.state.objects import new_object

from ._st import ctx_with, make_state


def test_create_places_object_in_correct_region() -> None:
    kernel, sm, ctx = make_state()
    tx = sm.begin_transaction(ctx)
    g = tx.create(ObjectType.GOAL, payload={"desc": "x"})
    tx.commit()
    obj = sm.get(g)
    assert obj.region is Region.R2_INTENTIONAL and obj.status is ObjectStatus.ACTIVE
    assert obj.version == 1 and not obj.immutable
    sm.stop()


def test_belief_and_relationship_link() -> None:
    kernel, sm, ctx = make_state()
    tx = sm.begin_transaction(ctx)
    b = tx.create(ObjectType.BELIEF, payload={"prop": "p"}, confidence=0.9)
    g = tx.create(ObjectType.GOAL, payload={"desc": "y"})
    tx.link(g, RelationshipType.DEPENDENCY, b)
    tx.commit()
    rels = sm.relationships(g)
    assert any(r.rel_type is RelationshipType.DEPENDENCY and r.target == b for r in rels)
    sm.stop()


def test_multiple_ops_same_handle_produce_one_version() -> None:
    kernel, sm, ctx = make_state()
    tx = sm.begin_transaction(ctx)
    g = tx.create(ObjectType.GOAL, payload={"a": 1})
    tx.update(g, payload_merge={"b": 2})
    tx.update(g, payload_merge={"c": 3}, salience=0.5)
    tx.commit()
    obj = sm.get(g)
    assert obj.version == 1 and dict(obj.payload) == {"a": 1, "b": 2, "c": 3} and obj.salience == 0.5
    sm.stop()


def test_optimistic_concurrency_conflict() -> None:
    kernel, sm, ctx = make_state()
    tx = sm.begin_transaction(ctx)
    g = tx.create(ObjectType.GOAL, payload={"n": 0})
    tx.commit()  # v1
    tx_a = sm.begin_transaction(ctx)
    tx_a.update(g, payload_merge={"n": 1}, expected_version=1)
    tx_b = sm.begin_transaction(ctx)
    tx_b.update(g, payload_merge={"n": 2}, expected_version=1)
    tx_a.commit()  # -> v2
    with pytest.raises(StateConflictError):
        tx_b.commit()  # stale expected version
    assert sm.metrics().conflicts == 1
    sm.stop()


def test_immutable_executive_decision_cannot_be_edited() -> None:
    kernel, sm, ctx = make_state()
    tx = sm.begin_transaction(ctx)
    d = tx.create(ObjectType.EXECUTIVE_DECISION, payload={"choice": "escalate"})
    tx.commit()
    assert sm.get(d).immutable
    tx2 = sm.begin_transaction(ctx)
    tx2.update(d, payload_merge={"choice": "hacked"})
    with pytest.raises(ImmutableObjectError):
        tx2.commit()  # supersede-only, even for admins
    sm.stop()


def test_executive_decision_supersede_creates_new() -> None:
    kernel, sm, ctx = make_state()
    tx = sm.begin_transaction(ctx)
    d = tx.create(ObjectType.EXECUTIVE_DECISION, payload={"choice": "A"})
    tx.commit()
    tx2 = sm.begin_transaction(ctx)
    d2 = tx2.supersede(d, ObjectType.EXECUTIVE_DECISION, payload={"choice": "B"})
    tx2.commit()
    assert sm.get(d).status is ObjectStatus.SUPERSEDED
    assert any(r.rel_type is RelationshipType.SUPERSEDES and r.target == d for r in sm.relationships(d2))
    sm.stop()


def test_identity_evolution_requires_admin() -> None:
    kernel, sm, ctx = make_state()
    tx = sm.begin_transaction(ctx)
    i = tx.create(ObjectType.IDENTITY, payload={"role": "engineer"})
    tx.commit()
    # Non-admin edit refused.
    tx2 = sm.begin_transaction(ctx)
    tx2.update(i, payload_merge={"role": "changed"})
    with pytest.raises(StateSecurityError):
        tx2.commit()
    # Admin gated evolution permitted.
    admin = ctx_with(kernel, "state:admin")
    tx3 = sm.begin_transaction(admin)
    tx3.update(i, payload_merge={"role": "senior"})
    tx3.commit()
    assert sm.get(i).payload["role"] == "senior" and sm.get(i).version == 2
    sm.stop()


def test_invariant_acyclicity_rejects_dependency_cycle() -> None:
    kernel, sm, ctx = make_state()
    tx = sm.begin_transaction(ctx)
    a = tx.create(ObjectType.GOAL, payload={})
    b = tx.create(ObjectType.GOAL, payload={})
    tx.link(a, RelationshipType.DEPENDENCY, b)
    tx.commit()
    tx2 = sm.begin_transaction(ctx)
    tx2.link(b, RelationshipType.DEPENDENCY, a)  # would create a cycle
    with pytest.raises(StateConsistencyError):
        tx2.commit()
    sm.stop()


def test_invariant_referential_integrity() -> None:
    kernel, sm, ctx = make_state()
    tx = sm.begin_transaction(ctx)
    g = tx.create(ObjectType.GOAL, payload={})
    tx.link(g, RelationshipType.DEPENDENCY, "nonexistent-handle")
    with pytest.raises(StateConsistencyError):
        tx.commit()
    sm.stop()


class _RequireDesc:
    name = "goal_requires_desc"

    def validate(self, objects) -> None:
        for o in objects.values():
            if o.type is ObjectType.GOAL and "desc" not in o.payload:
                raise StateConsistencyError(f"goal {o.handle} missing 'desc'")


def test_pluggable_semantic_validator() -> None:
    kernel, sm, ctx = make_state()
    sm.register_validator(_RequireDesc())
    assert "goal_requires_desc" in sm._invariants.validators()  # noqa: SLF001
    tx = sm.begin_transaction(ctx)
    tx.create(ObjectType.GOAL, payload={})  # no desc
    with pytest.raises(StateConsistencyError):
        tx.commit()
    sm.stop()


def test_placement_invariant_rejects_misplaced_object() -> None:
    # Direct invariant check with a hand-built, deliberately misplaced object.
    import dataclasses

    from app.cognitive_kernel.state.errors import PlacementError

    misplaced = dataclasses.replace(new_object("h", ObjectType.GOAL), region=Region.R5_BELIEF)
    with pytest.raises(PlacementError):
        _check_placement({misplaced.handle: misplaced})
