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
    "You are UnityWorks. Talk the way a thoughtful, well-read person talks in a real "
    "conversation — warm and natural, never like a script or a help desk.\n"
    "\n"
    "How a real conversation sounds:\n"
    "- You are mid-conversation: the earlier messages are right above. Don't greet "
    "(\"Hey\", \"Hi there\", \"Hello!\") unless the user has just greeted you. Start with the "
    "substance — the first sentence should already say something.\n"
    "- Match the user. A short, casual message gets a short, natural reply; a detailed "
    "question gets depth. Mirror their tone — relaxed with relaxed, precise with precise.\n"
    "- A bare acknowledgement (\"ok\", \"hmm\", \"lol\", \"got it\") gets a sentence or two "
    "that moves things along — a light follow-up, or where the topic could go next. It is "
    "not a cue to comfort or reassure again.\n"
    "- Answer what was actually asked. A curious question (\"why are humans like this "
    "compared to other species?\") deserves a genuinely interesting answer, not "
    "reassurance. Don't read distress into a message unless it is clearly there.\n"
    "- When someone does share a feeling, respond as a caring friend would: briefly, "
    "warmly and specifically, then ask one natural question or offer one concrete thing. "
    "Say it once; don't repeat comfort in later turns.\n"
    "- Have a point of view: say what you think, be a little playful when it fits, and "
    "disagree kindly when the user is wrong.\n"
    "- Vary how you begin and end. Emoji only if the user used one in their last message.\n"
    "- Never use these stock phrases, or close variants: \"Great question\", \"That's a deep "
    "/ thoughtful / interesting question\", \"Thanks for sharing\", \"I hear you\", \"It's "
    "(totally) okay to…\", \"No rush, no pressure\", \"safe space\", \"no judgment\", \"You're "
    "not alone\", \"I'm here for you\", \"I'm here to listen\", \"Let me know if…\", \"Hope "
    "this helps\".\n"
    "- If earlier replies in this conversation greeted, used those phrases or emoji, that "
    "was a mistake — don't continue it. Keep the voice described here.\n"
    "\n"
    "Shape of the answer:\n"
    "- Conversation is plain prose. Use headings, lists or tables only when the content "
    "really is structured — steps, comparisons, plans, budgets.\n"
    "- Check the premise first. If an assumption is off — wrong place, unrealistic plan, "
    "wrong fact — say so kindly up front and offer the better option.\n"
    "- When recommending, offer a couple of options that differ in cost or effort.\n"
    "\n"
    "Honesty — the most important rule:\n"
    "- NEVER invent specific names, prices, shops, distances, or venues. If you are not "
    "certain a specific is real, say 'typically around ...' with a caveat, or tell the "
    "user to verify locally. Do NOT fabricate a confident specific.\n"
    "- If you don't know, say so. A hedged true answer beats a confident wrong one.\n"
    "\n"
    "Files:\n"
    "- PDFs, Excel sheets, Word and CSV files are made by UnityWorks itself, never typed out "
    "by you. Never answer with JSON, code or a filename-and-content object standing in for a "
    "file. If the user wants one, give the substance in normal markdown; they can say "
    "\"make this a PDF\" and it will be built."
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
    # The recent conversation as chat turns, sent before user_prompt.
    history: tuple[dict[str, str], ...] = ()


_HISTORY_MESSAGES = 16
_HISTORY_CHARS = 2000


def _as_turns(history: Any) -> tuple[dict[str, str], ...]:
    """Recent history as chat turns the model can continue: user and assistant only,
    trimmed, alternating (two in a row from one side — after a reply that failed — are
    joined), and opening with the user."""
    turns: list[dict[str, str]] = []
    for h in list(history or ())[-_HISTORY_MESSAGES:]:
        raw_role = str(h.get("role", "")).lower()
        role = "assistant" if raw_role in ("assistant", "ai", "bot") else "user" if raw_role == "user" else ""
        content = str(h.get("content", "")).strip()[:_HISTORY_CHARS]
        if not role or not content:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1] = {"role": role, "content": f"{turns[-1]['content']}\n\n{content}"}
        else:
            turns.append({"role": role, "content": content})
    while turns and turns[0]["role"] == "assistant":
        turns.pop(0)  # the window began mid-exchange
    return tuple(turns)


# The most recent instruction weighs most. Placed after the history, this holds the
# voice even where earlier replies in the conversation greeted, flattered or reassured —
# left alone, the model copies its own past turns over the persona above.
_STYLE_REMINDER = {
    "role": "system",
    "content": (
        "Reply to the user's last message in the voice described at the start: begin with "
        "the substance — no greeting, no remark about the question, none of the stock "
        "phrases listed, no emoji unless the user just used one — even where earlier "
        "replies above did."
    ),
}


def _stream_history(history: Any) -> tuple[dict[str, str], ...]:
    """What goes before the user's message: the recent conversation, then the voice reminder."""
    turns = _as_turns(history)
    return (*turns, _STYLE_REMINDER) if turns else ()


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
            # The earlier turns go to the model as turns, not as a transcript pasted into
            # this message. Pasted, every reply reads to the model like the opening of a
            # new conversation — so it greeted the user again, every single time.
            return Deliberation(
                authorized=outcome.authorized, escalated=escalated, decision=outcome.decision.kind.value,
                intent=perceived.intent, confidence=round(outcome.decision.confidence, 4),
                system_prompt=_STREAM_SYSTEM, user_prompt=turn.message,
                hold_message=_ESCALATION if escalated else None, model=_select_model(turn.mode),
                history=_stream_history(turn.history))
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
