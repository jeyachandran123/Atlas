"""
LLM Provider abstraction (Objective 9). The ONLY module in the platform
allowed to speak Ollama's chat protocol for conversational answering.
OpenAI/Azure/Anthropic/Google later = one new subclass each.

Deliberately calls Ollama's /api/chat directly rather than wrapping the
legacy OllamaClient.chat(): that client discards prompt_eval_count /
eval_count, and Objective 15 requires real token counts, not estimates.
Protocol handling (think-block stripping, usage extraction) is provider
code by definition — no business logic lives here.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator

import httpx

from app.document_platform.conversation.prompts import StructuredPrompt

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class LLMProviderError(Exception):
    """The LLM provider call failed (transient — retryable)."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    provider: str
    model: str


@dataclass
class StreamStats:
    """Filled by stream() as the final chunk arrives — lets the caller get
    real usage numbers without the stream yielding mixed types."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    full_text: str = ""
    chunks: list[str] = field(default_factory=list)


class AbstractLLMProvider(ABC):
    name: str = "abstract"
    model_name: str = ""

    @abstractmethod
    async def generate(self, prompt: StructuredPrompt) -> LLMResult: ...

    @abstractmethod
    def stream(self, prompt: StructuredPrompt, stats: StreamStats) -> AsyncIterator[str]: ...


class OllamaLLMProvider(AbstractLLMProvider):
    name = "ollama"

    def __init__(self) -> None:
        from app.config import get_settings
        cfg = get_settings()
        self._host = cfg.ollama_host
        self.model_name = cfg.dip_chat_model
        self._temperature = cfg.dip_chat_temperature
        self._timeout = cfg.ollama_timeout
        self._num_ctx = cfg.ollama_num_ctx
        self._num_predict = cfg.ollama_num_predict

    def _payload(self, prompt: StructuredPrompt, stream: bool) -> dict:
        return {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "stream": stream,
            "options": {
                "temperature": self._temperature,
                "num_ctx": self._num_ctx,
                "num_predict": self._num_predict,
            },
        }

    async def generate(self, prompt: StructuredPrompt) -> LLMResult:
        import time
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                base_url=self._host, timeout=self._timeout,
            ) as client:
                resp = await client.post("/api/chat", json=self._payload(prompt, stream=False))
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise LLMProviderError(f"Ollama chat failed: {e}") from e
        text = _THINK_RE.sub("", str(data.get("message", {}).get("content", ""))).strip()
        return LLMResult(
            text=text,
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
            latency_ms=int((time.monotonic() - start) * 1000),
            provider=self.name,
            model=self.model_name,
        )

    async def stream(self, prompt: StructuredPrompt, stats: StreamStats) -> AsyncIterator[str]:
        import json as _json
        import time
        start = time.monotonic()
        in_think = False
        try:
            async with httpx.AsyncClient(
                base_url=self._host,
                timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0),
            ) as client:
                async with client.stream(
                    "POST", "/api/chat", json=self._payload(prompt, stream=True),
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = _json.loads(line)
                        except _json.JSONDecodeError:
                            continue
                        if chunk.get("done"):
                            stats.prompt_tokens = int(chunk.get("prompt_eval_count", 0))
                            stats.completion_tokens = int(chunk.get("eval_count", 0))
                            break
                        content = chunk.get("message", {}).get("content", "")
                        if not content:
                            continue
                        # Strip <think>…</think> spans (qwen3, deepseek-r1)
                        if "<think>" in content:
                            in_think = True
                        if in_think:
                            if "</think>" in content:
                                in_think = False
                                content = content.split("</think>", 1)[1]
                                if not content:
                                    continue
                            else:
                                continue
                        stats.chunks.append(content)
                        yield content
        except httpx.HTTPError as e:
            raise LLMProviderError(f"Ollama stream failed: {e}") from e
        finally:
            stats.latency_ms = int((time.monotonic() - start) * 1000)
            stats.full_text = "".join(stats.chunks).strip()


def get_llm_provider(provider_name: str | None = None) -> AbstractLLMProvider:
    from app.config import get_settings
    name = provider_name or get_settings().dip_llm_provider
    if name == "ollama":
        return OllamaLLMProvider()
    raise ValueError(f"Unknown LLM provider: {name}")
