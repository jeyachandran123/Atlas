"""
LLM Provider abstraction (Objective 9). The ONLY module in the platform
allowed to speak an LLM's wire protocol for conversational answering.
OpenAI/Azure/Anthropic/Google later = one new subclass each.

The document workspace runs on the self-hosted UnityWorks deployment. Local
inference was removed rather than kept as a fallback: on CPU it produced a few
tokens a second, which meant an Excel generation could not finish inside any
sane timeout, and it streamed with no read ceiling — so a stalled model left the
UI on "Generating answer…" with nothing to time out and nothing to report.

The endpoint's shape drives two decisions here:

* **It answers in one shot.** There is no token stream to forward, so
  ``stream()`` fetches the answer and paces it out in slices. The surface still
  renders progressively; it just is not token-by-token.
* **It reports no token counts.** ``LLMResult`` carries zeros, and that is a
  known gap rather than a hidden one: Objective 15 wanted real counts from the
  provider, and this provider does not publish them. Estimating them here would
  put invented numbers into the same field that used to hold measured ones.

Protocol handling (think-block stripping, envelope reading) is provider code by
definition — no business logic lives here.
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger

from app.document_platform.conversation.prompts import StructuredPrompt

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

_BOXED_DISPLAY_RE = re.compile(r"\\\[\s*\\boxed\{(.*?)\}\s*\\\]", re.DOTALL)
_BOXED_RE = re.compile(r"\\boxed\{(.*?)\}", re.DOTALL)
r"""The deployed model finishes a numeric answer in LaTeX display math.

Asked for a row count it replies "... is 1252. \[ \boxed{1252} \]". Markdown
renders none of that, so the user reads a stray backslash-bracket and the
number twice. Unwrapping it is protocol handling in the same sense that
dropping the reasoning block is: the answer is the content, and the envelope
belongs to the model rather than to the platform.
"""


def _unwrap_math(text: str) -> str:
    """Take the LaTeX envelope off without taking anything else with it.

    A display block is usually the model restating a number the sentence above
    already gave, and unwrapping that leaves a bare digit dangling after the
    prose. So a restatement is dropped and anything new is kept: no reading of
    this ever removes a value the answer had not already stated.
    """

    def _display(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        before = text[: match.start()]
        return "" if inner and inner in before else inner

    return _BOXED_RE.sub(r"\1", _BOXED_DISPLAY_RE.sub(_display, text)).strip()

STREAM_SLICE = 40
"""Characters per emitted chunk when the provider answers in one shot.

Small enough that the answer visibly builds, large enough that a long report is
not thousands of separate server-sent events.
"""


class LLMProviderError(Exception):
    """The LLM provider call failed (transient — retryable).

    Every failure path below raises this and nothing else: the reasoning engine
    retries on this type, so an error that escapes as anything else burns the
    turn instead of being retried.
    """


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


class UnityWorksLLMProvider(AbstractLLMProvider):
    """The self-hosted UnityWorks deployment: one prompt in, one answer out."""

    name = "unityworks"

    def __init__(
        self,
        settings: Any = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if settings is None:
            from app.config import get_settings

            settings = get_settings()

        url = str(getattr(settings, "unityworks_base_url", "") or "").strip()
        if not url:
            raise LLMProviderError(
                "UNITYWORKS_BASE_URL is not set; the document workspace has no "
                "LLM endpoint to answer or generate with"
            )
        self._url = url

        key = getattr(settings, "unityworks_api_key", "")
        if hasattr(key, "get_secret_value"):
            key = key.get_secret_value()
        self._api_key = str(key or "")

        self.model_name = str(getattr(settings, "unityworks_model", "") or "unityworks-vlm")
        self._max_output_tokens = int(getattr(settings, "dip_max_output_tokens", 8192))
        self._timeout = float(getattr(settings, "dip_llm_timeout_seconds", 300.0))
        self._transport = transport
        """Injected in tests so every failure mode is reproducible without a
        network or an API key."""

    # ── wire format ──────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    def _payload(self, prompt: StructuredPrompt) -> dict[str, Any]:
        """One prompt string, because that is what the endpoint accepts.

        The platform composes system and user separately; they are joined here
        verbatim and nothing is added to them.
        """
        system = prompt.system.strip()
        user = prompt.user.strip()
        return {
            "prompt": f"{system}\n\n{user}" if system else user,
            "max_new_tokens": prompt.max_output_tokens or self._max_output_tokens,
        }

    async def _answer(self, prompt: StructuredPrompt) -> str:
        """One call. Every failure becomes a retryable LLMProviderError.

        Error messages carry the status or the exception type, never the
        response body: a provider that echoes its own error text can echo a
        header back with it.
        """
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0, read=self._timeout, write=30.0),
                transport=self._transport,
            ) as client:
                response = await client.post(
                    self._url, json=self._payload(prompt), headers=self._headers()
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise LLMProviderError(
                f"UnityWorks did not answer within {self._timeout:.0f}s"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(f"UnityWorks returned HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMProviderError(f"UnityWorks call failed: {type(exc).__name__}") from exc

        if not isinstance(data, dict) or "output" not in data:
            raise LLMProviderError("UnityWorks reply carried no 'output' field")
        return _unwrap_math(_THINK_RE.sub("", str(data["output"] or ""))).strip()

    # ── the port ─────────────────────────────────────────────────────────────

    async def generate(self, prompt: StructuredPrompt) -> LLMResult:
        start = time.monotonic()
        text = await self._answer(prompt)
        return LLMResult(
            text=text,
            # The endpoint publishes no usage. Zero here means "not reported";
            # an estimate would be indistinguishable from a measurement.
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=int((time.monotonic() - start) * 1000),
            provider=self.name,
            model=self.model_name,
        )

    async def stream(self, prompt: StructuredPrompt, stats: StreamStats) -> AsyncIterator[str]:
        """Fetch once, then pace the answer out so the surface renders as it goes."""
        start = time.monotonic()
        try:
            text = await self._answer(prompt)
            for index in range(0, len(text), STREAM_SLICE):
                chunk = text[index : index + STREAM_SLICE]
                stats.chunks.append(chunk)
                yield chunk
        finally:
            stats.latency_ms = int((time.monotonic() - start) * 1000)
            stats.full_text = "".join(stats.chunks).strip()


class NvidiaLLMProvider(AbstractLLMProvider):
    """NVIDIA's hosted endpoint, speaking the OpenAI chat-completions shape.

    Here so the document platform keeps answering when the self-hosted
    deployment is not up. A Lightning deployment scaled to zero replicas
    answers every request with

        HTTP 500 "cannot start deployment because the max number of
        replicas is 0, increase to at least 1"

    which reached users as "This response could not be generated" on every
    question in the workspace. One provider switch now moves reading, writing
    and answering together, so an outage on one side is a setting away from
    being routed around rather than a dead workspace.
    """

    name = "nvidia"

    def __init__(
        self,
        settings: Any = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if settings is None:
            from app.config import get_settings

            settings = get_settings()

        key = getattr(settings, "vision_nvidia_api_key", "") or getattr(
            settings, "nvidia_api_key", ""
        )
        if hasattr(key, "get_secret_value"):
            key = key.get_secret_value()
        self._api_key = str(key or "")
        if not self._api_key:
            raise LLMProviderError(
                "No NVIDIA API key is set, so the document platform has no "
                "endpoint to answer with"
            )
        from app.llm import DOCUMENT, get_chat_gateway

        self._gateway = get_chat_gateway()
        self.model_name = self._gateway.profile(DOCUMENT).model
        # Still accepted so existing callers construct this unchanged; the
        # gateway owns the connection now.
        self._transport = transport

    @staticmethod
    def _profile_for(prompt: StructuredPrompt) -> str:
        """Which kind of answer this prompt wants.

        Talk addressed to the user - the assistant's small talk, the Cognitive
        Kernel's steps - is GENERAL. Anything answering from documents is
        DOCUMENT: literal and low-temperature, because the validator has to be
        able to tie every sentence back to a source.
        """
        from app.llm import DOCUMENT, GENERAL

        return GENERAL if prompt.strategy in ("assistant", "cognitive") else DOCUMENT

    async def _complete(self, prompt: StructuredPrompt):
        from app.llm import LLMGatewayError

        try:
            return await self._gateway.complete(
                system=prompt.system, user=prompt.user,
                profile=self._profile_for(prompt),
                max_tokens=prompt.max_output_tokens or None,
            )
        except LLMGatewayError as exc:
            raise LLMProviderError(str(exc)) from exc

    async def _answer(self, prompt: StructuredPrompt) -> str:
        return _unwrap_math((await self._complete(prompt)).text).strip()

    async def generate(self, prompt: StructuredPrompt) -> LLMResult:
        result = await self._complete(prompt)
        return LLMResult(
            text=_unwrap_math(result.text).strip(),
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            latency_ms=result.latency_ms,
            provider=self.name,
            model=result.model,
        )

    async def stream(self, prompt: StructuredPrompt, stats: StreamStats) -> AsyncIterator[str]:
        """Fetched whole, then paced out - same as the self-hosted provider.

        Real token streaming is available here and deliberately not used: the
        validator needs the finished answer before any of it is trusted, so
        pacing a complete answer keeps both providers behaving identically.
        """
        start = time.monotonic()
        try:
            text = await self._answer(prompt)
            for index in range(0, len(text), STREAM_SLICE):
                chunk = text[index : index + STREAM_SLICE]
                stats.chunks.append(chunk)
                yield chunk
        finally:
            stats.latency_ms = int((time.monotonic() - start) * 1000)
            stats.full_text = "".join(stats.chunks).strip()


def get_llm_provider(provider_name: str | None = None) -> AbstractLLMProvider:
    """Which model answers questions about documents.

    Follows DOCUMENT_VLM_PROVIDER, the one switch that also decides which model
    reads images and which writes transformation code - so "which AI is this
    running on" has a single answer instead of three that can disagree.

    Falling back rather than raising is deliberate: a misconfigured provider
    name should degrade to a working platform, not an unanswerable workspace.
    """
    from app.config import get_settings

    settings = get_settings()
    name = provider_name or getattr(settings, "document_vlm_provider", "unityworks")
    if name == "nvidia":
        try:
            return NvidiaLLMProvider(settings)
        except LLMProviderError:
            logger.warning(
                "DOCUMENT_VLM_PROVIDER=nvidia but no NVIDIA key is set; "
                "answering with the self-hosted deployment instead"
            )
            return UnityWorksLLMProvider(settings)
    if name == "unityworks":
        return UnityWorksLLMProvider(settings)
    logger.warning(
        f"DOCUMENT_VLM_PROVIDER={name!r} names no answering model; "
        f"using the self-hosted deployment"
    )
    return UnityWorksLLMProvider(settings)
