"""The model that writes the code - deliberately separate from the one that talks.

Document conversation runs on the self-hosted UnityWorks deployment and stays
there. Code generation is a different job with a different requirement, and the
difference is measured, not assumed. Given the same prompt, the same file and
the same sandbox, with only the model varied:

    UnityWorks 7-8B   1251 rows, codes concatenated, 5/7 checks, 3 attempts, 145s
    NVIDIA 31B        3136 rows, every rule satisfied, 7/7 checks, 1 attempt, 9s

The smaller model did not fail for lack of speed; it wrote thousands of tokens
and misread the task. The larger one wrote 408 and got it right.

What crosses the network matters here and is worth being precise about: the
prompt carries column names, inferred types, a few sample rows and the user's
request. The document's rows never leave the machine - they are mounted into a
container with no network and the generated code reads them there. Sample rows
can be withheld entirely with DIP_CODEGEN_SEND_SAMPLES=false, at some cost to
the model's grasp of the data's shape.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from loguru import logger


class CodegenError(Exception):
    """The code-writing model could not be reached or gave nothing usable."""


@dataclass(frozen=True)
class Completion:
    text: str
    latency_ms: int
    completion_tokens: int
    model: str
    provider: str

    @property
    def tokens_per_second(self) -> float:
        seconds = self.latency_ms / 1000
        return self.completion_tokens / seconds if seconds > 0 else 0.0


class AbstractCodegenModel:
    name = "abstract"
    model_name = ""

    async def complete(self, system: str, user: str, max_tokens: int) -> Completion:
        raise NotImplementedError


class OpenAICompatibleModel(AbstractCodegenModel):
    """Anything speaking /v1/chat/completions - NVIDIA's endpoint, and others."""

    name = "openai_compatible"

    def __init__(
        self, *, url: str, api_key: str, model: str, timeout: float = 300.0,
        temperature: float = 0.2, transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not url:
            raise CodegenError("No endpoint configured for the code-writing model")
        if not model:
            raise CodegenError("No model name configured for the code-writing model")
        self._url = url
        self._api_key = api_key
        self.model_name = model
        self._timeout = timeout
        self._temperature = temperature
        self._transport = transport

    async def complete(self, system: str, user: str, max_tokens: int) -> Completion:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": self._temperature,
            "top_p": 0.95,
            "stream": False,
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=15.0),
                transport=self._transport,
            ) as client:
                response = await client.post(self._url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise CodegenError(
                f"{self.model_name} did not answer within {self._timeout:.0f}s"
            ) from exc
        except httpx.HTTPStatusError as exc:
            # The body can echo the key back; the status is what is safe to keep.
            raise CodegenError(
                f"{self.model_name} returned HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise CodegenError(f"{self.model_name} call failed: {type(exc).__name__}") from exc

        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise CodegenError(f"{self.model_name} returned no message content") from exc
        usage = data.get("usage") or {}
        return Completion(
            text=text,
            latency_ms=int((time.perf_counter() - started) * 1000),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            model=self.model_name,
            provider="nvidia" if "nvidia" in self._url else self.name,
        )


class UnityWorksCodegenModel(AbstractCodegenModel):
    """The self-hosted deployment, for keeping every byte on your own hardware.

    Measurably weaker at this task than the hosted 31B - see the module
    docstring - but it is the option where nothing at all leaves the building.
    """

    name = "unityworks"

    def __init__(self, settings) -> None:
        from app.document_platform.conversation.llm import UnityWorksLLMProvider

        self._provider = UnityWorksLLMProvider(settings)
        self.model_name = self._provider.model_name

    async def complete(self, system: str, user: str, max_tokens: int) -> Completion:
        from app.document_platform.conversation.llm import LLMProviderError
        from app.document_platform.conversation.prompts import StructuredPrompt

        prompt = StructuredPrompt(
            system=system, user=user, strategy="document_task_code",
            max_output_tokens=max_tokens,
        )
        try:
            result = await self._provider.generate(prompt)
        except LLMProviderError as exc:
            raise CodegenError(str(exc)) from exc
        return Completion(
            text=result.text, latency_ms=result.latency_ms,
            completion_tokens=result.completion_tokens,
            model=result.model, provider=self.name,
        )


def get_codegen_model(settings=None) -> AbstractCodegenModel:
    if settings is None:
        from app.config import get_settings

        settings = get_settings()

    # One switch for the whole document platform's AI. DOCUMENT_VLM_PROVIDER
    # already chose which model reads images; it chooses which model writes
    # code as well, so there is a single answer to "which AI is this running
    # on" rather than two that can disagree.
    provider = str(getattr(settings, "document_vlm_provider", "nvidia")).lower()
    if provider == "unityworks":
        return UnityWorksCodegenModel(settings)
    if provider == "nvidia":
        key = getattr(settings, "vision_nvidia_api_key", "") or getattr(
            settings, "nvidia_api_key", "")
        if hasattr(key, "get_secret_value"):
            key = key.get_secret_value()
        if not key:
            logger.warning(
                "DIP_CODEGEN_PROVIDER=nvidia but no NVIDIA key is set; "
                "falling back to the self-hosted model, which is weaker at this task"
            )
            return UnityWorksCodegenModel(settings)
        return OpenAICompatibleModel(
            url=str(getattr(settings, "dip_codegen_url", "")),
            api_key=str(key),
            model=str(getattr(settings, "dip_codegen_model", "")),
            timeout=float(getattr(settings, "dip_codegen_timeout_seconds", 300.0)),
        )
    # ollama, or anything else configured for images, has no code-writing
    # counterpart here; the self-hosted model is the honest fallback.
    logger.warning(
        f"DOCUMENT_VLM_PROVIDER={provider!r} has no code-writing model; "
        f"using the self-hosted UnityWorks model"
    )
    return UnityWorksCodegenModel(settings)
