"""
Shared fixtures for reasoning module tests.
Builds a minimal but complete IntelligenceContext.
"""
from __future__ import annotations
import pytest
from app.intelligence.models import (
    ComplexityAnalysis,
    ConversationAnalysis,
    ConversationTurn,
    Complexity,
    DetectedIntent,
    Intent,
    IntentAnalysis,
    IntelligenceContext,
    Persona,
    PolicyDecision,
    PolicyResult,
    ResponseStrategy,
    ToolPlan,
)
from app.intelligence.reasoning.models import ActiveGoalContext, GoalType, InferredGoal


def make_context(
    message: str = "Fix the authentication bug in my code",
    intent: Intent = Intent.DEBUGGING,
    intent_confidence: float = 0.9,
    complexity: Complexity = Complexity.COMPLEX,
    strategy: ResponseStrategy = ResponseStrategy.TROUBLESHOOTING,
    repo_id: str | None = "repo-123",
    retrieved_chunks: int = 5,
    session_messages: list | None = None,
    assumptions: list | None = None,
) -> IntelligenceContext:
    return IntelligenceContext(
        user_message=message,
        conversation_id="conv-001",
        user_id="user-001",
        org_id="org-001",
        repo_id=repo_id,
        agent_mode="auto",
        intent_analysis=IntentAnalysis(
            primary=DetectedIntent(intent=intent, confidence=intent_confidence, signals=["bug", "fix"]),
            secondary=[],
            raw_message=message,
        ),
        complexity=ComplexityAnalysis(
            level=complexity,
            expected_response_length="long",
            reasoning_depth="deep",
            estimated_tool_calls=2,
            estimated_context_tokens=1000,
            expected_token_budget=4000,
            response_strategy_hint=strategy,
            signals=["complex", "multi-step"],
        ),
        conversation=ConversationAnalysis(
            turn_type=ConversationTurn.NEW_TOPIC,
            topic_summary="auth bug fix",
            user_goal="fix authentication",
            is_continuation=False,
            referenced_prior_turn=False,
            assumptions=assumptions or ["Python backend", "FastAPI"],
        ),
        policy=PolicyResult(decision=PolicyDecision.ALLOW),
        persona=Persona.DEBUGGER,
        strategy=strategy,
        session_messages=session_messages or [],
        retrieved_chunks_count=retrieved_chunks,
        code_context_block="def authenticate(): pass" if retrieved_chunks > 0 else "",
        tool_plan=ToolPlan(should_use_tools=True, tools=["search_code", "read_file"]),
    )


def make_goal(
    goal_type: GoalType = GoalType.FIND_AND_FIX,
    message: str = "Fix the authentication bug",
    requires_repo: bool = True,
    requires_tools: bool = True,
    confidence: float = 0.9,
) -> InferredGoal:
    return InferredGoal(
        goal_type=goal_type,
        primary_objective=f"Find and fix: {message[:60]}",
        sub_objectives=[
            "Locate the relevant implementation",
            "Identify the root cause",
            "Apply the fix",
        ],
        success_criteria=["Problem identified", "Fix applied", "Explanation clear"],
        requires_repo=requires_repo,
        requires_tools=requires_tools,
        confidence=confidence,
        raw_message=message,
    )


def make_active_goal_context(goal: InferredGoal | None = None) -> ActiveGoalContext:
    return ActiveGoalContext(
        current_goal=goal,
        prior_goals=[],
        goal_continuity=False,
    )
