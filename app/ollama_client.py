"""
Async Ollama client.

Wraps the Ollama REST API with retry logic, timeout handling,
and a clean interface for both chat and embedding operations.
"""

from __future__ import annotations

import time
from typing import AsyncGenerator, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.shared.exceptions import OllamaUnavailableError

settings = get_settings()


class OllamaClient:
    """
    Async HTTP client for the Ollama API.

    Use as a singleton via get_ollama_client().
    All methods raise OllamaUnavailableError on connection failure.
    """

    def __init__(self, base_url: str, timeout: int = 120) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout),
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1,
    ) -> str:
        """
        Single-turn chat completion.
        Returns the assistant's response as a string.
        """
        model = model or settings.ollama_chat_model
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await self._client.post(
                "/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature},
                },
            )
            response.raise_for_status()
            data = response.json()
            return str(data["message"]["content"])
        except httpx.ConnectError as e:
            raise OllamaUnavailableError() from e
        except httpx.TimeoutException as e:
            raise OllamaUnavailableError("Ollama request timed out") from e

    async def chat_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming chat completion.
        Yields text chunks as they arrive from Ollama.
        """
        model = model or settings.ollama_chat_model
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            async with self._client.stream(
                "POST",
                "/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": True,
                    "options": {"temperature": temperature},
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        import json
                        chunk = json.loads(line)
                        if content := chunk.get("message", {}).get("content"):
                            yield content
                        if chunk.get("done"):
                            break
        except httpx.ConnectError as e:
            raise OllamaUnavailableError() from e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    async def embed(
        self,
        texts: list[str],
        model: Optional[str] = None,
    ) -> list[list[float]]:
        """
        Generate embeddings for a list of texts.
        Returns a list of float vectors (one per input text).
        """
        model = model or settings.ollama_embed_model
        embeddings = []

        for text in texts:
            try:
                response = await self._client.post(
                    "/api/embeddings",
                    json={"model": model, "prompt": text},
                )
                response.raise_for_status()
                data = response.json()
                embeddings.append(data["embedding"])
            except httpx.ConnectError as e:
                raise OllamaUnavailableError() from e

        return embeddings

    async def health_check(self) -> tuple[bool, int]:
        """
        Check if Ollama is available.
        Returns (available, latency_ms).
        """
        start = time.monotonic()
        try:
            response = await self._client.get("/api/tags", timeout=5.0)
            latency_ms = int((time.monotonic() - start) * 1000)
            return response.status_code == 200, latency_ms
        except Exception:
            return False, 0

    async def list_models(self) -> list[str]:
        """Return names of locally available Ollama models."""
        try:
            response = await self._client.get("/api/tags", timeout=5.0)
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    async def close(self) -> None:
        await self._client.aclose()


# ── Module-level singleton ────────────────────────────────────────────────────
_ollama_client: OllamaClient | None = None


def get_ollama_client() -> OllamaClient:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient(
            base_url=settings.ollama_host,
            timeout=settings.ollama_timeout,
        )
    return _ollama_client


async def close_ollama_client() -> None:
    global _ollama_client
    if _ollama_client:
        await _ollama_client.close()
        _ollama_client = None
