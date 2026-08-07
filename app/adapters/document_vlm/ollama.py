"""Ollama local VLM adapter — ``DocumentVLMPort`` over the local Ollama REST API.

Same port, same DTOs, same errors, same telemetry as the NVIDIA adapter. The
only things that differ are the wire shape (``POST {base}/api/chat`` with
base64 images on the message rather than OpenAI content parts), where the token
counts live in the reply, and what "healthy" means — for a local daemon it means
*the model is actually pulled*, which is the failure operators hit constantly
and which a naive ping would report as fine.

``OLLAMA_BASE_URL`` and ``OLLAMA_MODEL`` are separate settings from the chat
models' ``OLLAMA_HOST``, so a deployment can run document vision on a GPU box
while chat stays on the app server, without either one moving.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from app.adapters.document_vlm.base import HttpDocumentVLMAdapter, VLMAdapterConfig
from app.document_platform.vlm.errors import (
    DocumentVLMError,
    DocumentVLMInvalidResponseError,
    DocumentVLMUnavailableError,
)
from app.document_platform.vlm.ports import (
    CostEstimate,
    TokenUsage,
    VLMExtractionRequest,
)

#: Ollama's answer when a model has never been pulled. Worth detecting by hand:
#: it arrives as a 404, which would otherwise be classified as "we sent a bad
#: request" when in fact the request was fine and the machine is not ready.
_MODEL_MISSING_MARKERS = ("not found", "no such model", "try pulling")


class OllamaDocumentVLMAdapter(HttpDocumentVLMAdapter):
    """Locally hosted VLM behind ``DocumentVLMPort``."""

    provider = "ollama"

    # ── request ──────────────────────────────────────────────────────────────

    def _endpoint(self) -> str:
        return f"{self._config.endpoint_root}/api/chat"

    def _headers(self) -> dict[str, str]:
        # A local daemon has no credentials to leak. The header is still built
        # here rather than assumed away, because a deployment fronting Ollama
        # with an authenticating proxy is a normal thing to do.
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers

    def _body(self, request: VLMExtractionRequest) -> dict[str, Any]:
        prompt = request.prompt
        messages: list[dict[str, Any]] = []
        if prompt.system.strip():
            messages.append({"role": "system", "content": prompt.system})

        user: dict[str, Any] = {"role": "user", "content": prompt.user}
        if request.payload.images:
            user["images"] = [self._b64(image) for image in request.payload.images]
        messages.append(user)

        options: dict[str, Any] = {
            "temperature": prompt.temperature,
            "num_predict": prompt.max_output_tokens,
        }
        num_ctx = self._config.extra.get("num_ctx")
        if num_ctx:
            options["num_ctx"] = int(num_ctx)

        return {
            "model": self._config.model,
            "messages": messages,
            "stream": False,
            # Ollama's structured-output switch: a bare "json" constrains the
            # decoder to valid JSON, and a schema constrains it to *this* JSON.
            # Either way the platform still validates — a constrained decoder
            # guarantees shape, never truth.
            "format": dict(prompt.response_schema) if prompt.response_schema else "json",
            "options": options,
        }

    # ── response ─────────────────────────────────────────────────────────────

    def _read_response(self, data: Mapping[str, Any]) -> tuple[str, TokenUsage, str]:
        message = data.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None

        if not isinstance(content, str) or not content.strip():
            # Ollama reports some failures with HTTP 200 and an "error" key.
            error = data.get("error")
            if isinstance(error, str) and error:
                raise self._error_for_message(error)
            raise DocumentVLMInvalidResponseError(
                "Ollama returned a response with no message content",
                raw_excerpt=str(data)[:2000],
                provider=self.provider,
                model=self._config.model,
            )

        usage = TokenUsage(
            prompt_tokens=_int_or_none(data.get("prompt_eval_count")),
            completion_tokens=_int_or_none(data.get("eval_count")),
            total_tokens=_sum_or_none(
                data.get("prompt_eval_count"), data.get("eval_count")
            ),
        )
        return content, usage, str(data.get("done_reason") or "")

    # ── classification ───────────────────────────────────────────────────────

    def _classify(self, response: httpx.Response) -> DocumentVLMError:
        """404 from a reachable daemon usually means "model not pulled"."""
        if response.status_code == 404:
            detail = self._error_detail(response)
            if any(marker in detail.lower() for marker in _MODEL_MISSING_MARKERS):
                return DocumentVLMUnavailableError(
                    f"Ollama does not have model '{self._config.model}'; pull it "
                    f"with `ollama pull {self._config.model}`",
                    provider=self.provider,
                    model=self._config.model,
                    status_code=404,
                )
        return super()._classify(response)

    def _error_for_message(self, error: str) -> DocumentVLMError:
        if any(marker in error.lower() for marker in _MODEL_MISSING_MARKERS):
            return DocumentVLMUnavailableError(
                f"Ollama does not have model '{self._config.model}'; pull it with "
                f"`ollama pull {self._config.model}`",
                provider=self.provider,
                model=self._config.model,
            )
        return DocumentVLMInvalidResponseError(
            f"Ollama reported an error: {error[:300]}",
            raw_excerpt=error,
            provider=self.provider,
            model=self._config.model,
        )

    # ── health ───────────────────────────────────────────────────────────────

    async def _probe_health(self) -> tuple[bool, dict[str, Any]]:
        """Daemon reachable *and* the configured model present.

        Both halves matter, and they fail independently: a running daemon
        without the model produces a 404 on the first real request, hours after
        a green health check said everything was fine.
        """
        url = f"{self._config.endpoint_root}/api/tags"
        response = await self._get(url, timeout=self._config.health_timeout_seconds)

        detail: dict[str, Any] = {"endpoint": url, "status_code": response.status_code}
        if response.status_code >= 400:
            detail["reason"] = f"Ollama returned HTTP {response.status_code}"
            return False, detail

        try:
            body = response.json()
        except ValueError:
            detail["reason"] = "model listing was not JSON"
            return False, detail

        entries = body.get("models") if isinstance(body, Mapping) else None
        installed = {
            str(entry.get("name") or entry.get("model") or "")
            for entry in entries or []
            if isinstance(entry, Mapping)
        }
        detail["models_installed"] = len(installed)
        detail["model_present"] = self._model_present(installed)

        if not detail["model_present"]:
            detail["reason"] = (
                f"model '{self._config.model}' is not pulled on this host; run "
                f"`ollama pull {self._config.model}`"
            )
            return False, detail
        return True, detail

    def _model_present(self, installed: set[str]) -> bool:
        """``qwen2.5vl:7b`` matches ``qwen2.5vl:7b``; a bare name matches ``:latest``."""
        wanted = self._config.model
        if wanted in installed:
            return True
        if ":" not in wanted and f"{wanted}:latest" in installed:
            return True
        return False

    # ── cost ─────────────────────────────────────────────────────────────────

    def estimate_cost(self, request: VLMExtractionRequest) -> CostEstimate:
        """Free at the margin, and honest about what "free" means.

        Local inference has a real cost in GPU seconds and electricity; what it
        does not have is a per-call price, and reporting a fabricated one would
        make the cloud/local comparison meaningless. Tokens are still estimated
        so a budget policy has the same shape of number from either provider.
        """
        return CostEstimate(
            amount=0.0,
            currency="none",
            estimated_prompt_tokens=self._estimate_prompt_tokens(request),
            estimated_completion_tokens=request.prompt.max_output_tokens,
            basis="ollama: local inference, no per-call monetary cost",
        )


def _int_or_none(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def _sum_or_none(*values: Any) -> int | None:
    numbers = [v for v in values if isinstance(v, int | float)]
    return int(sum(numbers)) if numbers else None


def build_ollama_adapter(settings: Any, **kwargs: Any) -> OllamaDocumentVLMAdapter:
    """Factory used by the registry. Reads every value from settings."""
    config = VLMAdapterConfig(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        api_key="",
        timeout_seconds=settings.document_vlm_timeout_seconds,
        connect_timeout_seconds=settings.document_vlm_connect_timeout_seconds,
        max_retries=settings.document_vlm_max_retries,
        retry_backoff_seconds=settings.document_vlm_retry_backoff_seconds,
        max_output_tokens=settings.document_vlm_max_output_tokens,
        temperature=settings.document_vlm_temperature,
        health_timeout_seconds=settings.document_vlm_health_timeout_seconds,
        extra={"num_ctx": getattr(settings, "ollama_num_ctx", 0)},
    )
    return OllamaDocumentVLMAdapter(config, **kwargs)


def describe_ollama_config(settings: Any) -> dict[str, Any]:
    """This provider's effective configuration, for the operator endpoint.

    ``data_residency: local`` is the field a regulated site reads before
    deciding a document may be processed at all — the reason a local provider
    exists next to a cloud one.
    """
    return {
        "base_url": getattr(settings, "ollama_base_url", ""),
        "api_key_configured": False,
        "num_ctx": getattr(settings, "ollama_num_ctx", 0),
        "priced": False,
        "data_residency": "local",
    }


__all__ = [
    "OllamaDocumentVLMAdapter",
    "build_ollama_adapter",
    "describe_ollama_config",
]
