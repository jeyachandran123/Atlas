import pytest
from app.intelligence.reasoning.trace.builder import ReasoningTraceBuilder
from app.intelligence.reasoning.models import (
    ActiveGoalContext, ConfidenceLevel, ConfidenceReport,
    ExecutionMode, ExecutionPlan, ExecutionStep,
    GoalType, InferredGoal, QualitySignal, ReasoningDepth,
    ReflectionResult, ReflectionVerdict, RewrittenQuery,
    TaskDecomposition,
)


def _make_goal():
    return InferredGoal(
        goal_type=GoalType.BUILD,
        primary_objective="Build something",
        sub_objectives=[],
        success_criteria=[],
        raw_message="build it",
    )


def _make_plan():
    return ExecutionPlan(
        steps=[ExecutionStep(step_id="s1", task_ids=[], mode=ExecutionMode.SEQUENTIAL)],
        total_steps=1,
        has_parallel_steps=False,
        reasoning_depth=ReasoningDepth.SINGLE_PASS,
        estimated_tool_calls=0,
    )


def _make_confidence():
    return ConfidenceReport(
        scores=[],
        overall=0.85,
        overall_level=ConfidenceLevel.HIGH,
        should_clarify=False,
        should_retrieve_more=False,
    )


class TestReasoningTraceBuilder:
    def test_build_returns_trace_with_request_id(self):
        tb = ReasoningTraceBuilder("req-123")
        trace = tb.build()
        assert trace.request_id == "req-123"

    def test_total_ms_populated_after_build(self):
        tb = ReasoningTraceBuilder("req-1")
        trace = tb.build()
        assert trace.total_ms >= 0.0

    def test_set_goal_stored_in_trace(self):
        tb = ReasoningTraceBuilder("req-1")
        goal = _make_goal()
        tb.set_goal(goal)
        trace = tb.build()
        assert trace.inferred_goal is goal

    def test_set_rewritten_query_stored(self):
        tb = ReasoningTraceBuilder("req-1")
        rq = RewrittenQuery(original="test", rewritten="enriched test", enrichments_applied=[])
        tb.set_rewritten_query(rq)
        trace = tb.build()
        assert trace.rewritten_query is rq

    def test_set_execution_plan_stored(self):
        tb = ReasoningTraceBuilder("req-1")
        plan = _make_plan()
        tb.set_execution_plan(plan)
        trace = tb.build()
        assert trace.execution_plan is plan

    def test_reasoning_depth_set_from_plan(self):
        tb = ReasoningTraceBuilder("req-1")
        plan = _make_plan()
        tb.set_execution_plan(plan)
        trace = tb.build()
        assert trace.reasoning_depth == ReasoningDepth.SINGLE_PASS

    def test_set_confidence_stored(self):
        tb = ReasoningTraceBuilder("req-1")
        conf = _make_confidence()
        tb.set_confidence(conf)
        trace = tb.build()
        assert trace.confidence_report is conf

    def test_add_quality_signal_appended(self):
        tb = ReasoningTraceBuilder("req-1")
        signal = QualitySignal(
            signal_type="expansion_needed",
            intent="coding",
            strategy="coding",
            complexity="medium",
        )
        tb.add_quality_signal(signal)
        trace = tb.build()
        assert len(trace.quality_signals) == 1

    def test_measure_context_manager_records_timing(self):
        tb = ReasoningTraceBuilder("req-1")
        with tb.measure("goal"):
            pass
        trace = tb.build()
        assert trace.goal_analysis_ms >= 0.0

    def test_all_timing_stages_recorded(self):
        tb = ReasoningTraceBuilder("req-1")
        for stage in ["goal", "rewrite", "decompose", "plan", "confidence", "validate", "reflect"]:
            with tb.measure(stage):
                pass
        trace = tb.build()
        assert trace.goal_analysis_ms >= 0.0
        assert trace.query_rewrite_ms >= 0.0
        assert trace.decomposition_ms >= 0.0
        assert trace.planning_ms >= 0.0
        assert trace.confidence_ms >= 0.0
        assert trace.validation_ms >= 0.0
        assert trace.reflection_ms >= 0.0
