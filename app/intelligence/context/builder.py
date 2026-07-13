"""
User Context Builder.

Assembles all available context into a single IntelligenceContext object.
This is the single input to the DynamicPromptComposer.

Merges:
- Conversation history (session messages)
- Long-term memory context
- Retrieved code chunks
- Tool results
- Intelligence layer outputs (intent, complexity, strategy, persona, policy)
- Current request metadata
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.intelligence.interfaces import AbstractUserContextBuilder
from app.intelligence.models import (
    ComplexityAnalysis,
    ConversationAnalysis,
    IntelligenceContext,
    IntentAnalysis,
    Persona,
    PolicyResult,
    ResponseStrategy,
    ToolPlan,
)

if TYPE_CHECKING:
    from app.agents.state import AgentState


class UserContextBuilder(AbstractUserContextBuilder):
    """
    Assembles all context into a structured IntelligenceContext.
    Does NOT concatenate random strings — produces a typed object.
    """

    async def build(self, state: "AgentState") -> IntelligenceContext:
        raise NotImplementedError(
            "Use build_from_parts() for synchronous assembly or "
            "build_from_state() for full async pipeline."
        )

    def build_from_parts(
        self,
        state: "AgentState",
        intent_analysis: IntentAnalysis,
        complexity: ComplexityAnalysis,
        conversation: ConversationAnalysis,
        policy: PolicyResult,
        persona: Persona,
        strategy: ResponseStrategy,
        tool_plan: Optional[ToolPlan] = None,
    ) -> IntelligenceContext:
        """
        Assemble IntelligenceContext from all module outputs.
        Called by the engine after all analysis modules have run.
        """
        return IntelligenceContext(
            # Request identity
            user_message=state["user_message"],
            conversation_id=state["conversation_id"],
            user_id=state["user_id"],
            org_id=state["org_id"],
            repo_id=state.get("repo_id"),
            agent_mode=state.get("agent_mode", "auto"),
            request_id=state.get("request_id", ""),

            # Intelligence outputs
            intent_analysis=intent_analysis,
            complexity=complexity,
            conversation=conversation,
            policy=policy,
            persona=persona,
            strategy=strategy,

            # Retrieved knowledge (populated from state after retrieval)
            session_messages=state.get("session_messages", []),
            memory_context=state.get("memory_context", ""),
            code_context_block=state.get("context_block", ""),
            retrieved_chunks_count=state.get("context_chunks_used", 0),

            # Tool plan
            tool_plan=tool_plan,

            # Tool results (populated after execution)
            tool_results=list(state.get("tool_results", [])),
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_builder: UserContextBuilder | None = None


def get_context_builder() -> UserContextBuilder:
    global _builder
    if _builder is None:
        _builder = UserContextBuilder()
    return _builder
