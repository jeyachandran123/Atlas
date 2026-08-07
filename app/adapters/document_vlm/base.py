"""Shared machinery for HTTP-backed ``DocumentVLMPort`` adapters.

Retries, timeouts, error classification, JSON recovery and telemetry are
identical whether the model is behind NVIDIA's cloud or a local Ollama daemon —
they are properties of *calling a model over HTTP*, not of any provider. So they
live here once, and a concrete adapter supplies only the four things that
genuinely differ:

``_endpoint()``      where to POST
``_headers()``       what to authenticate with
``_body()``          the provider's request shape
``_read_response()`` where the text and the usage live in the reply

A new provider is those four methods plus a registration line. That is the whole
cost of adding Claude Vision, Gemini Vision, OpenAI Vision or Qwen Cloud, and it
is deliberately small — an abstraction that makes the second implementation
cheap and the fifth expensive has not actually abstracted anything.
"""

from __future__ import annotations

import asyncio
import base64
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.document_platform.vlm.errors import (
    DocumentVLMAuthError,
    DocumentVLMBadRequestError,
    DocumentVLMConnectionError,
    DocumentVLMError,
    DocumentVLMInvalidResponseError,
    DocumentVLMRateLimitError,
    DocumentVLMRefusedError,
    DocumentVLMTimeoutError,
    DocumentVLMUpstreamError,
)
from app.document_platform.vlm.json_repair import parse_model_json
from app.document_platform.vlm.observability import (
    VLMCallRecord,
    record_retry,
    record_vlm_call,
)
from app.document_platform.vlm.ports import (
    CostEstimate,
    DocumentImage,
    ProviderHealth,
    TokenUsage,
    VLMExtractionRequest,
    VLMExtractionResult,
)

#: Rough token cost of one page image. Providers price vision differently and
#: none of them publish an exact formula, so this is an order-of-magnitude
#: figure used only for pre-flight estimates — never for billing.
IMAGE_TOKEN_ESTIMATE = 1024

#: Characters per token, for text. Four is the usual English approximation and
#: is close enough for a budget check.
CHARS_PER_TOKEN = 4

#: Phrases that mean "the model declined" rather than "the model failed".
#: Checked only when the response contained no JSON at all, so an invoice whose
#: notes field says "I cannot process this" is never mistaken for a refusal.
_REFUSAL_MARKERS = (
    "i cannot assist",
    "i can't assist",
    "i cannot help with",
    "i'm unable to help",
    "i am unable to help",
    "i cannot process",
    "i'm not able to provide",
    "i am not able to provide",
    "violates my",
    "against my guidelines",
    "as an ai language model, i cannot",
)


@dataclass(frozen=True)
class VLMAdapterConfig:
    """Everything an HTTP VLM adapter needs, resolved from the environment.

    ``api_key`` is held as a plain string because it is only ever used to build
    a header — it is never placed in a DTO, a log record, an exception, or a
    ``repr``. ``__repr__`` below is overridden for the same reason: a dataclass
    that prints its own fields will eventually print this one into a stack
    trace.
    """

    base_url: str
    model: str
    api_key: str = ""
    timeout_seconds: float = 120.0
    connect_timeout_seconds: float = 10.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.5
    max_output_tokens: int = 4096
    temperature: float = 0.0
    health_timeout_seconds: float = 10.0
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("a VLM adapter needs a base URL")
        if not self.model.strip():
            raise ValueError("a VLM adapter needs a model name")

    @property
    def endpoint_root(self) -> str:
        return self.base_url.rstrip("/")

    def __repr__(self) -> str:
        return (
            f"VLMAdapterConfig(base_url={self.base_url!r}, model={self.model!r}, "
            f"api_key={'set' if self.api_key else 'unset'}, "
            f"timeout_seconds={self.timeout_seconds})"
        )


class HttpDocumentVLMAdapter(ABC):
    """Base for adapters that reach a model over HTTP. Implements the port.

    Conforms structurally to ``DocumentVLMPort``; the protocol is not inherited
    on purpose, so an adapter cannot accidentally satisfy the type checker by
    inheriting a method it never implemented.
    """

    provider: str = "http"

    def __init__(
        self,
        config: VLMAdapterConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self._config = config
        self._transport = transport
        """Injected in tests so every failure mode — 401, 429, 5xx, timeout,
        malformed JSON — is reproducible without a network or an API key."""

        self._sleep = sleep
        """Injected so retry tests assert on backoff instead of waiting for it."""

    # ── identity ─────────────────────────────────────────────────────────────

    def provider_name(self) -> str:
        return self.provider

    def model_name(self) -> str:
        return self._config.model

    @property
    def config(self) -> VLMAdapterConfig:
        return self._config

    # ── the port ─────────────────────────────────────────────────────────────

    async def extract_document(
        self, request: VLMExtractionRequest
    ) -> VLMExtractionResult:
        """Call the model, with bounded retries, and return what it said as data.

        Retries only what is worth retrying (timeouts, 429, 5xx, transport
        failures) and never what is not (401, 400, an unparseable answer at
        temperature zero) — a retry that cannot succeed is latency the caller
        pays for nothing.
        """
        record = VLMCallRecord(
            provider=self.provider,
            model=self._config.model,
            request_id=request.request_id,
            prompt_id=request.prompt.prompt_id,
            prompt_version=request.prompt.version,
            image_count=len(request.payload.images),
            image_bytes=request.payload.total_image_bytes,
            text_chars=len(request.payload.ocr_text),
            endpoint=self._endpoint(),
        )
        started = time.perf_counter()
        attempt = 0

        while True:
            try:
                raw_text, usage, finish_reason = await self._call(request)
                break
            except DocumentVLMError as exc:
                if exc.retryable and attempt < self._config.max_retries:
                    delay = self._backoff(attempt, exc.retry_after_seconds)
                    record_retry(self.provider, self._config.model, exc.code)
                    attempt += 1
                    await self._sleep(delay)
                    continue
                record.outcome = "error"
                record.error_code = exc.code
                record.retry_count = attempt
                record.latency_ms = (time.perf_counter() - started) * 1000.0
                record_vlm_call(record)
                exc.request_id = exc.request_id or request.request_id
                raise

        latency_ms = (time.perf_counter() - started) * 1000.0
        parsed = parse_model_json(raw_text)

        record.retry_count = attempt
        record.latency_ms = latency_ms
        record.finish_reason = finish_reason
        record.prompt_tokens = usage.prompt_tokens
        record.completion_tokens = usage.completion_tokens
        record.total_tokens = usage.total_tokens
        record.json_strategy = parsed.strategy
        record.json_repaired = parsed.repaired

        if not parsed.ok:
            record.outcome = "error"
            if self._looks_like_refusal(raw_text):
                record.error_code = DocumentVLMRefusedError.code
                record_vlm_call(record)
                raise DocumentVLMRefusedError(
                    "the model declined to extract this document",
                    provider=self.provider,
                    model=self._config.model,
                    request_id=request.request_id,
                )
            record.error_code = DocumentVLMInvalidResponseError.code
            record_vlm_call(record)
            raise DocumentVLMInvalidResponseError(
                f"the model's response was not usable JSON: {parsed.error}",
                raw_excerpt=raw_text,
                provider=self.provider,
                model=self._config.model,
                request_id=request.request_id,
            )

        structured = self._as_object(parsed.value)
        if structured is None:
            record.outcome = "error"
            record.error_code = DocumentVLMInvalidResponseError.code
            record_vlm_call(record)
            raise DocumentVLMInvalidResponseError(
                f"the model returned a JSON {type(parsed.value).__name__}, not an "
                f"object; an extraction must be a single object",
                raw_excerpt=raw_text,
                provider=self.provider,
                model=self._config.model,
                request_id=request.request_id,
            )

        record_vlm_call(record)
        return VLMExtractionResult(
            structured=structured,
            raw_text=raw_text,
            provider=self.provider,
            model=self._config.model,
            latency_ms=latency_ms,
            usage=usage,
            request_id=request.request_id,
            retry_count=attempt,
            finish_reason=finish_reason,
            repaired=parsed.repaired,
            prompt_id=request.prompt.prompt_id,
            prompt_version=request.prompt.version,
        )

    async def health(self) -> ProviderHealth:
        """Probe the provider. Never raises — unhealthy is a result, not an error."""
        started = time.perf_counter()
        try:
            healthy, detail = await self._probe_health()
            return ProviderHealth(
                healthy=healthy,
                provider=self.provider,
                model=self._config.model,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                detail=detail,
                error="" if healthy else str(detail.get("reason", "")),
            )
        except DocumentVLMError as exc:
            return ProviderHealth(
                healthy=False,
                provider=self.provider,
                model=self._config.model,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                detail={"error_code": exc.code},
                error=exc.message,
            )
        except Exception as exc:  # noqa: BLE001 - health must never propagate
            return ProviderHealth(
                healthy=False,
                provider=self.provider,
                model=self._config.model,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                detail={"error_code": "unexpected"},
                error=f"{type(exc).__name__}: {exc}",
            )

    def estimate_cost(self, request: VLMExtractionRequest) -> CostEstimate:
        """Token-based estimate. Subclasses price it; this counts it."""
        prompt_tokens = self._estimate_prompt_tokens(request)
        completion_tokens = request.prompt.max_output_tokens
        return CostEstimate(
            amount=0.0,
            currency="none",
            estimated_prompt_tokens=prompt_tokens,
            estimated_completion_tokens=completion_tokens,
            basis=f"{self.provider}: token estimate only, no price configured",
        )

    # ── what a provider must supply ──────────────────────────────────────────

    @abstractmethod
    def _endpoint(self) -> str:
        """Absolute URL of the chat/completion endpoint."""

    @abstractmethod
    def _headers(self) -> dict[str, str]:
        """Request headers, including auth. Never logged."""

    @abstractmethod
    def _body(self, request: VLMExtractionRequest) -> dict[str, Any]:
        """The provider's request shape for this extraction."""

    @abstractmethod
    def _read_response(self, data: Mapping[str, Any]) -> tuple[str, TokenUsage, str]:
        """``(text, usage, finish_reason)`` out of the provider's reply."""

    @abstractmethod
    async def _probe_health(self) -> tuple[bool, dict[str, Any]]:
        """``(healthy, detail)``. Detail keys are provider-neutral."""

    # ── HTTP ─────────────────────────────────────────────────────────────────

    async def _call(
        self, request: VLMExtractionRequest
    ) -> tuple[str, TokenUsage, str]:
        timeout = request.timeout_seconds or self._config.timeout_seconds
        response = await self._post(
            self._endpoint(), self._body(request), timeout=timeout
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise DocumentVLMInvalidResponseError(
                "the provider's response body was not JSON",
                raw_excerpt=response.text[:2000],
                provider=self.provider,
                model=self._config.model,
                request_id=request.request_id,
            ) from exc

        if not isinstance(data, Mapping):
            raise DocumentVLMInvalidResponseError(
                f"the provider returned a {type(data).__name__} envelope, not an object",
                raw_excerpt=str(data)[:2000],
                provider=self.provider,
                model=self._config.model,
                request_id=request.request_id,
            )
        return self._read_response(data)

    async def _post(
        self, url: str, body: Mapping[str, Any], *, timeout: float
    ) -> httpx.Response:
        async with self._client(timeout) as client:
            try:
                response = await client.post(url, json=dict(body), headers=self._headers())
            except httpx.TimeoutException as exc:
                raise DocumentVLMTimeoutError(
                    f"{self.provider} did not respond within {timeout:.0f}s",
                    provider=self.provider,
                    model=self._config.model,
                    timeout_seconds=timeout,
                ) from exc
            except httpx.HTTPError as exc:
                raise DocumentVLMConnectionError(
                    f"could not reach {self.provider}: {type(exc).__name__}",
                    provider=self.provider,
                    model=self._config.model,
                ) from exc

        if response.status_code >= 400:
            raise self._classify(response)
        return response

    async def _get(self, url: str, *, timeout: float) -> httpx.Response:
        async with self._client(timeout) as client:
            try:
                response = await client.get(url, headers=self._headers())
            except httpx.TimeoutException as exc:
                raise DocumentVLMTimeoutError(
                    f"{self.provider} did not respond within {timeout:.0f}s",
                    provider=self.provider,
                    model=self._config.model,
                ) from exc
            except httpx.HTTPError as exc:
                raise DocumentVLMConnectionError(
                    f"could not reach {self.provider}: {type(exc).__name__}",
                    provider=self.provider,
                    model=self._config.model,
                ) from exc
        return response

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout,
                connect=self._config.connect_timeout_seconds,
                read=timeout,
                write=self._config.connect_timeout_seconds,
            ),
            transport=self._transport,
        )

    # ── classification ───────────────────────────────────────────────────────

    def _classify(self, response: httpx.Response) -> DocumentVLMError:
        """HTTP status → typed error. Overridable for provider quirks.

        The message quotes the provider's own explanation when there is one,
        truncated — a 400 that says "model does not support images" is worth
        far more to an operator than "bad request".
        """
        status = response.status_code
        detail = self._error_detail(response)
        common: dict[str, Any] = {
            "provider": self.provider,
            "model": self._config.model,
            "status_code": status,
        }

        if status in (401, 403):
            return DocumentVLMAuthError(
                f"{self.provider} rejected the credentials (HTTP {status}); check "
                f"the API key configured for this provider",
                **common,
            )
        if status == 429:
            return DocumentVLMRateLimitError(
                f"{self.provider} is rate limiting this account (HTTP 429){detail}",
                retry_after_seconds=self._retry_after(response),
                **common,
            )
        if status >= 500:
            return DocumentVLMUpstreamError(
                f"{self.provider} returned HTTP {status}{detail}", **common
            )
        return DocumentVLMBadRequestError(
            f"{self.provider} rejected the request (HTTP {status}){detail}", **common
        )

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """A short, safe excerpt of the provider's error body."""
        try:
            body = response.json()
        except ValueError:
            body = response.text
        if isinstance(body, Mapping):
            error = body.get("error", body)
            message = (
                error.get("message") if isinstance(error, Mapping) else str(error)
            )
        else:
            message = str(body)
        message = (message or "").strip().replace("\n", " ")
        return f": {message[:300]}" if message else ""

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        raw = response.headers.get("retry-after")
        if not raw:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            return None  # HTTP-date form; the default backoff applies

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        """Exponential, capped, and deterministic.

        No jitter: a document extraction API serves a handful of concurrent
        callers, not a thundering herd, and determinism makes the retry tests
        assert on a number instead of a range.
        """
        if retry_after is not None:
            return min(retry_after, 30.0)
        return min(self._config.retry_backoff_seconds * (2**attempt), 30.0)

    # ── helpers for subclasses ───────────────────────────────────────────────

    @staticmethod
    def _data_url(image: DocumentImage) -> str:
        encoded = base64.b64encode(image.data).decode("ascii")
        return f"data:{image.media_type};base64,{encoded}"

    @staticmethod
    def _b64(image: DocumentImage) -> str:
        return base64.b64encode(image.data).decode("ascii")

    def _estimate_prompt_tokens(self, request: VLMExtractionRequest) -> int:
        text_chars = len(request.prompt.system) + len(request.prompt.user)
        return (
            text_chars // CHARS_PER_TOKEN
            + len(request.payload.images) * IMAGE_TOKEN_ESTIMATE
        )

    @staticmethod
    def _as_object(value: Any) -> dict[str, Any] | None:
        """Coerce the parsed JSON to a single object, or refuse.

        A one-element list containing an object is unwrapped — models wrap
        answers in arrays often enough that rejecting it would fail extractions
        over punctuation. Anything else is refused rather than guessed at.
        """
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
            return dict(value[0])
        return None

    @staticmethod
    def _looks_like_refusal(text: str) -> bool:
        lowered = (text or "").lower()
        return any(marker in lowered for marker in _REFUSAL_MARKERS)

    @staticmethod
    def _usage_from(payload: Any) -> TokenUsage:
        """Read an OpenAI-shaped ``usage`` block, tolerating its absence."""
        if not isinstance(payload, Mapping):
            return TokenUsage()

        def _int(key: str) -> int | None:
            value = payload.get(key)
            return int(value) if isinstance(value, int | float) else None

        return TokenUsage(
            prompt_tokens=_int("prompt_tokens"),
            completion_tokens=_int("completion_tokens"),
            total_tokens=_int("total_tokens"),
        )


__all__ = [
    "CHARS_PER_TOKEN",
    "IMAGE_TOKEN_ESTIMATE",
    "HttpDocumentVLMAdapter",
    "VLMAdapterConfig",
]
