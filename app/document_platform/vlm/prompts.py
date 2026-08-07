"""Prompt management — versioned, outside the adapters, owned by the platform.

An extraction prompt hard-coded inside an adapter has three properties, all
bad: it has no version, so a change to it is invisible in every record it
produced; it is duplicated per provider, so NVIDIA and Ollama drift apart until
they are no longer the same experiment; and improving it means editing
infrastructure code, which is where the wording of a business question has no
business living.

So prompts live here. Adapters receive an ``ExtractionPrompt`` and send it. They
never compose one, never append to one, and never "helpfully" prepend a system
message of their own — port obligation V5.

Versioning is by explicit registration. A new wording is a new version
registered alongside the old, selected by ``DOCUMENT_VLM_PROMPT_VERSION``, which
makes a prompt rollback an environment change rather than a deploy, and makes
A/B comparison possible at all: both versions exist simultaneously, and every
extraction records which one answered.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.document_platform.vlm.errors import DocumentVLMConfigurationError
from app.document_platform.vlm.invoice_schema import (
    INVOICE_SCHEMA_VERSION,
    InvoiceSchemaValidator,
)
from app.document_platform.vlm.ports import DocumentPayload, ExtractionPrompt

INVOICE_EXTRACTION_PROMPT_ID = "invoice.extract"

DEFAULT_PROMPT_VERSION = "1.0.0"

#: How much OCR text is worth sending. Beyond this a model's attention is spread
#: thinner than the extra pages are worth, and the tail of a long document is
#: rarely where the invoice header lives. Truncation is *reported* in the
#: prompt, never silent — a model that knows it is seeing a fragment says so.
DEFAULT_MAX_TEXT_CHARS = 24_000


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """One version of one prompt.

    ``user_template`` is rendered with ``str.format`` against a small, fixed set
    of names, so a template is data rather than code and could move to a file or
    a database later without touching anything that consumes it.
    """

    prompt_id: str
    version: str
    system: str
    user_template: str
    notes: str = ""

    def render(self, **context: Any) -> str:
        try:
            return self.user_template.format(**context)
        except KeyError as exc:  # pragma: no cover - registration-time mistake
            raise DocumentVLMConfigurationError(
                f"prompt '{self.prompt_id}@{self.version}' references unknown "
                f"placeholder {exc}"
            ) from exc


@runtime_checkable
class PromptProvider(Protocol):
    """The seam the pipeline depends on. **Not a port** — a module boundary.

    The pipeline consumes prompts and never creates them. Anything that can
    produce a versioned ``ExtractionPrompt`` from a payload is substitutable
    here, including a future database-backed provider.
    """

    def build(self, payload: DocumentPayload, **options: Any) -> ExtractionPrompt: ...

    def versions(self) -> tuple[str, ...]: ...


# ── v1.0.0 ───────────────────────────────────────────────────────────────────

_V1_SYSTEM = (
    "You are a precise document data extraction engine. You read invoices and "
    "return structured JSON.\n"
    "\n"
    "Rules you must follow exactly:\n"
    "1. Return a single JSON object and nothing else — no prose, no markdown "
    "fences, no explanation before or after.\n"
    "2. Copy values from the document. Never infer, never estimate, never "
    "complete a value from what an invoice usually says.\n"
    "3. Use null for anything the document does not state. A null is a correct "
    "answer; a plausible guess is not.\n"
    "4. Numbers must be JSON numbers with no currency symbols and no thousands "
    "separators. Keep the decimals exactly as printed.\n"
    "5. Dates must be YYYY-MM-DD. If a date is ambiguous, copy it as printed "
    "rather than guessing the order of day and month.\n"
    "6. Currency must be the ISO 4217 code (SGD, USD, EUR, ...) when the "
    "document makes it unambiguous; otherwise null.\n"
    "7. Include every line item you can read, in the order they appear.\n"
    "8. If the document is not an invoice, return the same JSON object with "
    "document_type set to what it actually is and every other field null."
)

_V1_USER = """Extract the invoice data from this document.

Return JSON with exactly this shape:

{schema}

{sources}
Return only the JSON object."""


_INVOICE_SHAPE_V1 = """{
  "document_type": "invoice",
  "invoice_number": string | null,
  "purchase_order_number": string | null,
  "invoice_date": "YYYY-MM-DD" | null,
  "due_date": "YYYY-MM-DD" | null,
  "currency": "ISO 4217 code" | null,
  "supplier": {
    "name": string | null,
    "address": string | null,
    "tax_id": string | null,
    "registration_number": string | null,
    "email": string | null,
    "phone": string | null
  },
  "customer": {
    "name": string | null,
    "address": string | null,
    "tax_id": string | null,
    "registration_number": string | null,
    "email": string | null,
    "phone": string | null
  },
  "line_items": [
    {
      "line_number": number | null,
      "description": string | null,
      "product_code": string | null,
      "quantity": number | null,
      "unit": string | null,
      "unit_price": number | null,
      "discount": number | null,
      "tax_rate": number | null,
      "tax_amount": number | null,
      "amount": number | null
    }
  ],
  "totals": {
    "subtotal": number | null,
    "discount_total": number | null,
    "tax_total": number | null,
    "shipping_total": number | null,
    "grand_total": number | null,
    "amount_paid": number | null,
    "amount_due": number | null
  },
  "payment_terms": string | null,
  "payment_reference": string | null,
  "bank_details": string | null,
  "notes": string | null
}"""


INVOICE_PROMPT_V1 = PromptTemplate(
    prompt_id=INVOICE_EXTRACTION_PROMPT_ID,
    version="1.0.0",
    system=_V1_SYSTEM,
    user_template=_V1_USER,
    notes="Baseline. Shape-by-example rather than JSON Schema: smaller models "
    "follow an example far more reliably than a schema document.",
)


class InvoiceExtractionPromptProvider:
    """Produces the system and user prompts for invoice extraction.

    Stateless and deterministic: the same payload and version produce
    byte-identical prompts, which is what makes a replay a replay.
    """

    prompt_id = INVOICE_EXTRACTION_PROMPT_ID
    schema_version = INVOICE_SCHEMA_VERSION

    def __init__(
        self,
        *,
        version: str = DEFAULT_PROMPT_VERSION,
        templates: Mapping[str, PromptTemplate] | None = None,
        max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
        max_output_tokens: int = 4096,
        temperature: float = 0.0,
        include_json_schema: bool = False,
    ) -> None:
        self._templates: dict[str, PromptTemplate] = dict(
            templates if templates is not None else {"1.0.0": INVOICE_PROMPT_V1}
        )
        if version not in self._templates:
            raise DocumentVLMConfigurationError(
                f"DOCUMENT_VLM_PROMPT_VERSION='{version}' is not registered; "
                f"available versions are {', '.join(sorted(self._templates)) or 'none'}"
            )
        self._version = version
        self._max_text_chars = max(0, max_text_chars)
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._include_json_schema = include_json_schema

    # ── introspection ────────────────────────────────────────────────────────

    def versions(self) -> tuple[str, ...]:
        return tuple(sorted(self._templates))

    @property
    def version(self) -> str:
        return self._version

    def register(self, template: PromptTemplate) -> None:
        """Add a version. Existing versions are never overwritten.

        A mutable prompt version is a version that means nothing: two records
        pinned to ``1.0.0`` must have been produced by the same words, or
        provenance is decoration.
        """
        if template.version in self._templates:
            raise DocumentVLMConfigurationError(
                f"prompt version '{template.version}' is already registered; "
                f"a new wording is a new version, never an edit to an old one"
            )
        self._templates[template.version] = template

    # ── rendering ────────────────────────────────────────────────────────────

    def build(
        self,
        payload: DocumentPayload,
        *,
        version: str | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ExtractionPrompt:
        """Render the prompt for one payload."""
        chosen = version or self._version
        template = self._templates.get(chosen)
        if template is None:
            raise DocumentVLMConfigurationError(
                f"prompt version '{chosen}' is not registered for "
                f"'{self.prompt_id}'; available: {', '.join(self.versions())}"
            )

        user = template.render(
            schema=_INVOICE_SHAPE_V1,
            sources=self._sources_block(payload),
        )

        return ExtractionPrompt(
            system=template.system,
            user=user,
            prompt_id=template.prompt_id,
            version=template.version,
            response_schema=(
                InvoiceSchemaValidator.json_schema() if self._include_json_schema else None
            ),
            max_output_tokens=(
                self._max_output_tokens if max_output_tokens is None else max_output_tokens
            ),
            temperature=self._temperature if temperature is None else temperature,
        )

    # ── internals ────────────────────────────────────────────────────────────

    def _sources_block(self, payload: DocumentPayload) -> str:
        """Describe what the model is being given, and how much of it.

        A model that is shown OCR text without being told it is OCR treats
        garbled characters as the document's own wording. Saying where the text
        came from — and admitting when it has been truncated — costs a sentence
        and prevents a whole class of confident misreadings.
        """
        parts: list[str] = []

        if payload.has_images:
            pages = len(payload.images)
            parts.append(
                f"You are given {pages} page image{'s' if pages != 1 else ''} of the "
                f"document. The images are the authority: read values from them."
            )

        if payload.has_text:
            text = payload.ocr_text.strip()
            truncated = len(text) > self._max_text_chars
            if truncated:
                text = text[: self._max_text_chars]
            origin = {
                "pdf_text_layer": "the PDF's embedded text layer",
                "ocr": "OCR of the document",
            }.get(payload.text_source, "the document")
            caveat = (
                " It is truncated to the first part of the document."
                if truncated
                else ""
            )
            authority = (
                " Where the text and the images disagree, trust the images."
                if payload.has_images
                else " OCR can misread characters; if a value looks implausible, "
                "copy what is written rather than correcting it."
            )
            parts.append(
                f"Text extracted from {origin} follows.{caveat}{authority}\n"
                f"--- BEGIN DOCUMENT TEXT ---\n{text}\n--- END DOCUMENT TEXT ---"
            )

        return "\n\n".join(parts) + ("\n\n" if parts else "")

    def describe(self) -> dict[str, Any]:
        """Provenance for observability and for the API's response envelope."""
        return {
            "prompt_id": self.prompt_id,
            "version": self._version,
            "available_versions": list(self.versions()),
            "schema_version": self.schema_version,
            "max_text_chars": self._max_text_chars,
        }

    def as_json(self) -> str:  # pragma: no cover - operator convenience
        return json.dumps(self.describe(), indent=2)


__all__ = [
    "DEFAULT_MAX_TEXT_CHARS",
    "DEFAULT_PROMPT_VERSION",
    "INVOICE_EXTRACTION_PROMPT_ID",
    "INVOICE_PROMPT_V1",
    "InvoiceExtractionPromptProvider",
    "PromptProvider",
    "PromptTemplate",
]
