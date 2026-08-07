"""Document VLM error taxonomy — provider-neutral by construction.

Every failure a VLM adapter can produce is classified *here*, in the platform,
using vocabulary that says nothing about who failed: a 401 from NVIDIA and a
rejected bearer token from a future Claude Vision adapter are both
``DocumentVLMAuthError``. That is what lets the pipeline, the API layer and the
retry policy be written once and stay written when a provider is swapped.

Two properties carry the decisions:

``retryable``
    Whether another attempt could plausibly succeed. Explicit, never inferred
    from the message — a caller that has to pattern-match a string will
    eventually match the wrong one.

``http_status``
    What the API returns. Set on the class so the router maps outcomes by type
    rather than by a chain of ``isinstance`` guesses, and so an error that
    escapes the router still becomes a sane response through the existing
    ``AIAssistantError`` handler in ``app.main``.

Adapters never raise anything else across the port boundary, and never
fabricate a plausible extraction on failure — a fabricated invoice is
indistinguishable from a real one downstream, which makes it the single most
expensive failure mode this platform has.
"""

from __future__ import annotations

from typing import Any

from app.shared.exceptions import AIAssistantError


class DocumentVLMError(AIAssistantError):
    """Base for every failure reaching the platform through ``DocumentVLMPort``.

    Carries structured context so recovery logic and telemetry never parse a
    message string. ``context`` is redacted-by-construction: adapters put
    endpoints, status codes and durations here, never credentials.
    """

    http_status: int = 502
    code: str = "vlm_error"
    retryable: bool = False

    def __init__(
        self,
        message: str | None = None,
        *,
        provider: str = "",
        model: str = "",
        request_id: str = "",
        retry_after_seconds: float | None = None,
        **context: Any,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.request_id = request_id
        self.retry_after_seconds = retry_after_seconds
        self.context: dict[str, Any] = dict(context)

    def to_dict(self) -> dict[str, Any]:
        """The wire form. Contains no secret material by construction."""
        return {
            "code": self.code,
            "message": self.message,
            "provider": self.provider,
            "model": self.model,
            "retryable": self.retryable,
            **({"request_id": self.request_id} if self.request_id else {}),
            **(
                {"retry_after_seconds": self.retry_after_seconds}
                if self.retry_after_seconds is not None
                else {}
            ),
        }

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return (
            f"{type(self).__name__}({self.message!r}, provider={self.provider!r}, "
            f"code={self.code!r}, retryable={self.retryable})"
        )


# ── configuration ────────────────────────────────────────────────────────────


class DocumentVLMConfigurationError(DocumentVLMError):
    """The provider cannot be built from the environment as configured.

    An unknown ``DOCUMENT_VLM_PROVIDER``, a missing API key, an empty model
    name. 500 rather than 502: nothing upstream failed, the deployment is
    wrong, and retrying will not fix it.
    """

    http_status = 500
    code = "vlm_configuration_error"
    retryable = False


class DocumentVLMUnsupportedProviderError(DocumentVLMConfigurationError):
    """``DOCUMENT_VLM_PROVIDER`` names a provider nobody registered."""

    code = "vlm_unsupported_provider"


# ── transport / upstream ─────────────────────────────────────────────────────


class DocumentVLMAuthError(DocumentVLMError):
    """401/403 from the provider. Credentials are wrong, absent, or revoked.

    Never retried: a rejected key stays rejected, and repeating it is how an
    account gets rate-limited on top of being unauthenticated.
    """

    http_status = 502
    code = "vlm_auth_error"
    retryable = False


class DocumentVLMRateLimitError(DocumentVLMError):
    """429. Retryable, but only with backoff — ``retry_after_seconds`` when the
    provider said so."""

    http_status = 429
    code = "vlm_rate_limited"
    retryable = True


class DocumentVLMTimeoutError(DocumentVLMError):
    """The provider did not answer inside the configured budget."""

    http_status = 504
    code = "vlm_timeout"
    retryable = True


class DocumentVLMConnectionError(DocumentVLMError):
    """DNS, TLS, connection refused — the request never reached a model."""

    http_status = 502
    code = "vlm_connection_error"
    retryable = True


class DocumentVLMUpstreamError(DocumentVLMError):
    """5xx from the provider. Their side is unwell; a bounded retry is fair."""

    http_status = 502
    code = "vlm_upstream_error"
    retryable = True


class DocumentVLMBadRequestError(DocumentVLMError):
    """4xx that is not auth or rate limiting — our request was malformed.

    Not retryable: the same request will be rejected the same way. Typically a
    model name the provider does not serve, or an image it will not accept.
    """

    http_status = 502
    code = "vlm_bad_request"
    retryable = False


class DocumentVLMUnavailableError(DocumentVLMError):
    """The provider is reachable but cannot serve this model right now.

    Ollama with the model not pulled is the canonical case: the daemon answers,
    the model is absent, and telling the operator *that* is worth far more than
    a generic 502.
    """

    http_status = 503
    code = "vlm_unavailable"
    retryable = False


# ── response quality ─────────────────────────────────────────────────────────


class DocumentVLMInvalidResponseError(DocumentVLMError):
    """The provider answered, but not with something usable.

    A response envelope missing its content, or model text that survived neither
    parsing nor repair. Explicitly *not* retryable at the adapter level: the same
    prompt at temperature 0 produces the same unusable text, so retrying spends
    money to fail identically. ``raw_excerpt`` preserves a bounded piece of what
    was actually said, because a malformed answer is evidence and discarding it
    leaves nobody able to fix the prompt.
    """

    http_status = 502
    code = "vlm_invalid_response"
    retryable = False

    def __init__(
        self,
        message: str | None = None,
        *,
        raw_excerpt: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.raw_excerpt = raw_excerpt[:2000]

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        if self.raw_excerpt:
            payload["raw_excerpt"] = self.raw_excerpt
        return payload


class DocumentVLMRefusedError(DocumentVLMError):
    """The model declined to answer — safety filter, content policy.

    An explicit outcome recorded as such, never an empty success. A refusal
    reported as "no fields found" is a silent failure, and silent failures in an
    extraction pipeline surface as missing invoices weeks later.
    """

    http_status = 422
    code = "vlm_refused"
    retryable = False


# ── pipeline (platform-side, not provider failures) ──────────────────────────


class DocumentExtractionError(AIAssistantError):
    """Base for failures the pipeline owns rather than the provider."""

    http_status = 422
    code: str = "extraction_error"

    def __init__(self, message: str | None = None, **context: Any) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context)


class UnsupportedDocumentError(DocumentExtractionError):
    """The upload is not a document this pipeline can put in front of a VLM."""

    http_status = 415
    code = "unsupported_document"


class DocumentTooLargeError(DocumentExtractionError):
    """Above ``DOCUMENT_VLM_MAX_FILE_SIZE_MB``."""

    http_status = 413
    code = "document_too_large"


class EmptyDocumentError(DocumentExtractionError):
    """Zero bytes, or a document that yielded neither pixels nor text.

    Worth its own type: sending an empty payload to a VLM produces a confident
    hallucination, which is precisely the outcome this platform exists to avoid.
    """

    http_status = 422
    code = "empty_document"


class InvoiceSchemaError(DocumentExtractionError):
    """The model's JSON was well-formed but not an invoice.

    Distinct from ``DocumentVLMInvalidResponseError``: there the text was not
    JSON; here it is JSON that the invoice schema rejects.
    """

    http_status = 422
    code = "invoice_schema_error"

    def __init__(
        self,
        message: str | None = None,
        *,
        violations: tuple[str, ...] = (),
        **context: Any,
    ) -> None:
        super().__init__(message, **context)
        self.violations = violations
