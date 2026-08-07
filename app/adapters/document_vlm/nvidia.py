"""NVIDIA cloud VLM adapter — ``DocumentVLMPort`` over NVIDIA's Chat Completion API.

Speaks the OpenAI-compatible ``POST {base_url}/chat/completions`` endpoint that
``integrate.api.nvidia.com`` serves, with
``nvidia/llama-3.1-nemotron-nano-vl-8b-v1`` as the default model. Both are
configuration — ``NVIDIA_BASE_URL`` and ``NVIDIA_MODEL`` — because a base URL
compiled into an adapter is a base URL nobody can point at a private NIM
deployment.

Raw ``httpx`` rather than the ``openai`` SDK, deliberately: this adapter has to
classify 401 from 429 from 5xx from a truncated body precisely, honour a
per-request timeout, and be exercisable through ``httpx.MockTransport`` in a
test suite that must run with no API key and no network. A general-purpose SDK
hides exactly those seams.

**Image encoding is configurable.** NVIDIA's vision models are not consistent
with one another: some accept OpenAI-style ``image_url`` content parts, and the
Nemotron VL family documents an inline ``<img src="data:…">`` form. Rather than
guess, ``NVIDIA_IMAGE_FORMAT`` selects, defaulting to the OpenAI-compatible
shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from loguru import logger

from app.adapters.document_vlm.base import HttpDocumentVLMAdapter, VLMAdapterConfig
from app.document_platform.vlm.errors import (
    DocumentVLMBadRequestError,
    DocumentVLMError,
    DocumentVLMInvalidResponseError,
)
from app.document_platform.vlm.ports import (
    CostEstimate,
    TokenUsage,
    VLMExtractionRequest,
)

IMAGE_FORMAT_URL = "image_url"
"""OpenAI-compatible ``{"type": "image_url", "image_url": {"url": "data:…"}}``."""

IMAGE_FORMAT_INLINE = "inline_html"
"""NVIDIA VL style: an ``<img src="data:…"/>`` tag inside the text content."""

#: NVIDIA rejects inline images above roughly 180 KB of base64 on several
#: endpoints, directing callers to its assets API for anything larger. That API
#: is a second protocol this adapter deliberately does not implement — see the
#: degradation below, and the Known Limitations report.
DEFAULT_MAX_INLINE_IMAGE_BYTES = 180_000

#: Page images per request. Measured against
#: ``nvidia/llama-3.1-nemotron-nano-vl-8b-v1``: one page costs ~3,330 prompt
#: tokens, four fit in 13,992, and five overflow the server's multimodal
#: embedding table — which fails the request rather than truncating it.
DEFAULT_MAX_IMAGES = 4

#: Phrases in a 5xx body that mean "this input will never work", not "try again".
#: Retrying these spends three times the latency to fail three times.
_PERMANENT_5XX_MARKERS = (
    "prompt vocab size",
    "max prompt vocab size",
    "larger than max",
    "number of input tokens",
)


class NvidiaDocumentVLMAdapter(HttpDocumentVLMAdapter):
    """NVIDIA-hosted VLM behind ``DocumentVLMPort``."""

    provider = "nvidia"

    # ── request ──────────────────────────────────────────────────────────────

    def _endpoint(self) -> str:
        return f"{self._config.endpoint_root}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers

    def _body(self, request: VLMExtractionRequest) -> dict[str, Any]:
        prompt = request.prompt
        messages: list[dict[str, Any]] = []
        if prompt.system.strip():
            messages.append({"role": "system", "content": prompt.system})
        messages.append(self._user_message(request))

        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": prompt.temperature,
            "max_tokens": prompt.max_output_tokens,
            "stream": False,
        }
        if prompt.response_schema is not None:
            # Honoured by endpoints that support constrained decoding and
            # ignored by those that do not — either way the platform validates.
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "invoice", "schema": dict(prompt.response_schema)},
            }
        return body

    def _user_message(self, request: VLMExtractionRequest) -> dict[str, Any]:
        images = self._admissible_images(request)
        image_format = str(self._config.extra.get("image_format", IMAGE_FORMAT_URL))

        if not images:
            return {"role": "user", "content": request.prompt.user}

        if image_format == IMAGE_FORMAT_INLINE:
            tags = "".join(f'<img src="{self._data_url(img)}" />' for img in images)
            return {"role": "user", "content": f"{request.prompt.user}\n{tags}"}

        parts: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": self._data_url(image)}}
            for image in images
        ]
        parts.append({"type": "text", "text": request.prompt.user})
        return {"role": "user", "content": parts}

    def _admissible_images(self, request: VLMExtractionRequest) -> list[Any]:
        """Drop inline images the endpoint will refuse — but only if text remains.

        An oversized page with OCR text behind it costs accuracy when dropped.
        The same page with *no* text is the whole document, and sending it to be
        rejected with a clear provider error beats silently extracting nothing
        from an empty payload.
        """
        limit = int(
            self._config.extra.get("max_inline_image_bytes", DEFAULT_MAX_INLINE_IMAGE_BYTES)
        )
        images = list(request.payload.images)
        if limit <= 0:
            return images

        # base64 inflates by 4/3; compare against the encoded size the API sees.
        admissible = [img for img in images if (img.size_bytes * 4) // 3 <= limit]
        dropped = len(images) - len(admissible)
        if dropped and (admissible or request.payload.has_text):
            logger.warning(
                f"nvidia adapter: {dropped} page image(s) exceed the "
                f"{limit} byte inline limit and were not sent; extraction "
                f"continues from the remaining pages and document text"
            )
        else:
            admissible = images

        return self._within_embedding_budget(admissible)

    def _within_embedding_budget(self, images: list[Any]) -> list[Any]:
        """Cap page images at what the model's embedding table can hold.

        A backstop, not the primary control: ``DOCUMENT_VLM_MAX_PAGES`` is where
        a deployment decides how much of a document to send, and it produces a
        warning the caller can see. This exists because exceeding the budget does
        not degrade — the server returns an opaque HTTP 500 about *"prompt vocab
        size"* and the whole extraction is lost. Losing the fifth page beats
        losing all five.
        """
        limit = int(self._config.extra.get("max_images_per_request", DEFAULT_MAX_IMAGES))
        if limit <= 0 or len(images) <= limit:
            return images

        logger.warning(
            f"nvidia adapter: {len(images)} page images exceed this model's "
            f"limit of {limit} per request; sending the first {limit}. Lower "
            f"DOCUMENT_VLM_MAX_PAGES to {limit} so the caller is told which "
            f"pages were read"
        )
        return images[:limit]

    # ── classification ───────────────────────────────────────────────────────

    def _classify(self, response: httpx.Response) -> DocumentVLMError:
        """A 5xx about the input size is permanent, whatever its status code says.

        NVIDIA reports "too many page images" as an inference-time HTTP 500,
        which the generic rule treats as transient and retries twice — three
        identical failures and triple the latency, because the input is what is
        wrong. Detected by message rather than status, and turned into an error
        that names the fix.
        """
        if response.status_code >= 500:
            detail = self._error_detail(response).lower()
            if any(marker in detail for marker in _PERMANENT_5XX_MARKERS):
                return DocumentVLMBadRequestError(
                    f"nvidia could not accept this request's size (HTTP "
                    f"{response.status_code}): the document sent more page images "
                    f"than the model's embedding budget allows. Lower "
                    f"DOCUMENT_VLM_MAX_PAGES (this model accepts "
                    f"{DEFAULT_MAX_IMAGES})",
                    provider=self.provider,
                    model=self._config.model,
                    status_code=response.status_code,
                )
        return super()._classify(response)

    # ── response ─────────────────────────────────────────────────────────────

    def _read_response(self, data: Mapping[str, Any]) -> tuple[str, TokenUsage, str]:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise DocumentVLMInvalidResponseError(
                "NVIDIA returned a response with no choices",
                raw_excerpt=str(data)[:2000],
                provider=self.provider,
                model=self._config.model,
            )

        choice = choices[0] if isinstance(choices[0], Mapping) else {}
        message = choice.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None

        if isinstance(content, list):
            # Some deployments return content parts even for text-only replies.
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, Mapping) and part.get("type") in (None, "text")
            )

        if not isinstance(content, str) or not content.strip():
            raise DocumentVLMInvalidResponseError(
                "NVIDIA returned a choice with no text content",
                raw_excerpt=str(data)[:2000],
                provider=self.provider,
                model=self._config.model,
            )

        return (
            content,
            self._usage_from(data.get("usage")),
            str(choice.get("finish_reason") or ""),
        )

    # ── health ───────────────────────────────────────────────────────────────

    async def _probe_health(self) -> tuple[bool, dict[str, Any]]:
        """Ask the catalogue endpoint, not the model.

        A health check that runs an inference costs money and seconds on every
        poll. ``GET /models`` proves the three things that actually fail —
        endpoint reachable, credentials accepted, model catalogued — for free.
        """
        url = f"{self._config.endpoint_root}/models"
        response = await self._get(url, timeout=self._config.health_timeout_seconds)

        detail: dict[str, Any] = {
            "endpoint": url,
            "status_code": response.status_code,
            "credentials": "configured" if self._config.api_key else "missing",
        }

        if response.status_code in (401, 403):
            detail["reason"] = "credentials rejected"
            return False, detail
        if response.status_code >= 400:
            detail["reason"] = f"catalogue endpoint returned HTTP {response.status_code}"
            return False, detail

        try:
            body = response.json()
        except ValueError:
            detail["reason"] = "catalogue response was not JSON"
            return False, detail

        models = body.get("data") if isinstance(body, Mapping) else None
        if isinstance(models, list):
            served = {
                str(entry.get("id"))
                for entry in models
                if isinstance(entry, Mapping) and entry.get("id")
            }
            detail["catalogue_size"] = len(served)
            detail["model_listed"] = self._config.model in served
            if served and self._config.model not in served:
                # Reachable and authenticated, but this model is not in the
                # listing — a warning rather than a failure, because private NIM
                # deployments serve models the public catalogue never lists.
                detail["reason"] = "model not present in the catalogue listing"
        return True, detail

    # ── cost ─────────────────────────────────────────────────────────────────

    def estimate_cost(self, request: VLMExtractionRequest) -> CostEstimate:
        """Priced when the deployment configured prices, counted otherwise.

        No default price table: a hard-coded rate goes stale silently and an
        invented number in a budget decision is worse than an honest absence.
        """
        prompt_tokens = self._estimate_prompt_tokens(request)
        completion_tokens = request.prompt.max_output_tokens
        input_rate = float(self._config.extra.get("price_per_million_input_tokens", 0.0))
        output_rate = float(self._config.extra.get("price_per_million_output_tokens", 0.0))

        if input_rate <= 0 and output_rate <= 0:
            return CostEstimate(
                amount=0.0,
                currency="unpriced",
                estimated_prompt_tokens=prompt_tokens,
                estimated_completion_tokens=completion_tokens,
                basis=(
                    "nvidia: token estimate only — set "
                    "NVIDIA_PRICE_PER_MILLION_INPUT_TOKENS / "
                    "NVIDIA_PRICE_PER_MILLION_OUTPUT_TOKENS to price it"
                ),
            )

        amount = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
        return CostEstimate(
            amount=round(amount, 6),
            currency=str(self._config.extra.get("price_currency", "USD")),
            estimated_prompt_tokens=prompt_tokens,
            estimated_completion_tokens=completion_tokens,
            basis=(
                f"nvidia: {prompt_tokens} prompt + {completion_tokens} completion "
                f"tokens at configured rates"
            ),
        )


def build_nvidia_adapter(settings: Any, **kwargs: Any) -> NvidiaDocumentVLMAdapter:
    """Factory used by the registry. Reads every value from settings.

    Kept in this module so the registry never learns an NVIDIA-specific field
    name: adding a provider adds a factory, not a branch in shared code.
    """
    from app.document_platform.vlm.errors import DocumentVLMConfigurationError

    api_key = settings.nvidia_api_key.get_secret_value()
    if not api_key:
        raise DocumentVLMConfigurationError(
            "DOCUMENT_VLM_PROVIDER=nvidia requires NVIDIA_API_KEY to be set"
        )

    config = VLMAdapterConfig(
        base_url=settings.nvidia_base_url,
        model=settings.nvidia_model,
        api_key=api_key,
        timeout_seconds=settings.document_vlm_timeout_seconds,
        connect_timeout_seconds=settings.document_vlm_connect_timeout_seconds,
        max_retries=settings.document_vlm_max_retries,
        retry_backoff_seconds=settings.document_vlm_retry_backoff_seconds,
        max_output_tokens=settings.document_vlm_max_output_tokens,
        temperature=settings.document_vlm_temperature,
        health_timeout_seconds=settings.document_vlm_health_timeout_seconds,
        extra={
            "image_format": getattr(settings, "nvidia_image_format", IMAGE_FORMAT_URL),
            "max_inline_image_bytes": getattr(
                settings, "nvidia_max_inline_image_bytes", DEFAULT_MAX_INLINE_IMAGE_BYTES
            ),
            "max_images_per_request": getattr(
                settings, "nvidia_max_images_per_request", DEFAULT_MAX_IMAGES
            ),
            "price_per_million_input_tokens": getattr(
                settings, "nvidia_price_per_million_input_tokens", 0.0
            ),
            "price_per_million_output_tokens": getattr(
                settings, "nvidia_price_per_million_output_tokens", 0.0
            ),
        },
    )
    return NvidiaDocumentVLMAdapter(config, **kwargs)


def describe_nvidia_config(settings: Any) -> dict[str, Any]:
    """This provider's effective configuration, for the operator endpoint.

    Registered with the factory so the registry never learns an NVIDIA field
    name. The key is reported as *configured or not* — the only fact anybody
    debugging a 401 needs, and the only one safe to serve over HTTP.
    """
    api_key = getattr(settings, "nvidia_api_key", None)
    return {
        "base_url": getattr(settings, "nvidia_base_url", ""),
        "api_key_configured": bool(api_key and api_key.get_secret_value()),
        "image_format": getattr(settings, "nvidia_image_format", IMAGE_FORMAT_URL),
        "priced": bool(
            getattr(settings, "nvidia_price_per_million_input_tokens", 0.0)
            or getattr(settings, "nvidia_price_per_million_output_tokens", 0.0)
        ),
        "data_residency": "remote",
    }


__all__ = [
    "DEFAULT_MAX_INLINE_IMAGE_BYTES",
    "IMAGE_FORMAT_INLINE",
    "IMAGE_FORMAT_URL",
    "NvidiaDocumentVLMAdapter",
    "build_nvidia_adapter",
    "describe_nvidia_config",
]
