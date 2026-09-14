"""The Cognitive Kernel, running on the workspace's own model.

The brain ships wired to Ollama. In this deployment Ollama is a LAN box that
may not be there, and measured through it a one-word greeting took sixty to
ninety seconds and came back in Chinese introducing itself as a different
company's model. Both failures have the same cause: the brain was reasoning
with whatever model happened to be behind ``OllamaLLMAdapter``, not the one
this product actually runs on.

The kernel never needed changing for this. It takes its LLM by injection, so
the whole fix is to hand it the conversation platform's configured provider -
the same endpoint that answers document questions, chosen by
``DOCUMENT_VLM_PROVIDER`` like everything else here. One model, one
credential, one place to change it.

The adapter also owns the persona, because the brain composes its own prompts
and a system prompt written for a generic assistant is how "who are you" gets
answered with somebody else's marketing.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from loguru import logger

IDENTITY = (
    "You are UnityWorks AI, the assistant inside the UnityWorks document "
    "knowledge workspace.\n"
    "What this workspace does: people upload documents - Excel, PDF, Word, "
    "CSV, images, scans - and you read, search, summarise, compare and compute "
    "over them, answer questions with citations back to the source, and "
    "generate new Excel, Word, PDF, CSV and Markdown files from them.\n"
    "Rules about yourself:\n"
    "- Always answer in English unless the user writes to you in another "
    "language first.\n"
    "- Never identify yourself as any other model, company or product, and "
    "never mention the model you run on.\n"
    "- Never invent a specialism. You are a general document assistant; you "
    "are not limited to any one industry or subject, and you must not claim "
    "to be.\n"
    "- Be warm and brief. Two or three sentences unless more is asked for."
)
"""Prepended to whatever the kernel asks for.

Not vanity, and not only about the name. A model asked "who are you" answers
from its training, and this deployment's model is tuned for a physics domain:
asked to introduce itself it offered to help the user read qubit calibration
plots, in a product for reading invoices and spreadsheets. Saying what the
product *is* costs a few lines and removes a whole class of confident,
plausible, completely wrong self-description.
"""


class WorkspaceBrainLLM:
    """``LLMPort`` for the kernel, backed by the conversation provider.

    The kernel runs synchronously in a worker thread, so this bridges to the
    async provider the way the adapter it replaces does: a private event loop
    per call. There is no running loop in that thread to conflict with.
    """

    def __init__(self, provider: Any | None = None) -> None:
        self._provider = provider

    def _get(self) -> Any:
        if self._provider is None:
            from app.document_platform.conversation.llm import get_llm_provider

            self._provider = get_llm_provider()
        return self._provider

    def complete(
        self, prompt: str, *, system: str | None = None,
        model: str | None = None, temperature: float = 0.15,
    ) -> str:
        from app.document_platform.conversation.prompts import StructuredPrompt

        structured = StructuredPrompt(
            system=f"{IDENTITY}\n\n{system}" if system else IDENTITY,
            user=prompt,
            strategy="cognitive",
            max_output_tokens=_MAX_TOKENS,
        )
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self._get().generate(structured))
        finally:
            loop.close()
        return (result.text or "").strip()


_MAX_TOKENS = 700
"""The kernel calls its LLM several times for one turn - perception, reasoning,
then rendering - so this is a per-step budget, and the turn costs a multiple of
it. Generous enough for a real answer, small enough that thinking out loud does
not become the latency."""


_pipeline: Any = None
_lock = threading.Lock()


def workspace_pipeline() -> Any | None:
    """The kernel wired to this workspace's model, built once.

    ``None`` if it cannot be built at all - the caller then answers with the
    model directly, which is a smaller product but a working one.
    """
    global _pipeline
    with _lock:
        if _pipeline is not None:
            return _pipeline
        try:
            from app.cognitive_integration.factory import build_pipeline

            _pipeline = build_pipeline(llm=WorkspaceBrainLLM())
            logger.info("Cognitive Kernel bound to the workspace conversation model")
        except Exception as e:  # noqa: BLE001 - degrade, do not die
            logger.warning(f"Cognitive Kernel could not be built: {e}")
            _pipeline = None
        return _pipeline


def reset_workspace_pipeline() -> None:
    """Drop the cached brain. For tests and configuration reloads."""
    global _pipeline
    with _lock:
        _pipeline = None
