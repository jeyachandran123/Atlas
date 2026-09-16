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
    LLM_PROVIDER=nvidia  → the chat gateway, app.llm (NVIDIA_CHAT_MODEL, by profile)
    LLM_PROVIDER=ollama  → local Ollama models
Embeddings always use Ollama.
"""

from __future__ import annotations

import time
from typing import AsyncGenerator, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.llm import GENERAL, LLMGatewayError, get_chat_gateway
from app.shared.exceptions import OllamaUnavailableError

settings = get_settings()

class ReasoningDelta(str):
    """A piece of the model's thinking - not of its answer.

    ``chat_stream`` yields these only to a caller that asks for them with
    ``include_reasoning=True``, and as a distinct type so that caller can tell
    the two apart. Concatenating thinking into the answer is how "<think>"
    ends up in a saved message, and in the next turn's memory after that.
    """


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

    # ── NVIDIA: through the chat gateway ─────────────────────────────────────

    async def _nvidia_chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        *,
        profile: Optional[str] = None,
        thinking: Optional[bool] = None,
    ) -> str:
        try:
            result = await get_chat_gateway().complete(
                user=prompt, system=system_prompt, profile=profile or GENERAL,
                thinking=thinking, temperature=temperature,
            )
        except LLMGatewayError as e:
            raise OllamaUnavailableError(str(e)) from e
        return result.text

    @staticmethod
    def _conversation(
        prompt: str,
        system_prompt: Optional[str],
        history: "list[dict[str, str]] | tuple[dict[str, str], ...] | None",
    ) -> list[dict[str, str]]:
        """System, then the earlier turns, then this message. If the history ends on the
        user's side, this message joins that turn — chat templates expect turns to alternate."""
        messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
        messages.extend({"role": m["role"], "content": m["content"]} for m in (history or ()))
        if messages and messages[-1]["role"] == "user":
            messages[-1] = {"role": "user", "content": f"{messages[-1]['content']}\n\n{prompt}"}
        else:
            messages.append({"role": "user", "content": prompt})
        return messages

    async def _nvidia_chat_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        *,
        profile: Optional[str] = None,
        thinking: Optional[bool] = None,
        include_reasoning: bool = False,
        history: "list[dict[str, str]] | tuple[dict[str, str], ...] | None" = None,
    ) -> AsyncGenerator[str, None]:
        try:
            async for event in get_chat_gateway().stream(
                self._conversation(prompt, system_prompt, history),
                profile=profile or GENERAL, thinking=thinking, temperature=temperature,
            ):
                if event.kind == "content" and event.text:
                    yield event.text
                elif event.kind == "reasoning" and include_reasoning and event.text:
                    yield ReasoningDelta(event.text)
        except LLMGatewayError as e:
            raise OllamaUnavailableError(str(e)) from e

    # ── Public interface (same as before — coding_agent.py unchanged) ─────────

    async def chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        *,
        profile: Optional[str] = None,
        thinking: Optional[bool] = None,
    ) -> str:
        """
        Single-turn chat completion.
        Routes to the chat gateway (NVIDIA) or Ollama based on LLM_PROVIDER.

        ``profile`` names the kind of answer wanted - general, reasoning, math,
        coding, agent_planning, document - and ``thinking`` overrides that
        profile's default. ``temperature=None`` lets the profile decide. The
        Ollama path ignores both and uses one model per agent mode instead.
        """
        if settings.llm_provider == "nvidia":
            return await self._nvidia_chat(
                prompt, system_prompt, temperature, profile=profile, thinking=thinking,
            )
        return await self._ollama_chat(prompt, system_prompt, model, temperature)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _ollama_chat(
        self,
        prompt: str,
        system_prompt: Optional[str],
        model: Optional[str],
        temperature: Optional[float],
    ) -> str:
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
        *,
        profile: Optional[str] = None,
        thinking: Optional[bool] = None,
        include_reasoning: bool = False,
        history: "list[dict[str, str]] | tuple[dict[str, str], ...] | None" = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming chat completion.
        Routes to the chat gateway (NVIDIA) or Ollama based on LLM_PROVIDER.

        With ``include_reasoning=True`` the model's thinking is yielded too, as
        ``ReasoningDelta`` chunks a caller can tell apart from the answer.
        Without it, thinking is dropped and only the answer is yielded - the
        behaviour every existing caller was written against.

        ``history`` is the conversation so far, as {role, content} turns sent
        before ``prompt`` — so the model continues a conversation instead of
        opening a new one every turn.
        """
        if settings.llm_provider == "nvidia":
            async for chunk in self._nvidia_chat_stream(
                prompt, system_prompt, temperature, profile=profile,
                thinking=thinking, include_reasoning=include_reasoning, history=history,
            ):
                yield chunk
            return

        # ── Switch: Ollama (default) ──────────────────────────────────────────
        import json as _json

        temperature = 0.1 if temperature is None else temperature
        model = model or settings.ollama_chat_model
        messages = self._conversation(prompt, system_prompt, history)

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(connect=10.0, read=float(settings.ollama_timeout), write=30.0, pool=10.0),
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