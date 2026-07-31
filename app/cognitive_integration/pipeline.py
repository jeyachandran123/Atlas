"""CognitivePipeline — the one complete vertical slice, brain at the centre.

    User -> Conversation -> Perception -> Working Memory -> Attention ->
    Reasoning -> Reasoning Port -> Ollama -> Executive -> Generation ->
    Conversation -> User

Synchronous (the engines are synchronous). The route runs it in a worker thread and
bridges to async infra at the edges. The pipeline *coordinates adapters*; it performs
no cognition itself and imports no platform. Dangerous or high-stakes turns are
escalated by the Executive and never auto-answered — the constitutional safety gate.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.cognitive_kernel.engines.attention import Candidate, SalienceVector
from app.cognitive_kernel.engines.reasoning import ReasoningRequest
from app.cognitive_kernel.engines.executive import ReasoningProposal

from .generation import GenerationAdapter
from .perception import PerceptionAdapter
from .platform_actions import PlatformActionAdapter
from .ports import Turn, TurnResult

_ESCALATION = (
    "That request looks high-stakes or potentially irreversible, so I'm holding it for "
    "review rather than acting on it automatically. Could you confirm exactly what you'd "
    "like me to do?"
)

_STREAM_SYSTEM = (
    "You are UnityWorks, a helpful and accurate assistant. Answer the user directly, "
    "concisely, and factually. If you are unsure, say so plainly."
)


@dataclass(frozen=True, slots=True)
class Deliberation:
    """The fast, no-LLM governance result for a streamed turn: perception + attention +
    the Executive safety gate decide *whether* to answer; the answer itself is then
    streamed token-by-token by the caller (true streaming, not chunk-after-complete)."""

    authorized: bool
    escalated: bool
    decision: str
    intent: str
    confidence: float
    system_prompt: str
    user_prompt: str
    hold_message: str | None
    model: str | None = None   # LLM to stream the answer with (selected by mode/intent)


def _select_model(mode: str) -> str | None:
    """Pick the LLM for this turn — general chat uses the conversational model
    (qwen3:8b), code uses the coder model. Falls back to Ollama defaults."""
    try:
        from app.config import get_settings

        s = get_settings()
        if mode == "code":
            return s.ollama_chat_model                                   # qwen2.5-coder:7b
        return getattr(s, "dip_chat_model", None) or s.ollama_auto_model  # qwen3:8b for general chat
    except Exception:
        return None  # let chat_stream use its own default


class CognitivePipeline:
    def __init__(self, session: Any, perception: PerceptionAdapter, generation: GenerationAdapter,
                 platform_actions: PlatformActionAdapter | None = None) -> None:
        self._session = session
        self._perception = perception
        self._generation = generation
        self._platforms = platform_actions or PlatformActionAdapter()

    def deliberate(self, turn: Turn) -> Deliberation | None:
        """Governance-only pass for streaming: Perception -> Attention -> Executive safety
        gate, with NO answer generation (fast, no LLM). The route streams the answer after.
        Returns None on a brain error so the caller falls back to the classic pipeline."""
        s = self._session
        try:
            ctx = s.new_context(turn)
            perceived = self._perception.perceive(s, turn, ctx)
            candidates = [Candidate(h, SalienceVector(goal_relevance=0.9, user_importance=0.8))
                          for h in perceived.evidence_handles]
            s.attention.attend(candidates, ctx)
            proposal = ReasoningProposal(
                proposal_id="turn-" + uuid.uuid4().hex,
                statement=f"respond to user: {turn.message[:200]}", confidence=0.9,
                kind="action" if (perceived.safety_relevant or perceived.reversibility < 0.5) else "belief",
                stakes=perceived.stakes, reversibility=perceived.reversibility,
                safety_relevant=perceived.safety_relevant, source="conversation")
            outcome = s.executive.govern(proposal, ctx)
            escalated = outcome.decision.outcome.value == "escalated"
            prefix = f"Conversation context:\n{perceived.context_text}\n\n" if perceived.context_text else ""
            return Deliberation(
                authorized=outcome.authorized, escalated=escalated, decision=outcome.decision.kind.value,
                intent=perceived.intent, confidence=round(outcome.decision.confidence, 4),
                system_prompt=_STREAM_SYSTEM, user_prompt=f"{prefix}User: {turn.message}",
                hold_message=_ESCALATION if escalated else None, model=_select_model(turn.mode))
        except Exception:
            return None

    def handle(self, turn: Turn) -> TurnResult:
        s = self._session
        ctx = s.new_context(turn)

        # 1. Perception — Conversation input becomes cognitive objects, loaded into WM.
        perceived = self._perception.perceive(s, turn, ctx)

        # 2. Attention — select what becomes conscious.
        candidates = [Candidate(h, SalienceVector(goal_relevance=0.9, user_importance=0.8))
                      for h in perceived.evidence_handles]
        att = s.attention.attend(candidates, ctx)

        # 3. Reasoning — transforms conscious content into a conclusion, via the Ollama port.
        result = s.reasoning.reason(
            ReasoningRequest(goal=perceived.goal, question=perceived.question,
                             stakes=perceived.stakes, reversibility=perceived.reversibility), ctx)
        conclusion = result.conclusion.statement if result.conclusion else None
        confidence = result.conclusion.confidence if result.conclusion else 0.0

        # 4. Executive — governs the proposal (authorize / escalate), safety-scaled.
        proposal = ReasoningProposal(
            proposal_id="turn-" + uuid.uuid4().hex,
            statement=conclusion or "(no conclusion reached)", confidence=confidence,
            kind="action" if (perceived.safety_relevant or perceived.reversibility < 0.5) else "belief",
            goal_id=perceived.goal_handle if s.state.exists(perceived.goal_handle) else None,
            stakes=perceived.stakes, reversibility=perceived.reversibility,
            safety_relevant=perceived.safety_relevant, source="reasoning")
        outcome = s.executive.govern(proposal, ctx)
        authorized = outcome.authorized
        escalated = outcome.decision.outcome.value == "escalated"

        # 5. Generation — render the final reply (or a safe hold on escalation).
        if escalated:
            reply = _ESCALATION
        elif authorized and conclusion:
            reply = self._generation.render(conclusion, perceived.context_text, turn)
        else:
            reply = self._generation.render(conclusion, perceived.context_text, turn)

        return TurnResult(
            reply=reply, authorized=authorized, decision=outcome.decision.kind.value, escalated=escalated,
            conclusion=conclusion, confidence=round(confidence, 4), intent=perceived.intent,
            stages={
                "attention_ignited": att.ignited, "coalition": len(att.coalition),
                "reasoning_concluded": result.concluded, "executive_outcome": outcome.decision.outcome.value,
            },
        )
