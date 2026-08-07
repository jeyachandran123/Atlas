"""``DocumentVLMPort`` — the only way the Document Platform reaches a VLM.

The platform knows this file and nothing beyond it. There is no NVIDIA here, no
Ollama, no Claude, no Gemini, no OpenAI, no Qwen — and there never will be,
because the moment a provider name appears in the platform the substitution
stops being free and every future provider costs a change to business logic.

Same shape as the ports the rest of UnityWorks already runs on
(``ReasoningEnginePort``, ``UnderstandingPort``, ``GenerationPort``): a
``runtime_checkable`` ``Protocol`` over frozen DTOs, so an adapter conforms
structurally, a test double conforms without inheriting anything, and
conformance is assertable at binding time rather than discoverable in
production.

### Semantic contract

An implementation of this port must honour all seven obligations. They are what
make two providers *interchangeable* rather than merely *both present*.

| # | Obligation |
|---|---|
| **V1** | Returns the model's structured output and the verbatim text it came from. Nothing else. |
| **V2** | **Never fabricates.** A timeout, refusal, or unparseable answer is a typed error — never a plausible empty invoice. |
| **V3** | Applies **no business interpretation**. It answers the prompt it was handed; it does not know what an invoice is, and it certainly does not know what an ERP wants. |
| **V4** | **Stateless across calls.** Two identical requests are independently answerable, or replay and caching both break. |
| **V5** | The prompt arrives in the request. An adapter that composes its own prompt has silently taken ownership of extraction quality. |
| **V6** | Cost is estimable **before** the call, so budget policy can decide. |
| **V7** | Credentials never appear in a return value, an error, a log line, or a telemetry record. |
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

DOCUMENT_VLM_PORT_VERSION = "1.0.0"


# ── inputs ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DocumentImage:
    """One rendered page or one uploaded image, as an adapter sees it.

    Note what is absent: no user, no org, no document id, no tenant. An adapter
    is handed pixels and a question, never a subject — which is what stops a
    provider from being able to accumulate anything about anyone.
    """

    data: bytes
    media_type: str
    page: int | None = None

    def __post_init__(self) -> None:
        if not self.data:
            raise ValueError("a document image with no bytes carries no information")
        if not self.media_type.startswith("image/"):
            raise ValueError(
                f"document image media type must be an image/*, got '{self.media_type}'"
            )

    @property
    def size_bytes(self) -> int:
        return len(self.data)


@dataclass(frozen=True, slots=True)
class DocumentPayload:
    """What the pipeline puts in front of the model: pixels, text, or both.

    Both are optional *individually* and required *together* — a payload with
    neither would ask a model to extract an invoice from nothing, and a model
    asked that will invent one rather than object (V2 exists because of exactly
    this failure).

    ``ocr_text`` is the output of the platform's existing OCR stage. It is
    passed alongside the pixels rather than instead of them: OCR is reliable
    about characters and blind to layout, a VLM is the reverse, and an invoice
    is a layout problem as much as a character one.
    """

    images: tuple[DocumentImage, ...] = ()
    ocr_text: str = ""
    filename: str = ""
    media_type: str = ""
    page_count: int = 0
    text_source: str = "none"
    """``pdf_text_layer`` | ``ocr`` | ``none`` — provenance of ``ocr_text``,
    recorded so a bad extraction can be traced to a bad text stage."""

    def __post_init__(self) -> None:
        if not self.images and not self.ocr_text.strip():
            raise ValueError(
                "a document payload must carry pixels, text, or both; a model "
                "given neither will produce a confident invoice from nothing"
            )

    @property
    def has_images(self) -> bool:
        return bool(self.images)

    @property
    def has_text(self) -> bool:
        return bool(self.ocr_text.strip())

    @property
    def total_image_bytes(self) -> int:
        return sum(image.size_bytes for image in self.images)


@dataclass(frozen=True, slots=True)
class ExtractionPrompt:
    """One rendered instruction, pinned to its version.

    Built by a prompt provider, never by an adapter (V5). It carries its own
    identity so every extraction can be attributed to the exact wording that
    produced it — which is the only way to tell a prompt regression from a model
    regression.
    """

    system: str
    user: str
    prompt_id: str
    version: str
    response_schema: Mapping[str, Any] | None = None
    """A JSON Schema for providers that support constrained decoding. Adapters
    that cannot honour it ignore it; the platform validates either way."""

    max_output_tokens: int = 4096
    temperature: float = 0.0

    def __post_init__(self) -> None:
        if not self.user.strip():
            raise ValueError(
                f"prompt '{self.prompt_id}' rendered to empty instructions; "
                f"a model asked nothing answers nothing"
            )
        if not self.prompt_id or not self.version:
            raise ValueError("a rendered prompt must carry its id and version")

    @property
    def pinned(self) -> str:
        return f"{self.prompt_id}@{self.version}"


@dataclass(frozen=True, slots=True)
class VLMExtractionRequest:
    """One document, one question, one correlation id."""

    payload: DocumentPayload
    prompt: ExtractionPrompt
    request_id: str = ""
    timeout_seconds: float | None = None
    """``None`` means the adapter's configured default. Present so a caller with
    a tighter budget than the deployment's can impose it per request."""

    metadata: Mapping[str, Any] = field(default_factory=dict)
    """Interpretation context for observability. Never business context, and
    never credentials."""


# ── outputs ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """What the call consumed, when the provider says so.

    Every field is optional because not every provider reports usage, and a
    zero that means "not reported" is a lie that shows up in a cost dashboard.
    """

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    @property
    def reported(self) -> bool:
        return any(
            value is not None
            for value in (self.prompt_tokens, self.completion_tokens, self.total_tokens)
        )

    def as_dict(self) -> dict[str, int | None]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True)
class VLMExtractionResult:
    """What an adapter returns: structured output plus the evidence for it.

    ``structured`` is the model's JSON, parsed and nothing more — not validated
    against any schema, not reshaped, not enriched. Validation is the platform's
    job (and knows what an invoice is); the adapter's job ends at "this is what
    the model said, as data".

    ``raw_text`` is preserved verbatim next to it because a structured result
    with its source discarded cannot be audited, and an extraction nobody can
    audit is an extraction nobody should act on.
    """

    structured: Mapping[str, Any]
    raw_text: str
    provider: str
    model: str
    latency_ms: float
    usage: TokenUsage = TokenUsage()
    request_id: str = ""
    retry_count: int = 0
    finish_reason: str = ""
    repaired: bool = False
    """The model's JSON needed repair before it parsed. Surfaced rather than
    hidden: a provider that routinely needs repair is a prompt problem, and this
    counter is how anyone finds out."""

    prompt_id: str = ""
    prompt_version: str = ""

    @property
    def truncated(self) -> bool:
        """The model stopped because it ran out of tokens, not because it was
        finished — so ``structured`` is a fragment of an answer, not an answer."""
        return self.finish_reason in {"length", "max_tokens"}


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """What a call would cost, before spending it (V6).

    ``currency`` of ``"none"`` with a zero amount is how a local provider says
    "free" without pretending to be priced. ``basis`` explains where the number
    came from, because an unexplained cost estimate gets either blindly trusted
    or blindly ignored.
    """

    amount: float = 0.0
    currency: str = "none"
    estimated_prompt_tokens: int = 0
    estimated_completion_tokens: int = 0
    basis: str = ""

    @property
    def is_free(self) -> bool:
        return self.amount == 0.0


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """Whether this provider can serve a request right now.

    ``detail`` carries provider-specific diagnosis (endpoint reachable, model
    present, HTTP status) in provider-neutral keys, so a health dashboard is
    written once. It never carries credentials (V7).
    """

    healthy: bool
    provider: str
    model: str
    latency_ms: float = 0.0
    detail: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""
    checked_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "provider": self.provider,
            "model": self.model,
            "latency_ms": round(self.latency_ms, 2),
            "detail": dict(self.detail),
            **({"error": self.error} if self.error else {}),
        }


# ── the port ─────────────────────────────────────────────────────────────────


@runtime_checkable
class DocumentVLMPort(Protocol):
    """Turn a document and a prompt into structured data.

    Implemented today by an NVIDIA cloud adapter and an Ollama local adapter;
    tomorrow by Claude Vision, Gemini Vision, OpenAI Vision or Qwen Cloud —
    with no change to anything that consumes this protocol.
    """

    def provider_name(self) -> str:
        """Stable identifier of the implementation (``"nvidia"``, ``"ollama"``).

        Reported on every response and every metric. It is a *label*, never a
        branch: platform code that switches on this value has re-coupled itself
        to the provider it was written to be free of.
        """
        ...

    def model_name(self) -> str:
        """The concrete model answering, exactly as the provider names it."""
        ...

    async def extract_document(
        self, request: VLMExtractionRequest
    ) -> VLMExtractionResult:
        """Answer one request, or raise a ``DocumentVLMError``. Never fabricates."""
        ...

    async def health(self) -> ProviderHealth:
        """Can this provider serve a request now? Never raises — an unhealthy
        provider is a *result*, and a health check that throws cannot be used by
        the thing that needs it most."""
        ...

    def estimate_cost(self, request: VLMExtractionRequest) -> CostEstimate:
        """What this request would cost, before it is spent (V6)."""
        ...


def is_document_vlm(candidate: object) -> bool:
    """Structural conformance check, for binding time and for tests.

    ``isinstance`` against a ``runtime_checkable`` Protocol verifies the methods
    exist, which is exactly the check that belongs at a plugin boundary: a
    provider that is missing ``estimate_cost`` should fail when it is bound, not
    when a budget policy first consults it.
    """
    return isinstance(candidate, DocumentVLMPort)


__all__ = [
    "DOCUMENT_VLM_PORT_VERSION",
    "CostEstimate",
    "DocumentImage",
    "DocumentPayload",
    "DocumentVLMPort",
    "ExtractionPrompt",
    "ProviderHealth",
    "TokenUsage",
    "VLMExtractionRequest",
    "VLMExtractionResult",
    "is_document_vlm",
]
