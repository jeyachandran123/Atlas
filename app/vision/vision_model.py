"""
Vision Model — routes image+text requests to a vision-capable LLM.

Supports:
  - Ollama vision models (llava, llama3.2-vision, bakllava)
  - NVIDIA multimodal models (via OpenAI-compatible API)

The model router automatically selects the vision model when images are present.
Which provider serves it is VISION_PROVIDER, falling back to LLM_PROVIDER when
unset — so images can run on a cloud VLM while text chat stays local.
"""
from __future__ import annotations

import base64
from typing import AsyncGenerator, Optional

import httpx
from loguru import logger

from app.config import get_settings

settings = get_settings()

# Vision model configuration — reads from settings
OLLAMA_VISION_MODEL = getattr(settings, "vision_model", "qwen2.5vl:7b")


# Magic-byte prefixes, longest-first where they overlap.
_IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _sniff_mime(data: bytes) -> str:
    """Media type for a data URL, read from the bytes rather than assumed.

    Ollama takes bare base64 and never asks what format it is. NVIDIA's
    OpenAI-compatible endpoint reads the data-URL media type, so a JPEG
    announced as image/png is a payload the server can refuse outright.
    """
    for magic, mime in _IMAGE_MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


class VisionModel:
    """Handles vision LLM calls with image inputs."""

    def __init__(self) -> None:
        self._base_url = settings.ollama_host.rstrip("/")

    async def chat(
        self,
        prompt: str,
        system_prompt: str,
        image_data: list[bytes],
        temperature: float = 0.3,
    ) -> str:
        """Single-turn vision chat. Returns complete response."""
        if settings.vision_provider_resolved == "nvidia":
            return await self._nvidia_vision_chat(prompt, system_prompt, image_data, temperature)
        return await self._ollama_vision_chat(prompt, system_prompt, image_data, temperature)

    async def chat_stream(
        self,
        prompt: str,
        system_prompt: str,
        image_data: list[bytes],
        temperature: float = 0.3,
    ) -> AsyncGenerator[str, None]:
        """Streaming vision chat. Yields text chunks."""
        if settings.vision_provider_resolved == "nvidia":
            async for chunk in self._nvidia_vision_stream(prompt, system_prompt, image_data, temperature):
                yield chunk
        else:
            async for chunk in self._ollama_vision_stream(prompt, system_prompt, image_data, temperature):
                yield chunk

    # ── Ollama Vision ─────────────────────────────────────────────────────────

    async def _ollama_vision_chat(
        self, prompt: str, system_prompt: str, image_data: list[bytes], temperature: float
    ) -> str:
        """Ollama multimodal chat (non-streaming)."""
        messages = self._build_ollama_messages(prompt, system_prompt, image_data)
        async with httpx.AsyncClient(timeout=httpx.Timeout(300)) as client:
            response = await client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": OLLAMA_VISION_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature, "num_ctx": 8192},
                },
            )
            response.raise_for_status()
            data = response.json()
            return str(data["message"]["content"])

    async def _ollama_vision_stream(
        self, prompt: str, system_prompt: str, image_data: list[bytes], temperature: float
    ) -> AsyncGenerator[str, None]:
        """Ollama multimodal chat (streaming)."""
        import json as _json

        messages = self._build_ollama_messages(prompt, system_prompt, image_data)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
        ) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json={
                    "model": OLLAMA_VISION_MODEL,
                    "messages": messages,
                    "stream": True,
                    "options": {"temperature": temperature, "num_ctx": 8192},
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = _json.loads(line)
                    except _json.JSONDecodeError:
                        continue
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done"):
                        break

    @staticmethod
    def _build_ollama_messages(
        prompt: str, system_prompt: str, image_data: list[bytes]
    ) -> list[dict]:
        """Build Ollama message format with base64 images."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Ollama expects images as base64 in the message
        images_b64 = [base64.b64encode(img).decode("utf-8") for img in image_data]
        messages.append({
            "role": "user",
            "content": prompt,
            "images": images_b64,
        })
        return messages

    # ── NVIDIA Vision ─────────────────────────────────────────────────────────

    async def _nvidia_vision_chat(
        self, prompt: str, system_prompt: str, image_data: list[bytes], temperature: float
    ) -> str:
        """NVIDIA multimodal chat via OpenAI-compatible API."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=settings.nvidia_base_url,
            api_key=settings.nvidia_api_key.get_secret_value(),
        )
        messages = self._build_openai_messages(prompt, system_prompt, image_data)
        completion = await client.chat.completions.create(
            model=settings.nvidia_vision_model_resolved,
            messages=messages,
            temperature=temperature,
            top_p=settings.nvidia_top_p,
            max_tokens=settings.nvidia_max_tokens,
            stream=False,
        )
        return completion.choices[0].message.content or ""

    async def _nvidia_vision_stream(
        self, prompt: str, system_prompt: str, image_data: list[bytes], temperature: float
    ) -> AsyncGenerator[str, None]:
        """NVIDIA multimodal streaming."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=settings.nvidia_base_url,
            api_key=settings.nvidia_api_key.get_secret_value(),
        )
        messages = self._build_openai_messages(prompt, system_prompt, image_data)
        stream = await client.chat.completions.create(
            model=settings.nvidia_vision_model_resolved,
            messages=messages,
            temperature=temperature,
            top_p=settings.nvidia_top_p,
            max_tokens=settings.nvidia_max_tokens,
            stream=True,
        )
        async for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                yield content

    @staticmethod
    def _build_openai_messages(
        prompt: str, system_prompt: str, image_data: list[bytes]
    ) -> list[dict]:
        """Build OpenAI-compatible message format with inline images."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        content_parts: list[dict] = []
        for img in image_data:
            b64 = base64.b64encode(img).decode("utf-8")
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{_sniff_mime(img)};base64,{b64}"},
            })
        content_parts.append({"type": "text", "text": prompt})

        messages.append({"role": "user", "content": content_parts})
        return messages


# Singleton
_vision_model: VisionModel | None = None


def get_vision_model() -> VisionModel:
    global _vision_model
    if _vision_model is None:
        _vision_model = VisionModel()
    return _vision_model
