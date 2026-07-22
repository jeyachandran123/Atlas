"""Automatic conversation titles — one short call through the existing LLM
provider abstraction. Falls back to a trimmed question if the model
misbehaves; never blocks the answer itself."""
from __future__ import annotations

import re

from loguru import logger

from app.document_platform.conversation.llm import get_llm_provider
from app.document_platform.conversation.prompts import StructuredPrompt

_QUOTE = re.compile(r"^[\"'`\s]+|[\"'`\s.]+$")


def fallback_title(question: str) -> str:
    words = question.strip().split()
    return " ".join(words[:8])[:60] or "New conversation"


async def generate_title(question: str, answer: str) -> str:
    try:
        provider = get_llm_provider()
        prompt = StructuredPrompt(
            system=(
                "You name conversations. Reply with ONLY a concise 2-5 word "
                "title in Title Case. No quotes, no punctuation, no explanation."
            ),
            user=f"Question: {question[:400]}\n\nAnswer summary: {answer[:400]}",
            strategy="title",
        )
        result = await provider.generate(prompt)
        title = _QUOTE.sub("", result.text.split("\n")[0])[:60]
        return title or fallback_title(question)
    except Exception as e:
        logger.warning(f"Title generation failed (using fallback): {e}")
        return fallback_title(question)
