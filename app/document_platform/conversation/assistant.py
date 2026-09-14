"""Answering the user rather than the documents.

The grounding contract is right about document questions and wrong about
everything else. "Hey hi" is not a failed search, "who are you" is not a
missing citation, and replying to either with *I don't have enough information
in the knowledge base* is the assistant failing to notice it was being spoken
to. A knowledge workspace is still a conversation, and a product that cannot
say hello does not feel like an assistant - it feels like a form.

So this module handles the turns that are addressed to the assistant. Two
things answer them, in order:

1. **The Cognitive Kernel** - the application's brain, already built, already
   tested, and until now not reachable from this workspace at all. It runs
   perception, reasoning and generation and returns a conclusion, and it is
   what makes this an agent rather than a search box with a chat skin.
2. **The configured conversation model**, directly, if the brain declines or
   cannot be reached. The brain returns ``None`` rather than raising when its
   LLM is unavailable, and a greeting must never fail on infrastructure.

What this does NOT do is answer questions about documents. Those keep every
guarantee they had: retrieval, citations, validation, refusal. The routing
decision is made before anything here runs, by the intent classifier, and it
errs towards the grounded path in every ambiguous case.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from app.document_platform.conversation.prompts import StructuredPrompt

ASSISTANT_SYSTEM = (
    "You are the UnityWorks assistant inside a document knowledge workspace. "
    "You are talking to the person who uses it.\n"
    "- Be warm, brief and direct. Two or three sentences unless more is asked "
    "for.\n"
    "- You can answer general questions from your own knowledge. When you do, "
    "you are not reading their documents, and you never imply that you are.\n"
    "- You can read, search, summarise, compare and compute over the documents "
    "in this workspace, and generate Excel, Word, PDF, CSV and Markdown files "
    "from them. Say so when someone asks what you can do.\n"
    "- Never invent anything about a document you have not been shown. If a "
    "question needs a document you cannot see, say which document you need.\n"
    "- Plain markdown. No citation markers - there are no sources here."
)

ASSISTANT_MAX_TOKENS = 512
"""Small talk that runs to a page is not small talk. This also keeps the reply
fast enough to feel like a reply rather than a job."""


@dataclass(frozen=True)
class AssistantReply:
    text: str
    source: str            # "cognitive_kernel" | "model"
    model: str = ""
    latency_ms: int = 0


async def answer_directly(
    question: str,
    *,
    reasoning,
    conversation_id: str = "",
    user_id: str = "",
    org_id: str = "",
    history: list | None = None,
    use_brain: bool = True,
) -> AssistantReply | None:
    """Reply as the assistant. ``None`` only if nothing could answer at all."""
    if use_brain:
        reply = await _ask_the_brain(
            question, conversation_id=conversation_id, user_id=user_id,
            org_id=org_id, history=history,
        )
        if reply is not None:
            return reply

    prompt = StructuredPrompt(
        system=ASSISTANT_SYSTEM,
        user=_with_history(question, history),
        strategy="assistant",
        max_output_tokens=ASSISTANT_MAX_TOKENS,
    )
    try:
        result = await reasoning.generate(prompt)
    except Exception as e:  # noqa: BLE001 - a greeting must not raise
        logger.warning(f"The assistant could not answer directly: {e}")
        return None
    text = (result.text or "").strip()
    if not text:
        return None
    return AssistantReply(
        text=text, source="model",
        model=getattr(result, "model", ""),
        latency_ms=getattr(result, "latency_ms", 0),
    )


async def _ask_the_brain(
    question: str, *, conversation_id: str, user_id: str, org_id: str,
    history: list | None,
) -> AssistantReply | None:
    """One turn through the Cognitive Kernel, or ``None`` to fall back.

    Imported inside the function on purpose. The brain is a large subsystem
    with its own dependencies, and a document workspace that cannot answer a
    question because importing the kernel failed would be a worse product than
    one that never had a kernel.
    """
    try:
        from app.cognitive_integration.flag import cognitive_brain_enabled
        from app.cognitive_integration.service import cognitive_turn
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Cognitive Kernel unavailable: {e}")
        return None

    try:
        if not cognitive_brain_enabled():
            return None
    except Exception:  # noqa: BLE001 - a flag that cannot be read is not on
        return None

    from app.document_platform.conversation.brain import workspace_pipeline

    pipeline = workspace_pipeline()
    if pipeline is None:
        return None

    try:
        result = await cognitive_turn(
            question, conversation_id=conversation_id or "workspace",
            user_id=user_id or "user", org_id=org_id or "org",
            history=history or (),
            pipeline=pipeline,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Cognitive Kernel turn failed: {e}")
        return None

    if result is None:
        return None
    text = (getattr(result, "conclusion", None) or "").strip()
    if not text:
        return None
    logger.info("Answered from the Cognitive Kernel")
    return AssistantReply(text=text, source="cognitive_kernel", model="cognitive_kernel")


_GIST_CHARS = 240
"""How much of a previous reply to carry. Small, and for one reason: asked
"thanks!" with a full previous reply in view, the model answered by sending
that reply again. History is here to resolve references, not to be reused."""


def _with_history(question: str, history: list | None) -> str:
    """The last few exchanges, so "what about the other one" means something."""
    if not history:
        return question
    lines = []
    for turn in history[-4:]:
        asked = getattr(turn, "question", None)
        answered = (getattr(turn, "answer", None) or "").strip()
        if len(answered) > _GIST_CHARS:
            answered = answered[:_GIST_CHARS].rsplit(" ", 1)[0] + " …"
        if asked:
            lines.append(f"User: {asked}")
        if answered:
            lines.append(f"Assistant: {answered}")
    if not lines:
        return question
    return (
        "# Earlier in this conversation (context only - do NOT repeat these)\n"
        + "\n".join(lines)
        + f"\n\n# Their message now\n{question}\n\n"
        "Reply to their message. Do not restate who you are or what you can do "
        "unless they just asked."
    )
