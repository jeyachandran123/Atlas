"""Full-system integration — the complete Cognitive OS, plugged correctly.

Boots all eight engines as one mind and verifies: registration with the Kernel and
Runtime, health reporting, an end-to-end signal flowing across every faculty, that
cross-engine coordination routes through the Runtime (no direct engine-to-engine
calls), and that the constitutional invariants hold system-wide.
"""

from __future__ import annotations

from app.cognitive_kernel.state import ObjectStatus, ObjectType, Region
from app.cognitive_kernel.engines.attention import Candidate, SalienceVector
from app.cognitive_kernel.engines.reasoning import ReasoningRequest
from app.cognitive_kernel.engines.prediction import Driver, PredictionRequest
from app.cognitive_kernel.engines.executive import GoalTier, ReasoningProposal
from app.cognitive_kernel.engines.development.contracts import Capability

from ._sys import ENGINE_NAMES, assemble, teardown


def _make(state, ctx, kind, payload, **kw):
    tx = state.begin_transaction(ctx)
    h = tx.create(kind, payload=payload, **kw)
    tx.commit()
    return h


# --- wiring ---------------------------------------------------------------- #


def test_all_engines_register_with_kernel_and_runtime() -> None:
    kernel, rt, state, E, ctx = assemble()
    try:
        assert ENGINE_NAMES <= set(kernel.engine_registry().names())   # discoverable by the Kernel
        assert ENGINE_NAMES <= set(rt._orchestrator.names())            # noqa: SLF001 - executable by the Runtime
    finally:
        teardown(kernel, rt, state, E)


def test_health_monitor_sees_every_component_and_is_healthy() -> None:
    kernel, rt, state, E, ctx = assemble()
    try:
        report = kernel.services().health.report()
        assert ENGINE_NAMES <= set(report.keys())          # every faculty registered a probe
        assert "cognitive_state" in report
        assert kernel.services().health.overall().value == "healthy"
    finally:
        teardown(kernel, rt, state, E)


# --- end-to-end cross-faculty flow ---------------------------------------- #


def test_signal_flows_across_every_faculty() -> None:
    kernel, rt, state, E, ctx = assemble()
    try:
        a = _make(state, ctx, ObjectType.EVIDENCE, {"statement": "a"}, confidence=0.9)
        rule = _make(state, ctx, ObjectType.CONSTRAINT, {"rule": {"if": ["a"], "then": "b"}})
        E["wm_api"].load(a, ctx)
        E["wm_api"].load(rule, ctx)

        # Attention -> consciousness (ignites Working Memory).
        att = E["attention"].attend([Candidate(a, SalienceVector(goal_relevance=0.9)),
                                     Candidate(rule, SalienceVector(goal_relevance=0.8))], ctx)
        assert att.ignited and len(att.coalition) >= 1

        # Reasoning -> understanding.
        res = E["reasoning"].reason(ReasoningRequest(goal="derive b", question="b"), ctx)
        assert res.concluded and res.conclusion.statement == "b"

        # Executive -> governance (owns a goal, authorizes reasoning's proposal).
        g = E["executive"].create_goal(ctx, title="ship", owner="user", tier=GoalTier.STRATEGIC)
        gov = E["executive"].govern(ReasoningProposal("p1", res.conclusion.statement,
                                                      res.conclusion.confidence, goal_id=g.goal_id, stakes=0.1), ctx)
        assert gov.authorized and gov.decision.kind.value == "approve"

        # Executive -> Prediction (a high-stakes irreversible act triggers a risk request via the Runtime).
        E["executive"].govern(ReasoningProposal("p2", "irreversible act", 0.6, kind="action",
                                                stakes=0.95, reversibility=0.0), ctx)
        assert E["prediction"].metrics().risk_assessments >= 1

        # Prediction forecasts and reconciles realized outcomes.
        for i in range(6):
            E["prediction"].forecast(PredictionRequest(f"f{i}", target="ok", seed=i,
                                                       drivers=(Driver("d", 0.8, 1.0),)), ctx)
            E["prediction"].reconcile(f"f{i}", observed_outcome=0.8, context=ctx)

        # Learning -> the only durable change (multi-episode belief consolidation + calibration).
        for ep in range(3):
            _make(state, ctx, ObjectType.LEARNING_CANDIDATE,
                  {"generalization": "pattern_x", "episode": f"ep{ep}", "confidence": 0.8},
                  status=ObjectStatus.PROPOSED)
        lreport = E["learning"].learn(ctx)
        learned = [b for b in state.query(region=Region.R5_BELIEF, type=ObjectType.BELIEF,
                                          status=ObjectStatus.ACTIVE) if b.payload.get("statement") == "pattern_x"]
        assert lreport.committed >= 1 and learned                  # durable belief written
        assert E["learning"].metrics().calibrations == 1          # calibrated from realized outcomes

        # Meta-Cognition -> oversight (assesses the mind; audits compliance).
        mart = E["metacognition"].reflect(ctx)
        assert len(mart.assessments) == 8 and mart.audit.compliant

        # Development -> long-term evolution (assesses maturity; proposes; applies nothing).
        dart = E["development"].develop(ctx)
        assert len(dart.assessments) == len(list(Capability)) and dart.proposals

        # Coordination flowed through the Runtime (no direct engine-to-engine calls).
        util = rt.metrics().engine_utilization
        assert "prediction" in util and "attention" in util and "working_memory" in util
    finally:
        teardown(kernel, rt, state, E)


# --- system-wide constitutional invariants -------------------------------- #


def test_read_only_faculties_write_no_canonical_state() -> None:
    kernel, rt, state, E, ctx = assemble()
    try:
        # Drive some activity, then confirm the read-only faculties changed nothing.
        _make(state, ctx, ObjectType.EVIDENCE, {"statement": "x"}, confidence=0.9)
        for i in range(4):
            E["prediction"].forecast(PredictionRequest(f"f{i}", seed=i, drivers=(Driver("d", 0.8, 1.0),)), ctx)
        E["metacognition"].reflect(ctx)
        E["development"].develop(ctx)
        assert E["prediction"].canonical_writes() == 0
        assert E["metacognition"].canonical_writes() == 0
        assert E["development"].canonical_writes() == 0
    finally:
        teardown(kernel, rt, state, E)


def test_system_integrity_after_full_flow() -> None:
    kernel, rt, state, E, ctx = assemble()
    try:
        a = _make(state, ctx, ObjectType.EVIDENCE, {"statement": "a"}, confidence=0.9)
        E["wm_api"].load(a, ctx)
        E["attention"].attend([Candidate(a, SalienceVector(goal_relevance=0.9))], ctx)
        E["executive"].govern(ReasoningProposal("p", "ok", 0.9, stakes=0.1), ctx)
        E["metacognition"].reflect(ctx)
        E["development"].develop(ctx)
        # No execution failed; the hash-chained ledger and state projection verify.
        assert rt.metrics().failed == 0
        assert kernel.services().ledger.verify()
        assert state.verify_integrity()
    finally:
        teardown(kernel, rt, state, E)
