"""Production wrappers — adapt the *existing* Body components to the integration ports.

These reuse the real infrastructure: the Ollama client (Qwen/DeepSeek/Llama), the
Intent Detector, and the Conversation history for context. They are lazy and
defensive — importing the real components only when used — so the integration package
imports cleanly in any environment and tests can inject fakes instead. Nothing here
duplicates platform logic; each wrapper is a thin translation to a port.
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

from .ports import IntentResult, Turn


def _run_sync(coro: Any) -> Any:
    """Run an async coroutine from synchronous code (the pipeline runs in a worker thread)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class OllamaLLMAdapter:
    """LLMPort backed by the existing ``OllamaClient.chat`` (sync bridge over async)."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def _get(self) -> Any:
        if self._client is None:
            from app.ollama_client import get_ollama_client

            self._client = get_ollama_client()
        return self._client

    def complete(self, prompt: str, *, system: str | None = None, model: str | None = None,
                 temperature: float = 0.15) -> str:
        return _run_sync(self._get().chat(prompt, system_prompt=system, model=model, temperature=temperature))


class IntentDetectorAdapter:
    """IntentPort reusing the existing Intent Detector, enriched with a safety-risk scan."""

    _DANGER = ("delete", "drop table", "rm -rf", "wipe", "destroy", "erase", "format ", "shutdown",
               "revoke", "deploy to prod", "force push", "factory reset", "remove all")

    def __init__(self, detector: Any | None = None) -> None:
        self._detector = detector

    def detect(self, message: str, history: list[Mapping[str, Any]]) -> IntentResult:
        intent = "general"
        try:
            if self._detector is None:
                from app.intelligence.intent.detector import get_intent_detector

                self._detector = get_intent_detector()
            analysis = self._detector.detect(message, history)
            intent = str(getattr(analysis, "intent", None) or getattr(analysis, "mode", None) or "general")
        except Exception:
            pass
        low = message.lower()
        hits = tuple(d for d in self._DANGER if d in low)
        dangerous = bool(hits)
        return IntentResult(
            intent=intent, is_question=message.strip().endswith("?"),
            stakes=0.95 if dangerous else 0.1, safety_relevant=dangerous, irreversible=dangerous, keywords=hits)


class ConversationContextAdapter:
    """ContextPort assembling recent conversation context from the turn history.

    Keeps enough of the recent transcript that multi-turn references stay anchored
    (e.g. "describe Reiner" three turns after "Attack on Titan"). Uses clear role
    labels so the model treats it as prior dialogue. (The full DB-backed Context
    Builder / retrieval plugs in here unchanged when richer grounding is wanted.)"""

    MAX_TURNS = 12
    MAX_CHARS_PER_MESSAGE = 800

    def build(self, message: str, turn: Turn) -> str:
        parts = []
        for h in list(turn.history)[-self.MAX_TURNS:]:
            role = str(h.get("role", "user")).lower()
            label = "Assistant" if role in ("assistant", "ai", "bot") else "User"
            content = str(h.get("content", "")).strip()[: self.MAX_CHARS_PER_MESSAGE]
            if content:
                parts.append(f"{label}: {content}")
        return "\n".join(parts)


class GenerationLLMAdapter:
    """GenerationPort reusing the existing Ollama generation infrastructure to render the reply."""

    _SYSTEM = ("You are UnityWorks. Rewrite the analysis into a clear, friendly, well-formatted reply "
               "to the user. Convey the analysis faithfully; do not invent new facts.")

    def __init__(self, llm: Any, model: str | None = None) -> None:
        self._llm = llm
        self._model = model

    def render(self, conclusion: str, context_text: str, turn: Turn) -> str:
        prompt = (f"User message: {turn.message}\n\n"
                  f"Analysis to convey:\n{conclusion}\n\nWrite the final reply to the user.")
        return self._llm.complete(prompt, system=self._SYSTEM, model=self._model, temperature=0.4)
