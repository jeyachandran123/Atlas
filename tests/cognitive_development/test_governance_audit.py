"""Governance, constitutional protection, review submission, and audit."""

from __future__ import annotations

from app.cognitive_kernel.engines.development.contracts import ReviewTier

from ._dv import make_development, make_development_executive, strong_reasoning, teardown, wm_churn


def test_no_forbidden_proposal_is_ever_generated() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 20)
        wm_churn(kernel.services(), 20)
        art = dev.develop(ctx)
        assert all(p.review_tier is not ReviewTier.FORBIDDEN for p in art.proposals)  # DeL1/DeL16
    finally:
        teardown(kernel, rt, state, dev)


def test_proposals_are_exported_not_applied() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        wm_churn(kernel.services(), 20)
        before = dev.canonical_watermark()
        dev.develop(ctx)
        recs = dev.development_recommendations()
        assert recs                                   # proposals produced
        assert dev.canonical_watermark() == before    # but nothing applied (proposals only, DeL13)
    finally:
        teardown(kernel, rt, state, dev)


def test_review_submission_routes_to_executive() -> None:
    kernel, rt, state, ex, dev, ctx = make_development_executive()
    try:
        wm_churn(kernel.services(), 20)
        dev.develop(ctx)
        submitted = dev.submit_for_review(ctx)
        assert submitted >= 1 and "executive" in rt.metrics().engine_utilization  # DeL3/DeL8, via runtime
    finally:
        teardown(kernel, rt, state, ex, dev)


def test_regression_raises_a_fail_safe_signal() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 30)
        dev.develop(ctx)
        dev.develop(ctx)
        for _ in range(300):
            from ._dv import emit
            emit(kernel.services(), "reasoning.escalated", "reasoning")
        before = kernel.services().ledger.head()
        dev.develop(ctx)
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "development.regression" in types  # DeL14 — fail-safe escalation signal
    finally:
        teardown(kernel, rt, state, dev)


def test_future_capability_planning_and_recommendations() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        wm_churn(kernel.services(), 20)
        dev.develop(ctx)
        assert isinstance(dev.future_capability_planning(), list)   # item 35
        assert dev.development_recommendations()                    # item 26
    finally:
        teardown(kernel, rt, state, dev)
