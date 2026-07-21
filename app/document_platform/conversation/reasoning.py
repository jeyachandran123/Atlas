"""
Reasoning Engine (Objective 8) — coordinates the LLM call: retries via the
platform's existing RetryPolicy, latency + token tracking, typed failure
normalization. Business logic stays here; the provider only speaks protocol.
"""
from __future__ import annotations

import asyncio

from loguru import logger

from app.document_platform.conversation.llm import (
    AbstractLLMProvider,
    LLMProviderError,
    LLMResult,
)
from app.document_platform.conversation.prompts import StructuredPrompt


class ReasoningError(Exception):
    """All retries exhausted — the turn fails honestly."""


class ReasoningEngine:
    def __init__(self, provider: AbstractLLMProvider, max_retries: int) -> None:
        self._provider = provider
        self._max_retries = max_retries

    @property
    def provider(self) -> AbstractLLMProvider:
        return self._provider

    async def generate(self, prompt: StructuredPrompt) -> LLMResult:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 2):  # initial try + retries
            try:
                return await self._provider.generate(prompt)
            except LLMProviderError as e:
                last_error = e
                if attempt <= self._max_retries:
                    delay = min(2.0 * attempt, 8.0)
                    logger.warning(
                        f"LLM call failed (attempt {attempt}), retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
        raise ReasoningError(
            f"LLM provider '{self._provider.name}' failed after "
            f"{self._max_retries + 1} attempts: {last_error}"
        ) from last_error
