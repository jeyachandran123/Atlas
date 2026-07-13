"""
Core domain models for the Conversation Intelligence Engine.

These are the data structures that flow between every module.
All modules depend on these models — never on each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ── Enumerations ──────────────────────────────────────────────────────────────


class Intent(str, Enum):
    GENERAL_CHAT = "general_chat"
    CODING = "coding"
    DEBUGGING = "debugging"
    ARCHITECTURE = "architecture"
    REPOSITORY_QUESTION = "repository_question"
    DOCUMENTATION = "documentation"
    LEARNING = "learning"
    DEEP_TEACHING = "deep_teaching"
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    DOCUMENT_ANALYSIS = "document_analysis"
    RESEARCH = "research"
    BRAINSTORMING = "brainstorming"
    PLANNING = "planning"
    REFACTORING = "refactoring"
    TESTING = "testing"
    GIT_OPERATIONS = "git_operations"
    TOOL_EXECUTION = "tool_execution"
    UNKNOWN = "unknown"


class Complexity(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"
    VERY_COMPLEX = "very_complex"


class ConversationTurn(str, Enum):
    NEW_TOPIC = "new_topic"
    CONTINUATION = "continuation"
    FOLLOW_UP = "follow_up"
    CORRECTION = "correction"
    CLARIFICATION = "clarification"


class ResponseStrategy(str, Enum):
    TEACHING = "teaching"
    CODING = "coding"
    ARCHITECTURE = "architecture"
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    TROUBLESHOOTING = "troubleshooting"
    BRAINSTORMING = "brainstorming"
    RESEARCH = "research"
    DIRECT_ANSWER = "direct_answer"
    STEP_BY_STEP = "step_by_step"


class Persona(str, Enum):
    TEACHER = "teacher"
    SENIOR_ENGINEER = "senior_engineer"
    ARCHITECT = "architect"
    RESEARCH_ASSISTANT = "research_assistant"
    TECHNICAL_WRITER = "technical_writer"
    REVIEWER = "reviewer"
    DEBUGGER = "debugger"


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    WARN = "warn"
    REQUIRE_CONFIRMATION = "require_confirmation"


class ReviewDecision(str, Enum):
    APPROVED = "approved"
    REGENERATE = "regenerate"
    NEEDS_FORMATTING = "needs_formatting"


# ── Data Models ───────────────────────────────────────────────────────────────


@dataclass
class DetectedIntent:
    intent: Intent
    confidence: float  # 0.0 – 1.0
    signals: list[str] = field(default_factory=list)  # keywords/patterns that triggered


@dataclass
class IntentAnalysis:
    """Result of intent detection. Supports multiple simultaneous intents."""
    primary: DetectedIntent
    secondary: list[DetectedIntent] = field(default_factory=list)
    raw_message: str = ""

    @property
    def all_intents(self) -> list[Intent]:
        return [self.primary.intent] + [s.intent for s in self.secondary]


@dataclass
class ComplexityAnalysis:
    level: Complexity
    expected_response_length: str        # "short" | "medium" | "long" | "very_long"
    reasoning_depth: str                 # "surface" | "moderate" | "deep" | "exhaustive"
    estimated_tool_calls: int
    estimated_context_tokens: int
    expected_token_budget: int
    response_strategy_hint: ResponseStrategy
    signals: list[str] = field(default_factory=list)


@dataclass
class ConversationAnalysis:
    turn_type: ConversationTurn
    topic_summary: str
    user_goal: str
    is_continuation: bool
    referenced_prior_turn: bool
    prior_context_summary: str = ""
    assumptions: list[str] = field(default_factory=list)


@dataclass
class PolicyResult:
    decision: PolicyDecision
    reason: str = ""
    violated_policies: list[str] = field(default_factory=list)
    safe_response: Optional[str] = None  # pre-built refusal message if BLOCK


@dataclass
class ToolPlan:
    should_use_tools: bool
    tools: list[str] = field(default_factory=list)          # ordered tool names
    parallel_groups: list[list[str]] = field(default_factory=list)  # tools that can run in parallel
    rationale: str = ""
    can_answer_without_tools: bool = True


@dataclass
class IntelligenceContext:
    """
    The unified context object produced by UserContextBuilder.
    This is the single structured input to the DynamicPromptComposer.
    """
    # Request
    user_message: str
    conversation_id: str
    user_id: str
    org_id: str
    repo_id: Optional[str]
    agent_mode: str

    # Intelligence layer outputs
    intent_analysis: IntentAnalysis
    complexity: ComplexityAnalysis
    conversation: ConversationAnalysis
    policy: PolicyResult
    persona: Persona
    strategy: ResponseStrategy

    # Retrieved knowledge
    session_messages: list[dict] = field(default_factory=list)
    memory_context: str = ""
    code_context_block: str = ""
    retrieved_chunks_count: int = 0

    # Tool decisions
    tool_plan: Optional[ToolPlan] = None

    # Tool results (populated after execution)
    tool_results: list[Any] = field(default_factory=list)

    # Metadata
    request_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReviewResult:
    decision: ReviewDecision
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    score: float = 1.0  # 0.0 – 1.0


@dataclass
class IntelligenceTrace:
    """
    Observability record for a single request through the engine.
    Produced after every request for debugging and monitoring.
    """
    request_id: str
    user_message_preview: str  # first 100 chars

    # Module outputs
    detected_intents: list[str] = field(default_factory=list)
    primary_intent_confidence: float = 0.0
    complexity_level: str = ""
    conversation_turn_type: str = ""
    policy_decision: str = ""
    selected_persona: str = ""
    selected_strategy: str = ""
    tool_plan: Optional[ToolPlan] = None
    review_decision: str = ""

    # Timing (ms)
    intent_ms: float = 0.0
    complexity_ms: float = 0.0
    conversation_ms: float = 0.0
    policy_ms: float = 0.0
    context_build_ms: float = 0.0
    prompt_compose_ms: float = 0.0
    llm_ms: float = 0.0
    review_ms: float = 0.0
    total_ms: float = 0.0

    # Prompt metadata
    prompt_modules_used: list[str] = field(default_factory=list)
    prompt_token_estimate: int = 0
