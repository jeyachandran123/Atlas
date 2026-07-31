# """
# Async Ollama client.

# Wraps the Ollama REST API with retry logic, timeout handling,
# and a clean interface for both chat and embedding operations.
# """

# from __future__ import annotations

# import time
# from typing import AsyncGenerator, Optional

# import httpx
# from tenacity import retry, stop_after_attempt, wait_exponential

# from app.config import get_settings
# from app.shared.exceptions import OllamaUnavailableError

# settings = get_settings()


# class OllamaClient:
#     """
#     Async HTTP client for the Ollama API.

#     Use as a singleton via get_ollama_client().
#     All methods raise OllamaUnavailableError on connection failure.
#     """

#     def __init__(self, base_url: str, timeout: int = 120) -> None:
#         self._base_url = base_url.rstrip("/")
#         self._timeout = timeout
#         self._client = httpx.AsyncClient(
#             base_url=self._base_url,
#             timeout=httpx.Timeout(timeout),
#         )

#     @retry(
#         stop=stop_after_attempt(3),
#         wait=wait_exponential(multiplier=1, min=1, max=8),
#         reraise=True,
#     )
#     async def chat(
#         self,
#         prompt: str,
#         system_prompt: Optional[str] = None,
#         model: Optional[str] = None,
#         temperature: float = 0.15,
#     ) -> str:
#         """
#         Single-turn chat completion.
#         Returns the assistant's response as a string.
#         """
#         model = model or settings.ollama_chat_model
#         messages = []
#         if system_prompt:
#             messages.append({"role": "system", "content": system_prompt})
#         messages.append({"role": "user", "content": prompt})

#         try:
#             response = await self._client.post(
#                 "/api/chat",
#                 json={
#                     "model": model,
#                     "messages": messages,
#                     "stream": False,
#                     "options": {
#                         "temperature": temperature,
#                         "num_ctx": settings.ollama_num_ctx,
#                         "num_predict": settings.ollama_num_predict,
#                         "repeat_penalty": 1.1,
#                     },
#                 },
#             )
#             response.raise_for_status()
#             data = response.json()
#             return str(data["message"]["content"])
#         except httpx.ConnectError as e:
#             raise OllamaUnavailableError() from e
#         except httpx.TimeoutException as e:
#             raise OllamaUnavailableError("Ollama request timed out") from e

#     async def chat_stream(
#         self,
#         prompt: str,
#         system_prompt: Optional[str] = None,
#         model: Optional[str] = None,
#         temperature: float = 0.1,
#     ) -> AsyncGenerator[str, None]:
#         """
#         Streaming chat completion.
#         Yields text chunks as they arrive from Ollama.
#         """
#         import json as _json

#         model = model or settings.ollama_chat_model
#         messages = []
#         if system_prompt:
#             messages.append({"role": "system", "content": system_prompt})
#         messages.append({"role": "user", "content": prompt})

#         try:
#             # Use a separate client with no read timeout for streaming
#             async with httpx.AsyncClient(
#                 base_url=self._base_url,
#                 timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0),
#             ) as stream_client:
#                 async with stream_client.stream(
#                     "POST",
#                     "/api/chat",
#                     json={
#                         "model": model,
#                         "messages": messages,
#                         "stream": True,
#                         "options": {
#                             "temperature": temperature,
#                             "num_ctx": settings.ollama_num_ctx,
#                             "num_predict": settings.ollama_num_predict,
#                             "repeat_penalty": 1.1,
#                         },
#                     },
#                 ) as response:
#                     response.raise_for_status()
#                     async for line in response.aiter_lines():
#                         if not line:
#                             continue
#                         try:
#                             chunk = _json.loads(line)
#                         except _json.JSONDecodeError:
#                             continue
#                         if content := chunk.get("message", {}).get("content"):
#                             yield content
#                         if chunk.get("done"):
#                             break
#         except httpx.ConnectError as e:
#             raise OllamaUnavailableError() from e
#         except httpx.TimeoutException as e:
#             raise OllamaUnavailableError("Ollama stream timed out") from e

#     @retry(
#         stop=stop_after_attempt(3),
#         wait=wait_exponential(multiplier=1, min=1, max=4),
#         reraise=True,
#     )
#     async def embed(
#         self,
#         texts: list[str],
#         model: Optional[str] = None,
#     ) -> list[list[float]]:
#         """
#         Generate embeddings for a list of texts.
#         Returns a list of float vectors (one per input text).
#         """
#         model = model or settings.ollama_embed_model
#         embeddings = []

#         for text in texts:
#             try:
#                 response = await self._client.post(
#                     "/api/embeddings",
#                     json={"model": model, "prompt": text},
#                 )
#                 response.raise_for_status()
#                 data = response.json()
#                 embeddings.append(data["embedding"])
#             except httpx.ConnectError as e:
#                 raise OllamaUnavailableError() from e

#         return embeddings

#     async def health_check(self) -> tuple[bool, int]:
#         """
#         Check if Ollama is available.
#         Returns (available, latency_ms).
#         """
#         start = time.monotonic()
#         try:
#             response = await self._client.get("/api/tags", timeout=5.0)
#             latency_ms = int((time.monotonic() - start) * 1000)
#             return response.status_code == 200, latency_ms
#         except Exception:
#             return False, 0

#     async def list_models(self) -> list[str]:
#         """Return names of locally available Ollama models."""
#         try:
#             response = await self._client.get("/api/tags", timeout=5.0)
#             response.raise_for_status()
#             data = response.json()
#             return [m["name"] for m in data.get("models", [])]
#         except Exception:
#             return []

#     async def close(self) -> None:
#         await self._client.aclose()


# # ── Module-level singleton ────────────────────────────────────────────────────
# _ollama_client: OllamaClient | None = None


# def get_ollama_client() -> OllamaClient:
#     global _ollama_client
#     if _ollama_client is None:
#         _ollama_client = OllamaClient(
#             base_url=settings.ollama_host,
#             timeout=settings.ollama_timeout,
#         )
#     return _ollama_client


# async def close_ollama_client() -> None:
#     global _ollama_client
#     if _ollama_client:
#         await _ollama_client.close()
#         _ollama_client = None


"""
Async Ollama client.

Wraps the Ollama REST API with retry logic, timeout handling,
and a clean interface for both chat and embedding operations.

Supports LLM_PROVIDER switch in .env:
    LLM_PROVIDER=ollama  → uses local Ollama models (default)
    LLM_PROVIDER=nvidia  → routes to NVIDIA API (deepseek-v4-pro)
"""

from __future__ import annotations

import time
from typing import AsyncGenerator, Optional

import httpx
from openai import AsyncOpenAI, OpenAIError
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.shared.exceptions import OllamaUnavailableError

settings = get_settings()

# Reused across calls: constructing AsyncOpenAI per request forces a fresh TLS
# handshake and discards the connection pool. Built lazily so importing this
# module never requires an NVIDIA key when LLM_PROVIDER=ollama.
_nvidia_singleton: AsyncOpenAI | None = None

# deepseek-v4-pro emits a reasoning pass by default. It is filtered out of the
# stream either way, but generating it costs latency and eats into max_tokens,
# so turn it off at the template level.
_NVIDIA_NO_THINKING = {"chat_template_kwargs": {"thinking": False}}


def _nvidia_client() -> AsyncOpenAI:
    global _nvidia_singleton
    if _nvidia_singleton is None:
        _nvidia_singleton = AsyncOpenAI(
            base_url=settings.nvidia_base_url,
            api_key=settings.nvidia_api_key.get_secret_value(),
        )
    return _nvidia_singleton

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

    # ── NVIDIA private helper ─────────────────────────────────────────────────

    async def _nvidia_chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Route chat to NVIDIA API (deepseek-v4-pro)."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            completion = await _nvidia_client().chat.completions.create(
                model=settings.nvidia_chat_model,
                messages=messages,
                temperature=(
                    settings.nvidia_temperature if temperature is None else temperature
                ),
                top_p=settings.nvidia_top_p,
                max_tokens=settings.nvidia_max_tokens,
                stream=False,
                extra_body=_NVIDIA_NO_THINKING,
            )
        except OpenAIError as e:
            raise OllamaUnavailableError(f"NVIDIA API unavailable: {e}") from e
        return completion.choices[0].message.content

    async def _nvidia_chat_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming version for NVIDIA API."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            stream = await _nvidia_client().chat.completions.create(
                model=settings.nvidia_chat_model,
                messages=messages,
                temperature=(
                    settings.nvidia_temperature if temperature is None else temperature
                ),
                top_p=settings.nvidia_top_p,
                max_tokens=settings.nvidia_max_tokens,
                stream=True,
                extra_body=_NVIDIA_NO_THINKING,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                # Reasoning arrives on delta.reasoning_content, never on delta.content,
                # so reading content alone keeps any thinking out of the user stream.
                content = getattr(delta, "content", None)
                if content:
                    yield content
        except OpenAIError as e:
            raise OllamaUnavailableError(f"NVIDIA API unavailable: {e}") from e

    # ── Public interface (same as before — coding_agent.py unchanged) ─────────

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
        temperature: Optional[float] = None,
    ) -> str:
        """
        Single-turn chat completion.
        Routes to NVIDIA or Ollama based on LLM_PROVIDER setting.

        ``temperature=None`` means "use the configured default for whichever
        provider is active" — NVIDIA_TEMPERATURE or the Ollama default below.
        """
        # ── Switch: NVIDIA ────────────────────────────────────────────────────
        if settings.llm_provider == "nvidia":
            return await self._nvidia_chat(prompt, system_prompt, temperature)

        # ── Switch: Ollama (default) ──────────────────────────────────────────
        temperature = 0.15 if temperature is None else temperature
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
                    "options": {
                        "temperature": temperature,
                        "num_ctx": settings.ollama_num_ctx,
                        "num_predict": settings.ollama_num_predict,
                        "repeat_penalty": 1.1,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            content = str(data["message"]["content"])
            # Strip <think>...</think> blocks from thinking models
            import re as _re
            content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()
            return content
        except httpx.ConnectError as e:
            raise OllamaUnavailableError() from e
        except httpx.TimeoutException as e:
            raise OllamaUnavailableError("Ollama request timed out") from e

    async def chat_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming chat completion.
        Routes to NVIDIA or Ollama based on LLM_PROVIDER setting.

        ``temperature=None`` means "use the configured default for whichever
        provider is active" — NVIDIA_TEMPERATURE or the Ollama default below.
        """
        # ── Switch: NVIDIA ────────────────────────────────────────────────────
        if settings.llm_provider == "nvidia":
            async for chunk in self._nvidia_chat_stream(
                prompt, system_prompt, temperature
            ):
                yield chunk
            return

        # ── Switch: Ollama (default) ──────────────────────────────────────────
        import json as _json

        temperature = 0.1 if temperature is None else temperature
        model = model or settings.ollama_chat_model
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0),
            ) as stream_client:
                async with stream_client.stream(
                    "POST",
                    "/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": True,
                        "options": {
                            "temperature": temperature,
                            "num_ctx": settings.ollama_num_ctx,
                            "num_predict": settings.ollama_num_predict,
                            "repeat_penalty": 1.1,
                        },
                    },
                ) as response:
                    response.raise_for_status()
                    in_think = False
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = _json.loads(line)
                        except _json.JSONDecodeError:
                            continue
                        content = chunk.get("message", {}).get("content", "")
                        if not content:
                            if chunk.get("done"):
                                break
                            continue
                        # Strip <think>...</think> blocks from thinking models (qwen3, deepseek-r1)
                        if "<think>" in content:
                            in_think = True
                        if in_think:
                            if "</think>" in content:
                                in_think = False
                                after = content.split("</think>", 1)[1]
                                if after:
                                    yield after
                            continue
                        yield content
                        if chunk.get("done"):
                            break
        except httpx.ConnectError as e:
            raise OllamaUnavailableError() from e
        except httpx.TimeoutException as e:
            raise OllamaUnavailableError("Ollama stream timed out") from e

    # ── Embeddings (always Ollama — NVIDIA not used for embeddings) ───────────

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
        Always uses Ollama (nomic-embed-text) regardless of LLM_PROVIDER.
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