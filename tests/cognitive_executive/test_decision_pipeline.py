"""Decision pipeline — approve/reject/escalate, immutable decisions, audit, runtime."""

from __future__ import annotations

from app.cognitive_kernel.runtime import ExecutionRequest
from app.cognitive_kernel.state import ObjectStatus, ObjectType, Region
from app.cognitive_kernel.engines.executive import Policy, PolicyEffect, PolicyFamily

from ._ex import make_executive, proposal, teardown


def test_confident_low_stakes_is_approved() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        out = ex.govern(proposal("p", "server healthy", 0.9, stakes=0.1), ctx)
        assert out.authorized and out.decision.kind.value == "approve"
        assert out.decision.outcome.value == "approved"
    finally:
        teardown(kernel, rt, state, ex)


def test_low_confidence_high_stakes_escalates() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        out = ex.govern(proposal("p", "risky", 0.4, kind="action", stakes=0.9, reversibility=0.2), ctx)
        assert not out.authorized and out.decision.outcome.value == "escalated"  # ExL13/P10
    finally:
        teardown(kernel, rt, state, ex)


def test_safety_relevant_action_requires_human_approval() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        out = ex.govern(proposal("p", "transfer funds", 0.99, kind="action", safety_relevant=True), ctx)
        assert out.decision.kind.value == "ask_user"  # constitutional gate (ExL14)
    finally:
        teardown(kernel, rt, state, ex)


def test_absolute_policy_denial_rejects() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        ex.enact_policy(admin, Policy("blk", PolicyFamily.SAFETY, "no_wipe", PolicyEffect.DENY,
                                      predicate={"statement_contains": "wipe"}))
        out = ex.govern(proposal("p", "wipe everything", 0.99, kind="action"), ctx)
        assert out.decision.kind.value == "reject" and not out.authorized  # ExL7
    finally:
        teardown(kernel, rt, state, ex)


def test_decision_persisted_immutably_in_R9() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        out = ex.govern(proposal("p", "ok", 0.9, stakes=0.1), ctx)
        obj = state.get(out.decision.handle)
        assert obj.type is ObjectType.EXECUTIVE_DECISION and obj.region is Region.R9_METACOGNITIVE
        assert obj.immutable and obj.payload["decision_id"] == out.decision.decision_id
    finally:
        teardown(kernel, rt, state, ex)


def test_audit_trail_records_every_ruling() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        ex.govern(proposal("p1", "a", 0.9, stakes=0.1), ctx)
        ex.govern(proposal("p2", "b", 0.4, stakes=0.9, kind="action", reversibility=0.1), ctx)
        trail = ex.audit_trail()
        assert len(trail) >= 2  # every governance ruling is an immutable artifact (ExL3)
    finally:
        teardown(kernel, rt, state, ex)


def test_executive_events_published() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        before = kernel.services().ledger.head()
        ex.govern(proposal("p", "ok", 0.9, stakes=0.1), ctx)
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "executive.decision" in types
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, ex)


def test_govern_via_runtime_execution() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        h = rt.submit(ExecutionRequest(
            engine="executive", operation="govern",
            payload={"statement": "healthy", "confidence": 0.9, "stakes": 0.1},
        ))
        rt.drain()
        result = h.result()
        assert result.state.value == "completed" and result.value["authorized"]
    finally:
        teardown(kernel, rt, state, ex)


def test_governance_is_deterministic() -> None:
    def run():
        kernel, rt, state, ex, ctx, admin = make_executive()
        try:
            out = ex.govern(proposal("p", "x", 0.72, stakes=0.4, reversibility=0.5), ctx)
            return out.decision.kind.value, out.decision.threshold
        finally:
            teardown(kernel, rt, state, ex)

    assert run() == run()  # deterministic governance
