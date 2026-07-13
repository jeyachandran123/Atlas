"""
Reasoning domain models.

All data structures that flow through the Reasoning Engine.
No logic lives here — only typed data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ── Enumerations ──────────────────────────────────────────────────────────────


class GoalType(str, Enum):
    FIND_AND_FIX        = "find_and_fix"
    UNDERSTAND          = "understand"
    BUILD               = "build"
    IMPROVE             = "improve"
    VALIDATE            = "validate"
    RESEARCH            = "research"
    DECIDE              = "decide"
    EXPLAIN             = "explain"
    COMPARE             = "compare"
    PLAN                = "plan"
    UNKNOWN             = "unknown"


class TaskStatus(str, Enum):
    PENDING     = "pending"
    RUNNING     = "running"
    DONE        = "done"
    SKIPPED     = "skipped"
    FAILED      = "failed"


class ExecutionMode(str, Enum):
    SEQUENTIAL  = "sequential"
    PARALLEL    = "parallel"
    CONDITIONAL = "conditional"


class ConfidenceLevel(str, Enum):
    HIGH        = "high"       # >= 0.75
    MEDIUM      = "medium"     # >= 0.50
    LOW         = "low"        # >= 0.25
    VERY_LOW    = "very_low"   # <  0.25


class ReflectionVerdict(str, Enum):
    SATISFACTORY        = "satisfactory"
    NEEDS_EXPANSION     = "needs_expansion"
    MISSED_GOAL         = "missed_goal"
    STRATEGY_MISMATCH   = "strategy_mismatch"


class ValidationVerdict(str, Enum):
    VALID       = "valid"
    MISMATCH    = "mismatch"
    AMBIGUOUS   = "ambiguous"


class ReasoningDepth(str, Enum):
    SINGLE_PASS = "single_pass"   # simple questions
    MULTI_STEP  = "multi_step"    # complex engineering tasks


# ── Goal ─────────────────────────────────────────────────────────────────────


@dataclass
class InferredGoal:
    """
    The actual goal Atlas inferred from the user message.
    Users rarely state goals directly — this is the translation.
    """
    goal_type: GoalType
    primary_objective: str          # one clear sentence
    sub_objectives: list[str]       # ordered steps to achieve the goal
    success_criteria: list[str]     # how to know the goal was achieved
    requires_repo: bool = False
    requires_tools: bool = False
    confidence: float = 1.0
    raw_message: str = ""


# ── Query Rewrite ─────────────────────────────────────────────────────────────


@dataclass
class RewrittenQuery:
    """
    The enriched version of the user's message.
    Never changes meaning — only adds missing context.
    """
    original: str
    rewritten: str
    enrichments_applied: list[str]  # what context was added
    persona_hint: str = ""          # audience level inferred
    domain_hint: str = ""           # domain inferred (e.g. "web development")


# ── Task Decomposition ────────────────────────────────────────────────────────


@dataclass
class ReasoningTask:
    """A single executable unit of work within a decomposed request."""
    task_id: str
    description: str
    tool_hint: Optional[str]        # which tool this task likely needs
    depends_on: list[str]           # task_ids this must wait for
    can_cache: bool = False
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None


@dataclass
class TaskDecomposition:
    """The full breakdown of a complex request into ordered tasks."""
    tasks: list[ReasoningTask]
    total_tasks: int
    requires_tools: bool
    estimated_steps: int
    decomposition_rationale: str = ""

    def pending_tasks(self) -> list[ReasoningTask]:
        return [t for t in self.tasks if t.status == TaskStatus.PENDING]

    def ready_tasks(self) -> list[ReasoningTask]:
        """Tasks whose dependencies are all DONE."""
        done_ids = {t.task_id for t in self.tasks if t.status == TaskStatus.DONE}
        return [
            t for t in self.tasks
            if t.status == TaskStatus.PENDING
            and all(dep in done_ids for dep in t.depends_on)
        ]


# ── Execution Plan ────────────────────────────────────────────────────────────


@dataclass
class ExecutionStep:
    """One step in the execution plan."""
    step_id: str
    task_ids: list[str]             # tasks in this step
    mode: ExecutionMode
    can_reuse_context: bool = False
    needs_retrieval: bool = False
    cache_key: Optional[str] = None


@dataclass
class ExecutionPlan:
    """
    Ordered execution graph produced by the ExecutionPlanner.
    Determines what runs when, what can run in parallel, and what can be cached.
    """
    steps: list[ExecutionStep]
    total_steps: int
    has_parallel_steps: bool
    reasoning_depth: ReasoningDepth
    estimated_tool_calls: int
    plan_rationale: str = ""


# ── Confidence ────────────────────────────────────────────────────────────────


@dataclass
class ConfidenceScore:
    """Confidence measurement for a single reasoning dimension."""
    dimension: str          # e.g. "intent", "goal", "tool_selection"
    score: float            # 0.0 – 1.0
    level: ConfidenceLevel
    reason: str = ""


@dataclass
class ConfidenceReport:
    """
    Aggregated confidence across all reasoning dimensions.
    Drives decisions: clarify, retrieve more, or proceed.
    """
    scores: list[ConfidenceScore]
    overall: float
    overall_level: ConfidenceLevel
    should_clarify: bool            # True if overall < LOW threshold
    should_retrieve_more: bool      # True if repo_match confidence is low
    clarification_question: str = ""  # pre-built question if should_clarify

    def get(self, dimension: str) -> Optional[ConfidenceScore]:
        return next((s for s in self.scores if s.dimension == dimension), None)


# ── Reflection ────────────────────────────────────────────────────────────────


@dataclass
class WeakSection:
    """A section of the response identified as needing expansion."""
    section_id: str
    description: str            # what this section covers
    weakness_reason: str        # why it's weak
    expansion_hint: str         # what to add


@dataclass
class ReflectionResult:
    """
    Post-generation reflection on whether the response achieved the goal.
    Never about grammar — always about goal achievement.
    """
    verdict: ReflectionVerdict
    goal_achieved: bool
    missed_objectives: list[str]
    weak_sections: list[WeakSection]
    alternative_strategy: Optional[str]  # if strategy_mismatch
    reflection_notes: str = ""


# ── Expansion ─────────────────────────────────────────────────────────────────


@dataclass
class ExpansionTarget:
    """Identifies exactly what needs to be expanded in a response."""
    section_id: str
    current_content: str        # the weak content
    expansion_instruction: str  # what to add/improve
    priority: int               # 1 = highest


@dataclass
class ExpansionPlan:
    """
    Plan for targeted response expansion.
    Only expands weak sections — never regenerates the full response.
    """
    targets: list[ExpansionTarget]
    full_regeneration_needed: bool
    rationale: str = ""

    def highest_priority(self) -> Optional[ExpansionTarget]:
        if not self.targets:
            return None
        return min(self.targets, key=lambda t: t.priority)


# ── Goal Memory ───────────────────────────────────────────────────────────────


@dataclass
class GoalMemoryEntry:
    """A stored goal from a prior conversation turn."""
    goal_id: str
    conversation_id: str
    user_id: str
    goal: InferredGoal
    turn_index: int             # which turn this goal was set
    is_active: bool = True      # False when user explicitly changes topic
    created_at: str = ""        # ISO timestamp


@dataclass
class ActiveGoalContext:
    """
    The current active goal context for a conversation.
    Allows Atlas to answer relative to long-running objectives.
    """
    current_goal: Optional[InferredGoal]
    prior_goals: list[GoalMemoryEntry]
    goal_continuity: bool       # True if current message continues prior goal
    continuity_reason: str = ""


# ── Strategy Validation ───────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """Result of validating the selected response strategy against the goal."""
    verdict: ValidationVerdict
    selected_strategy: str
    expected_strategy: str
    mismatch_reason: str = ""
    corrected_strategy: Optional[str] = None


# ── Adaptive Signals ──────────────────────────────────────────────────────────


@dataclass
class QualitySignal:
    """
    An anonymous quality observation collected during a request.
    Drives adaptive learning — never contains PII.
    """
    signal_type: str            # "expansion_needed" | "clarification_needed" | "tool_failed" | "repo_miss"
    intent: str
    complexity: str
    strategy: str
    detail: str = ""            # non-PII detail


# ── Reasoning Trace ───────────────────────────────────────────────────────────


@dataclass
class ReasoningTrace:
    """
    Complete internal reasoning record for a single request.
    Internal only — never exposed to users.
    Used for debugging and observability.
    """
    request_id: str

    # Goal
    inferred_goal: Optional[InferredGoal] = None
    rewritten_query: Optional[RewrittenQuery] = None

    # Decomposition & planning
    task_decomposition: Optional[TaskDecomposition] = None
    execution_plan: Optional[ExecutionPlan] = None

    # Confidence
    confidence_report: Optional[ConfidenceReport] = None

    # Validation
    strategy_validation: Optional[ValidationResult] = None

    # Post-generation
    reflection: Optional[ReflectionResult] = None
    expansion_plan: Optional[ExpansionPlan] = None

    # Goal memory
    active_goal_context: Optional[ActiveGoalContext] = None

    # Reasoning depth used
    reasoning_depth: ReasoningDepth = ReasoningDepth.SINGLE_PASS

    # Timing (ms)
    goal_analysis_ms: float = 0.0
    query_rewrite_ms: float = 0.0
    decomposition_ms: float = 0.0
    planning_ms: float = 0.0
    confidence_ms: float = 0.0
    validation_ms: float = 0.0
    reflection_ms: float = 0.0
    total_ms: float = 0.0

    # Quality signals collected this turn
    quality_signals: list[QualitySignal] = field(default_factory=list)
