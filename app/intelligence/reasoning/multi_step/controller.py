"""
Multi-Step Reasoning Controller.

Determines how many reasoning passes a request requires.
Simple questions: one pass.
Complex engineering tasks: reason → plan → retrieve → reason → tool → reason → respond.

This controller does not execute the passes — it decides the depth
and produces a ReasoningSchedule that the engine follows.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.intelligence.reasoning.models import (
    ExecutionPlan,
    GoalType,
    InferredGoal,
    ReasoningDepth,
)

# Complexity → max reasoning passes
_COMPLEXITY_PASSES: dict[str, int] = {
    "simple":       1,
    "medium":       2,
    "complex":      3,
    "very_complex": 4,
}

# GoalTypes that always need at least 2 passes
_MULTI_PASS_GOALS = {
    GoalType.FIND_AND_FIX,
    GoalType.BUILD,
    GoalType.IMPROVE,
    GoalType.VALIDATE,
    GoalType.PLAN,
}


@dataclass
class ReasoningPass:
    """A single reasoning pass in the multi-step schedule."""
    pass_number: int
    purpose: str            # "initial_analysis" | "tool_integration" | "synthesis" | "validation"
    needs_tools: bool
    needs_retrieval: bool
    is_final: bool


@dataclass
class ReasoningSchedule:
    """
    The complete multi-step reasoning schedule for a request.
    Produced before any LLM call is made.
    """
    passes: list[ReasoningPass]
    total_passes: int
    depth: ReasoningDepth
    rationale: str


class MultiStepReasoningController:
    """
    Determines the reasoning schedule for a request.
    No LLM call — pure decision logic.
    """

    def schedule(
        self,
        goal: InferredGoal,
        execution_plan: ExecutionPlan,
        complexity_level: str,
    ) -> ReasoningSchedule:
        max_passes = _COMPLEXITY_PASSES.get(complexity_level, 1)

        # Force at least 2 passes for multi-pass goal types
        if goal.goal_type in _MULTI_PASS_GOALS and max_passes < 2:
            max_passes = 2

        # Single pass for simple goals
        if max_passes == 1:
            return ReasoningSchedule(
                passes=[ReasoningPass(
                    pass_number=1,
                    purpose="direct_response",
                    needs_tools=execution_plan.estimated_tool_calls > 0,
                    needs_retrieval=any(s.needs_retrieval for s in execution_plan.steps),
                    is_final=True,
                )],
                total_passes=1,
                depth=ReasoningDepth.SINGLE_PASS,
                rationale=f"Simple request — single reasoning pass",
            )

        # Multi-step schedule
        passes = self._build_passes(goal, execution_plan, max_passes)
        return ReasoningSchedule(
            passes=passes,
            total_passes=len(passes),
            depth=ReasoningDepth.MULTI_STEP,
            rationale=(
                f"Goal '{goal.goal_type.value}' with complexity '{complexity_level}' "
                f"requires {len(passes)} reasoning passes"
            ),
        )

    def _build_passes(
        self,
        goal: InferredGoal,
        plan: ExecutionPlan,
        max_passes: int,
    ) -> list[ReasoningPass]:
        passes: list[ReasoningPass] = []

        # Pass 1: Initial analysis — understand the problem
        passes.append(ReasoningPass(
            pass_number=1,
            purpose="initial_analysis",
            needs_tools=False,
            needs_retrieval=any(s.needs_retrieval for s in plan.steps[:1]),
            is_final=False,
        ))

        # Middle passes: tool integration
        # When max_passes == 2, there are no middle passes — the synthesis pass
        # below carries needs_tools=True to ensure at least one tool pass exists.
        tool_steps = [s for s in plan.steps if s.needs_retrieval or any(
            True for tid in s.task_ids  # has tasks
        )]
        for i, step in enumerate(tool_steps[:max_passes - 2], start=2):
            passes.append(ReasoningPass(
                pass_number=i,
                purpose="tool_integration",
                needs_tools=True,
                needs_retrieval=step.needs_retrieval,
                is_final=False,
            ))

        # Final pass: synthesis
        # When max_passes == 2, this is the only action pass — mark needs_tools
        # so the executor knows tools are required in this schedule.
        is_two_pass = max_passes == 2
        passes.append(ReasoningPass(
            pass_number=len(passes) + 1,
            purpose="synthesis",
            needs_tools=is_two_pass and plan.estimated_tool_calls > 0,
            needs_retrieval=False,
            is_final=True,
        ))

        return passes[:max_passes]


# ── Singleton ─────────────────────────────────────────────────────────────────

_controller: MultiStepReasoningController | None = None


def get_multi_step_controller() -> MultiStepReasoningController:
    global _controller
    if _controller is None:
        _controller = MultiStepReasoningController()
    return _controller
