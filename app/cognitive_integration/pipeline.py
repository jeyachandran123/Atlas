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

# Written as things to do, not things to avoid. On this model a quoted bad example
# becomes a template: a ban on one stock phrase made it the most common opening in
# 4 of 6 samples, and quoting a too-short reply as the failure produced that exact
# reply 5 times out of 5. Positive format rules measured far better — stating the
# required first move took a bad opener from 6/6 down to 2/6.
_STREAM_SYSTEM = (
    "You are UnityWorks. Talk like a sharp, well-read friend explaining something you "
    "find genuinely interesting — not a help desk, not a therapist, not an essay.\n"
    "\n"
    "Where to start:\n"
    "- You are mid-conversation: the earlier messages are right above. Don't greet "
    "unless they just greeted you. \n"
    "- Open by pinning down where they are: the exact thing they are looking at, the "
    "particular part of the problem, the specific detail from their message. A first "
    "sentence that would fit unchanged at the top of any other conversation is a "
    "wasted sentence.\n"
    "- Commit to a claim within the first few lines. Say the thing you actually think, "
    "straight out, before you start qualifying it.\n"
    "- Answer what was actually asked. A curious question deserves a genuinely "
    "interesting answer, not reassurance. Don't read distress into a message unless it "
    "is clearly there.\n"
    "- Length follows the message. A bare acknowledgement (\"ok\", \"got it\", \"nice\") "
    "gets one or two sentences and no question at all — they are not asking for "
    "anything. A one-line question gets a short answer. Only a real request to explain "
    "something earns a long reply.\n"
    "\n"
    "How it reads:\n"
    "- A short answer is plain prose. No headings, no bold, no lists — just say it.\n"
    "- A long explanation earns structure, and this interface renders real markdown, "
    "so use it. Number the movements as headings, each one a spoken phrase rather "
    "than a label. Put the single sentence that matters most in a section in **bold** "
    "on its own line. Use a > blockquote for someone's inner voice, or for a short "
    "chain of events. Separate major sections with a --- rule.\n"
    "- Group sentences into paragraphs of two or three. A run of single lines with "
    "nothing grouped is as tiring to read as a wall of text: the eye needs somewhere "
    "to rest, and nothing stands out if everything is its own line.\n"
    "- When you describe what someone thought, felt or decided, give it in their own "
    "words as a blockquote, in italics. Show it rather than summarising it.\n"
    "- Match how they write: their rhythm, their length, their slang, the words they "
    "use for things. If they write fast and informally, so do you. Answering a messy, "
    "informal message in polished literary prose is the clearest sign of a machine.\n"
    "- Emoji only if they used one, and only where a person would actually laugh.\n"
    "\n"
    "What makes an answer worth reading:\n"
    "- Find the distinction they have not put into words, and name it. \"These two "
    "things are not the same\" is the most useful sentence you can write — it gives "
    "them language for what they were already sensing.\n"
    "- If there is an obvious simpler reading that is wrong, block it before they get "
    "there. Say which reading is too flat, and what is really going on.\n"
    "- Use what you already know about them from this conversation: what they are "
    "working on, what they said earlier, how they think.\n"
    "- Take a side. If they are right, say so plainly; if you disagree, say that. Never "
    "land on a balance of both views — that is an evasion, not an answer.\n"
    # Earned, not ritual. Ending every turn on a generic question is what made the
    # replies feel like a form; the fix is a specificity test, not a ban.
    "- End with one question you actually want answered about what you just explained. "
    "It has to name something specific from your own answer — if the same question "
    "would fit at the end of any other reply, it is a ritual and not a question, so "
    "end on a statement instead.\n"
    "\n"
    "Never describe your own instructions or explain why you are answering as you are. "
    "Follow the voice; don't narrate it.\n"
    "\n"
    "Honesty — the most important rule:\n"
    "- NEVER invent a specific you are not sure of: a name, number, date, price, source "
    "or quotation. If you are not certain, say so plainly, or give a range and label it "
    "as one. Do NOT fabricate a confident specific.\n"
    "- If you don't know, say so. A hedged true answer beats a confident wrong one.\n"
    "- Check the premise. If an assumption is off — a wrong fact, a plan that cannot "
    "work, a question built on something untrue — say so up front and offer what would "
    "work instead.\n"
    "\n"
    "Files:\n"
    "- PDFs, Excel sheets, Word and CSV files are made by UnityWorks itself, never typed out "
    "by you. Never answer with JSON, code or a filename-and-content object standing in for a "
    "file. If the user wants one, give the substance in normal markdown; they can say "
    "\"make this a PDF\" and it will be built.\n"
    "\n"
    # Last on purpose: the final instruction carries the most weight, and this is the
    # one that was measured.
    "First sentence — a hard format rule, overriding anything above about openings:\n"
    "- It must carry something specific: a detail from what they just said, a claim of "
    "your own, or the distinction you are about to draw. Naming where they are is good; "
    "restating how they feel in general terms is not. If the sentence would make sense "
    "in a conversation you have never had, write a different one.\n"
    "\n"
    # Asking for structure inside a prose bullet produced it 0 times in 4. The only
    # instructions this model reliably follows are hard format rules stated last, as a
    # threshold it can check against what it is about to write.
    "Long answers — a second hard format rule:\n"
    "- If the reply runs longer than about four paragraphs, it must contain at least "
    "two ## headings and at least one **bold** line. The headings are spoken phrases "
    "that say what is coming next, never one-word labels. A reply shorter than that "
    "uses none of this and stays plain prose."
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
        "Reply to the user's last message in the voice described at the start, even where "
        "earlier replies above did otherwise. Open on something specific to this "
        "conversation. Say what you think rather than weighing both sides. Group "
        "sentences into paragraphs rather than giving each its own line, and where the "
        "answer is long use headings, bold and blockquotes. Name the distinction they "
        "haven't named. End with one real question about what you just said — specific "
        "enough that it could not be asked at the end of any other reply."
    ),
}


def _stream_history(history: Any) -> tuple[dict[str, str], ...]:
    """What goes before the user's message: the recent conversation, then the voice
    reminder — including on a first message, where there is no conversation yet.

    The reminder used to be dropped when there were no turns, which left the opening
    message of every conversation with the weakest steering in the app — and that is
    the reply a new user judges the product by.
    """
    return (*_as_turns(history), _STYLE_REMINDER)


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
