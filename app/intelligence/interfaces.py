"""
Abstract base classes for every intelligence module.

Every module in the engine implements one of these interfaces.
This enables:
- Independent testability (mock any interface)
- Replaceability (swap implementations without touching orchestration)
- Dependency injection (engine depends on abstractions, not concretions)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.state import AgentState
    from app.intelligence.models import (
        ComplexityAnalysis,
        ConversationAnalysis,
        IntelligenceContext,
        IntentAnalysis,
        PersonaEngine,
        PolicyResult,
        ResponseStrategy,
        ReviewResult,
        ToolPlan,
    )


class AbstractIntentDetector(ABC):
    """Classifies user intent from a raw message and conversation history."""

    @abstractmethod
    def detect(
        self,
        message: str,
        session_messages: list[dict],
        agent_mode: str = "auto",
        repo_active: bool = False,
    ) -> "IntentAnalysis":
        ...


class AbstractComplexityAnalyzer(ABC):
    """Estimates the complexity and resource requirements of a request."""

    @abstractmethod
    def analyze(
        self,
        message: str,
        intent_analysis: "IntentAnalysis",
        session_messages: list[dict],
    ) -> "ComplexityAnalysis":
        ...


class AbstractConversationAnalyzer(ABC):
    """Understands the conversational context and turn type."""

    @abstractmethod
    def analyze(
        self,
        message: str,
        session_messages: list[dict],
        intent_analysis: "IntentAnalysis",
    ) -> "ConversationAnalysis":
        ...


class AbstractPolicyEngine(ABC):
    """Evaluates whether a request is permitted under Atlas policies."""

    @abstractmethod
    def evaluate(
        self,
        message: str,
        intent_analysis: "IntentAnalysis",
        user_id: str,
        org_id: str,
    ) -> "PolicyResult":
        ...


class AbstractPersonaEngine(ABC):
    """Selects the appropriate persona based on intent and context."""

    @abstractmethod
    def select(
        self,
        intent_analysis: "IntentAnalysis",
        agent_mode: str,
        complexity: "ComplexityAnalysis",
    ) -> "PersonaEngine":
        ...


class AbstractResponseStrategyPlanner(ABC):
    """Decides how Atlas should structure and deliver its response."""

    @abstractmethod
    def plan(
        self,
        intent_analysis: "IntentAnalysis",
        complexity: "ComplexityAnalysis",
        conversation: "ConversationAnalysis",
    ) -> "ResponseStrategy":
        ...


class AbstractUserContextBuilder(ABC):
    """Assembles all available context into a single structured object."""

    @abstractmethod
    async def build(self, state: "AgentState") -> "IntelligenceContext":
        ...


class AbstractToolPlanner(ABC):
    """Decides which tools to use, in what order, and whether they're needed."""

    @abstractmethod
    def plan(
        self,
        context: "IntelligenceContext",
    ) -> "ToolPlan":
        ...


class AbstractPromptComposer(ABC):
    """Builds a structured prompt from the intelligence context."""

    @abstractmethod
    def compose(self, context: "IntelligenceContext") -> str:
        ...


class AbstractResponseReviewer(ABC):
    """Reviews LLM output and decides if it meets quality standards."""

    @abstractmethod
    def review(
        self,
        response: str,
        context: "IntelligenceContext",
    ) -> "ReviewResult":
        ...


class AbstractResponseFormatter(ABC):
    """Formats the final response according to the selected strategy."""

    @abstractmethod
    def format(
        self,
        response: str,
        context: "IntelligenceContext",
    ) -> str:
        ...


class AbstractMemoryPort(ABC):
    """
    Memory interface for the intelligence engine.
    Designed so long-term memory can be added without changing orchestration.
    """

    @abstractmethod
    async def get_session(
        self,
        user_id: str,
        conversation_id: str,
        limit: int = 10,
    ) -> list[dict]:
        ...

    @abstractmethod
    async def get_long_term(
        self,
        user_id: str,
        query: str,
        limit: int = 3,
    ) -> str:
        ...

    @abstractmethod
    async def save_turn(
        self,
        user_id: str,
        conversation_id: str,
        user_message: str,
        assistant_response: str,
        agent_mode: str,
    ) -> None:
        ...
