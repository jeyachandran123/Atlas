"""
Reasoning Engine.

The thinking layer of Atlas. Sits between the Conversation Intelligence Engine
and the Prompt Composer.

The Conversation Intelligence Engine decides HOW Atlas communicates.
The Reasoning Engine decides HOW Atlas thinks.

Pipeline (pre-LLM):
    IntelligenceContext
        → GoalAnalyzer          (what is the user actually trying to achieve?)
        → QueryRewriter         (enrich the query with missing context)
        → TaskDecomposer        (break complex requests into tasks)
        → ExecutionPlanner      (build the execution graph)
        → ConfidenceEvaluator   (are we confident enough to proceed?)
        → StrategyValidator     (does the strategy match the goal?)
        → MultiStepController   (how many reasoning passes are needed?)
        → GoalMemory            (store goal for future turns)
        → AdaptiveLearner       (apply accumulated adjustments)
        → ReasoningTrace        (record everything for observability)

Pipeline (post-LLM):
    LLM Response
        → ReflectionEngine      (did we achieve the goal?)
        → ExpansionEngine       (what needs to be expanded?)
        → AdaptiveLearner       (record quality signals)

Design:
- Never calls the LLM
- Never contains prompt templates
- Every module is independently injectable and testable
- Graceful degradation: any module failure falls back silently
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from app.intelligence.reasoning.adaptive.learner import AdaptiveLearner, get_adaptive_learner
from app.intelligence.reasoning.confidence.evaluator import (
    ConfidenceEvaluator,
    get_confidence_evaluator,
)
from app.intelligence.reasoning.decomposer.decomposer import (
    TaskDecomposer,
    get_task_decomposer,
)
from app.intelligence.reasoning.expansion.engine import ExpansionEngine, get_expansion_engine
from app.intelligence.reasoning.goal.analyzer import GoalAnalyzer, get_goal_analyzer
from app.intelligence.reasoning.goal_memory.memory import GoalMemory, get_goal_memory
from app.intelligence.reasoning.models import (
    ActiveGoalContext,
    ConfidenceLevel,
    ConfidenceReport,
    ExecutionMode,
    ExecutionPlan,
    ExecutionStep,
    ExpansionPlan,
    GoalType,
    InferredGoal,
    QualitySignal,
    ReasoningDepth,
    ReasoningTrace,
    ReflectionResult,
    ReflectionVerdict,
    RewrittenQuery,
    TaskDecomposition,
    ValidationResult,
    ValidationVerdict,
)
from app.intelligence.reasoning.multi_step.controller import (
    MultiStepReasoningController,
    ReasoningPass,
    ReasoningSchedule,
    get_multi_step_controller,
)
from app.intelligence.reasoning.planner.planner import ExecutionPlanner, get_execution_planner
from app.intelligence.reasoning.reflection.engine import ReflectionEngine, get_reflection_engine
from app.intelligence.reasoning.rewriter.rewriter import QueryRewriter, get_query_rewriter
from app.intelligence.reasoning.trace.builder import ReasoningTraceBuilder
from app.intelligence.reasoning.validation.validator import (
    StrategyValidator,
    get_strategy_validator,
)


@dataclass
class ReasoningResult:
    """
    Output of the pre-LLM reasoning pipeline.
    Passed to the Prompt Composer.
    """
    # Core outputs consumed by the prompt composer
    goal: InferredGoal
    rewritten_query: RewrittenQuery
    execution_plan: ExecutionPlan
    reasoning_schedule: ReasoningSchedule

    # Confidence — drives clarification decisions
    confidence: ConfidenceReport
    should_clarify: bool
    clarification_question: str

    # Strategy correction (if mismatch detected)
    corrected_strategy: Optional[str]

    # Adaptive adjustments
    adjustments: dict

    # Internal trace (never exposed to users)
    trace: ReasoningTrace


@dataclass
class PostGenerationResult:
    """Output of the post-LLM reasoning pipeline."""
    reflection: ReflectionResult
    expansion_plan: ExpansionPlan
    needs_expansion: bool
    needs_full_regeneration: bool
    trace: ReasoningTrace


class ReasoningEngine:
    """
    Orchestrates all reasoning modules.

    Pre-LLM:  think() → ReasoningResult
    Post-LLM: reflect() → PostGenerationResult
    """

    def __init__(
        self,
        goal_analyzer: Optional[GoalAnalyzer] = None,
        query_rewriter: Optional[QueryRewriter] = None,
        task_decomposer: Optional[TaskDecomposer] = None,
        execution_planner: Optional[ExecutionPlanner] = None,
        confidence_evaluator: Optional[ConfidenceEvaluator] = None,
        reflection_engine: Optional[ReflectionEngine] = None,
        expansion_engine: Optional[ExpansionEngine] = None,
        goal_memory: Optional[GoalMemory] = None,
        strategy_validator: Optional[StrategyValidator] = None,
        multi_step_controller: Optional[MultiStepReasoningController] = None,
        adaptive_learner: Optional[AdaptiveLearner] = None,
    ) -> None:
        self._goal_analyzer       = goal_analyzer       or get_goal_analyzer()
        self._query_rewriter      = query_rewriter      or get_query_rewriter()
        self._task_decomposer     = task_decomposer     or get_task_decomposer()
        self._execution_planner   = execution_planner   or get_execution_planner()
        self._confidence          = confidence_evaluator or get_confidence_evaluator()
        self._reflection          = reflection_engine   or get_reflection_engine()
        self._expansion           = expansion_engine    or get_expansion_engine()
        self._goal_memory         = goal_memory         or get_goal_memory()
        self._validator           = strategy_validator  or get_strategy_validator()
        self._multi_step          = multi_step_controller or get_multi_step_controller()
        self._adaptive            = adaptive_learner    or get_adaptive_learner()

    # ── Pre-LLM pipeline ─────────────────────────────────────────────────────

    def think(self, context, request_id: Optional[str] = None) -> ReasoningResult:
        """
        Run the full pre-LLM reasoning pipeline.

        Input:  IntelligenceContext (from ConversationIntelligenceEngine)
        Output: ReasoningResult with goal, plan, confidence, and trace

        Graceful degradation: any module failure produces a safe fallback.
        """
        rid = request_id or str(uuid.uuid4())
        tb = ReasoningTraceBuilder(rid)

        active_goal_ctx = self._load_active_goal_context(context, tb)
        goal            = self._run_goal_analysis(context, active_goal_ctx, tb)
        rewritten       = self._run_query_rewrite(context, goal, tb)
        decomposition   = self._run_task_decomposition(context, goal, tb)
        execution_plan  = self._run_execution_planning(context, decomposition, tb)
        confidence      = self._run_confidence_evaluation(context, goal, tb)
        validation      = self._run_strategy_validation(context, goal, tb)
        schedule        = self._run_multi_step_schedule(context, goal, execution_plan)
        adjustments     = self._get_adaptive_adjustments(context)
        self._store_goal(context, goal)

        trace = tb.build()
        return ReasoningResult(
            goal=goal,
            rewritten_query=rewritten,
            execution_plan=execution_plan,
            reasoning_schedule=schedule,
            confidence=confidence,
            should_clarify=confidence.should_clarify,
            clarification_question=confidence.clarification_question,
            corrected_strategy=(
                validation.corrected_strategy
                if validation.verdict == ValidationVerdict.MISMATCH
                else None
            ),
            adjustments=adjustments,
            trace=trace,
        )

    # ── Pre-LLM pipeline stages ───────────────────────────────────────────────

    def _load_active_goal_context(self, context, tb: ReasoningTraceBuilder) -> ActiveGoalContext:
        fallback_goal = InferredGoal(
            goal_type=GoalType.UNKNOWN,
            primary_objective=context.user_message[:80],
            sub_objectives=[],
            success_criteria=[],
            raw_message=context.user_message,
        )
        ctx = self._safe(
            lambda: self._goal_memory.get_active_context(
                user_id=context.user_id,
                conversation_id=context.conversation_id,
                current_goal=fallback_goal,
            ),
            fallback=ActiveGoalContext(current_goal=None, prior_goals=[], goal_continuity=False),
        )
        tb.set_active_goal_context(ctx)
        return ctx

    def _run_goal_analysis(self, context, active_goal_ctx: ActiveGoalContext, tb: ReasoningTraceBuilder) -> InferredGoal:
        with tb.measure("goal"):
            goal = self._safe(
                lambda: self._goal_analyzer.analyze(context.user_message, context, active_goal_ctx),
                fallback=self._fallback_goal(context),
            )
        tb.set_goal(goal)
        return goal

    def _run_query_rewrite(self, context, goal: InferredGoal, tb: ReasoningTraceBuilder) -> RewrittenQuery:
        with tb.measure("rewrite"):
            rewritten = self._safe(
                lambda: self._query_rewriter.rewrite(context.user_message, goal, context),
                fallback=RewrittenQuery(
                    original=context.user_message,
                    rewritten=context.user_message,
                    enrichments_applied=[],
                ),
            )
        tb.set_rewritten_query(rewritten)
        return rewritten

    def _run_task_decomposition(self, context, goal: InferredGoal, tb: ReasoningTraceBuilder) -> TaskDecomposition:
        with tb.measure("decompose"):
            decomposition = self._safe(
                lambda: self._task_decomposer.decompose(goal, context),
                fallback=TaskDecomposition(
                    tasks=[], total_tasks=0, requires_tools=False,
                    estimated_steps=1, decomposition_rationale="fallback",
                ),
            )
        tb.set_decomposition(decomposition)
        return decomposition

    def _run_execution_planning(self, context, decomposition: TaskDecomposition, tb: ReasoningTraceBuilder) -> ExecutionPlan:
        with tb.measure("plan"):
            execution_plan = self._safe(
                lambda: self._execution_planner.plan(decomposition, context),
                fallback=ExecutionPlan(
                    steps=[ExecutionStep(step_id="fallback", task_ids=[], mode=ExecutionMode.SEQUENTIAL)],
                    total_steps=1,
                    has_parallel_steps=False,
                    reasoning_depth=ReasoningDepth.SINGLE_PASS,
                    estimated_tool_calls=0,
                    plan_rationale="fallback",
                ),
            )
        tb.set_execution_plan(execution_plan)
        return execution_plan

    def _run_confidence_evaluation(self, context, goal: InferredGoal, tb: ReasoningTraceBuilder) -> ConfidenceReport:
        with tb.measure("confidence"):
            confidence = self._safe(
                lambda: self._confidence.evaluate(goal, context),
                fallback=ConfidenceReport(
                    scores=[],
                    overall=0.8,
                    overall_level=ConfidenceLevel.HIGH,
                    should_clarify=False,
                    should_retrieve_more=False,
                ),
            )
        tb.set_confidence(confidence)
        return confidence

    def _run_strategy_validation(self, context, goal: InferredGoal, tb: ReasoningTraceBuilder) -> ValidationResult:
        strategy = context.strategy.value if context.strategy else "direct_answer"
        with tb.measure("validate"):
            validation = self._safe(
                lambda: self._validator.validate(goal, context),
                fallback=ValidationResult(
                    verdict=ValidationVerdict.VALID,
                    selected_strategy=strategy,
                    expected_strategy=strategy,
                ),
            )
        tb.set_validation(validation)
        return validation

    def _run_multi_step_schedule(self, context, goal: InferredGoal, execution_plan: ExecutionPlan) -> ReasoningSchedule:
        return self._safe(
            lambda: self._multi_step.schedule(goal, execution_plan, context.complexity.level.value),
            fallback=self._fallback_schedule(),
        )

    def _get_adaptive_adjustments(self, context) -> dict:
        intent   = context.intent_analysis.primary.intent.value
        strategy = context.strategy.value if context.strategy else "direct_answer"
        return self._adaptive.get_adjustments(intent, strategy)

    def _store_goal(self, context, goal: InferredGoal) -> None:
        turn_index = len(context.session_messages)
        self._safe(
            lambda: self._goal_memory.store(context.user_id, context.conversation_id, goal, turn_index),
            fallback=None,
        )

    # ── Post-LLM pipeline ─────────────────────────────────────────────────────

    def reflect(
        self,
        response: str,
        context,
        reasoning_result: ReasoningResult,
    ) -> PostGenerationResult:
        """
        Run the post-LLM reflection and expansion pipeline.

        Input:  LLM response + IntelligenceContext + ReasoningResult
        Output: PostGenerationResult with reflection and expansion plan
        """
        tb = ReasoningTraceBuilder(reasoning_result.trace.request_id)

        # ── Reflection ────────────────────────────────────────────────────────
        with tb.measure("reflect"):
            reflection = self._safe(
                lambda: self._reflection.reflect(response, reasoning_result.goal, context),
                fallback=ReflectionResult(
                    verdict=ReflectionVerdict.SATISFACTORY,
                    goal_achieved=True,
                    missed_objectives=[],
                    weak_sections=[],
                    alternative_strategy=None,
                ),
            )
        tb.set_reflection(reflection)

        # ── Expansion Planning ────────────────────────────────────────────────
        expansion_plan = self._safe(
            lambda: self._expansion.plan_expansion(response, reflection, context),
            fallback=ExpansionPlan(targets=[], full_regeneration_needed=False),
        )
        tb.set_expansion_plan(expansion_plan)

        # ── Record quality signals ────────────────────────────────────────────
        intent = context.intent_analysis.primary.intent.value
        strategy = context.strategy.value if context.strategy else "direct_answer"

        complexity = context.complexity.level.value

        if expansion_plan.targets:
            signal = QualitySignal(
                signal_type="expansion_needed",
                intent=intent,
                strategy=strategy,
                complexity=complexity,
                detail=f"{len(expansion_plan.targets)} sections",
            )
            self._adaptive.record(signal)
            tb.add_quality_signal(signal)

        if reasoning_result.should_clarify:
            signal = QualitySignal(
                signal_type="clarification_needed",
                intent=intent,
                strategy=strategy,
                complexity=complexity,
            )
            self._adaptive.record(signal)
            tb.add_quality_signal(signal)

        if reasoning_result.trace.confidence_report:
            repo_score = reasoning_result.trace.confidence_report.get("repo_match")
            if repo_score and repo_score.score < 0.3 and context.repo_id:
                signal = QualitySignal(
                    signal_type="repo_miss",
                    intent=intent,
                    strategy=strategy,
                    complexity=complexity,
                )
                self._adaptive.record(signal)
                tb.add_quality_signal(signal)

        trace = tb.build()

        return PostGenerationResult(
            reflection=reflection,
            expansion_plan=expansion_plan,
            needs_expansion=bool(expansion_plan.targets),
            needs_full_regeneration=expansion_plan.full_regeneration_needed,
            trace=trace,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _safe(self, fn, fallback):
        """Execute fn(); return fallback on any exception."""
        try:
            return fn()
        except Exception as e:
            from loguru import logger
            logger.warning(f"ReasoningEngine module failed (non-blocking): {e}")
            return fallback

    def _fallback_goal(self, context) -> InferredGoal:
        return InferredGoal(
            goal_type=GoalType.UNKNOWN,
            primary_objective=context.user_message[:80],
            sub_objectives=[],
            success_criteria=[],
            raw_message=context.user_message,
        )

    def _fallback_schedule(self) -> ReasoningSchedule:
        return ReasoningSchedule(
            passes=[ReasoningPass(
                pass_number=1,
                purpose="direct_response",
                needs_tools=False,
                needs_retrieval=False,
                is_final=True,
            )],
            total_passes=1,
            depth=ReasoningDepth.SINGLE_PASS,
            rationale="fallback schedule",
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: ReasoningEngine | None = None


def get_reasoning_engine() -> ReasoningEngine:
    global _engine
    if _engine is None:
        _engine = ReasoningEngine()
    return _engine
