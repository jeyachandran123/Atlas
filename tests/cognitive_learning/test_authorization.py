"""Impact-scaled authorization (LeL33) — automatic / executive / human tiers."""

from __future__ import annotations

from ._ln import episodes, learned, make_learning, make_learning_executive, teardown


def test_low_impact_learns_on_the_automatic_tier() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        episodes(state, ctx, "ordinary_fact", 3)
        report = learn.learn(ctx)
        assert report.committed == 1  # LOW impact, validated -> automatic (LeL34), no executive needed
    finally:
        teardown(kernel, rt, state, learn)


def test_high_impact_is_deferred_to_human_without_executive() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        episodes(state, ctx, "relax_safety_margin", 3)   # 'safety' -> HIGH impact
        report = learn.learn(ctx)
        assert report.committed == 0 and report.deferred == 1 and not learned(state, "relax_safety_margin")
    finally:
        teardown(kernel, rt, state, learn)


def test_moderate_impact_committed_with_executive_approval() -> None:
    kernel, rt, state, ex, learn, ctx = make_learning_executive()
    try:
        # RULE_INDUCTION -> MODERATE -> routed to the Executive, which approves (reversible, moderate stakes).
        episodes(state, ctx, "induced_rule", 3, confidence=0.85, kind="rule_induction")
        report = learn.learn(ctx)
        assert report.committed == 1 and learned(state, "induced_rule")   # LeL3 — executive authorized
    finally:
        teardown(kernel, rt, state, ex, learn)


def test_high_impact_escalates_to_human_with_executive() -> None:
    kernel, rt, state, ex, learn, ctx = make_learning_executive()
    try:
        episodes(state, ctx, "change_identity_core", 3)  # 'identity'/'core' -> HIGH -> executive escalates
        report = learn.learn(ctx)
        assert report.committed == 0 and report.deferred == 1  # LeL6/LeL17 — human review gate
        assert "executive" in rt.metrics().engine_utilization  # authorization routed via the Executive
    finally:
        teardown(kernel, rt, state, ex, learn)
