"""
Prompt Enhancer — V2.

The old enhancer injected massive static templates into every request.
That is replaced by the PromptIntelligenceEngine in app/intelligence/prompting/.

This file now has one job: build the user-turn prompt cleanly.

  - Safety guard (18+ content)
  - Non-code topic guard for code mode
  - Business mode off-topic guard
  - Clean pass-through for everything else

The PromptIntelligenceEngine handles all objective expansion and depth planning.
The user message is passed through as-is here; the system prompt carries the intelligence.
"""

from __future__ import annotations

# ── 18+ content guard ─────────────────────────────────────────────────────────
_ADULT_PATTERNS = (
    "porn", "pornography", "nude", "naked", "sex ", "sexual", "nsfw",
    "explicit", "erotic", "xxx", "adult content", "18+", "hentai",
    "masturbat", "orgasm", "genitals", "penis", "vagina", "breast",
    "strip club", "escort", "prostitut", "onlyfans",
)

_ADULT_META_PATTERNS = (
    "18+ content", "adult content", "explicit content", "mature content",
    "if i ask about 18", "if ask about 18", "what if i ask 18",
    "can you do 18", "will you do 18", "cersei", "incest", "intimacy scene",
)


def _is_adult_content(message: str) -> bool:
    lower = message.lower()
    return any(p in lower for p in _ADULT_PATTERNS) or any(p in lower for p in _ADULT_META_PATTERNS)


# ── Non-code topic guard ───────────────────────────────────────────────────────
_NON_CODE_TOPICS = (
    "game of thrones", "breaking bad", "movie", "film", "book", "novel",
    "song", "music", "sport", "football", "cricket", "recipe", "cook",
    "travel", "history", "science", "physics", "math", "weather",
    "politics", "news", "celebrity", "actor", "actress", "season",
    "episode", "character", "plot", "story", "author", "director",
    "released", "published", "targaryen", "stark", "lannister", "westeros",
)


def _is_non_code_topic(message: str) -> bool:
    lower = message.lower()
    return any(t in lower for t in _NON_CODE_TOPICS)


# ── Business mode off-topic guard ─────────────────────────────────────────────
_BUSINESS_OFF_TOPIC = (
    "game of thrones", "breaking bad", "movie", "film", "song", "music",
    "sport", "football", "cricket", "recipe", "cook", "travel", "history",
    "science", "physics", "math", "javascript tutorial", "python tutorial",
    "how to code", "learn programming",
)


def _is_off_topic_for_business(message: str) -> bool:
    lower = message.lower()
    return any(t in lower for t in _BUSINESS_OFF_TOPIC)


# ── Public API ────────────────────────────────────────────────────────────────

def enhance_user_message(message: str, intent: str, agent_mode: str = "auto") -> str:
    """
    Prepare the user-turn message for the LLM.

    The system prompt (built by DynamicPromptComposer + PromptIntelligenceEngine)
    carries all the intelligence. This function only applies safety guards
    and returns the message cleanly.
    """
    stripped = message.strip()

    # 18+ guard (all modes)
    if _is_adult_content(stripped):
        return (
            "I'm not able to help with that type of content. "
            "Please ask me something else — I'm happy to help with "
            "coding, business questions, or general topics."
        )

    # Code mode: refuse non-code topics
    if agent_mode == "code" and _is_non_code_topic(stripped):
        return (
            "I'm in **Code mode**, which is focused on programming and software engineering.\n\n"
            "Your question appears to be about a non-coding topic. Please switch to:\n"
            "- **Auto mode** — for general questions, pop culture, history, science, etc.\n"
            "- **Business mode** — for business operations and ERP/POS/hotel systems\n\n"
            "Is there a coding question I can help you with?"
        )

    # Business mode: redirect off-topic queries
    if agent_mode == "business" and _is_off_topic_for_business(stripped):
        return (
            "I'm in Business mode, which focuses on hotel management, ERP, POS, "
            "stock management, and business operations.\n\n"
            "Your question appears to be off-topic for this mode. Please switch to:\n"
            "- **Auto mode** — for general questions, history, science, pop culture, etc.\n"
            "- **Code mode** — for programming and technical implementation\n\n"
            "Is there a business operations question I can help you with instead?"
        )

    # All other messages: pass through cleanly.
    # The PromptIntelligenceEngine in the system prompt handles all expansion and depth.
    return stripped
