"""Document VLM — the platform half of the seam.

Everything here is provider-neutral. There is no NVIDIA in this package, no
Ollama, and no import that could introduce one: concrete adapters live in
``app.adapters.document_vlm`` and are bound by the composition root at the API
edge, so the dependency arrow points *from* infrastructure *to* the platform
and never the other way.

    app.api.v1.document_extraction   ← composition root: reads config, binds
              │                        the provider, injects the pipeline
              ├── app.adapters.document_vlm      (NVIDIA, Ollama, and next)
              └── app.document_platform.vlm      (port, prompts, schema,
                                                  pipeline — this package)

What that buys: adding Claude Vision, Gemini Vision, OpenAI Vision or Qwen
Cloud is a new module under ``app.adapters.document_vlm`` and one registration
call. No file in this package changes, and no business logic anywhere is
touched.
"""

from app.document_platform.vlm.errors import (
    DocumentExtractionError,
    DocumentTooLargeError,
    DocumentVLMAuthError,
    DocumentVLMBadRequestError,
    DocumentVLMConfigurationError,
    DocumentVLMConnectionError,
    DocumentVLMError,
    DocumentVLMInvalidResponseError,
    DocumentVLMRateLimitError,
    DocumentVLMRefusedError,
    DocumentVLMTimeoutError,
    DocumentVLMUnavailableError,
    DocumentVLMUnsupportedProviderError,
    DocumentVLMUpstreamError,
    EmptyDocumentError,
    InvoiceSchemaError,
    UnsupportedDocumentError,
)
from app.document_platform.vlm.invoice_schema import (
    INVOICE_SCHEMA_VERSION,
    InvoiceDocument,
    InvoiceLineItem,
    InvoiceParty,
    InvoiceSchemaValidator,
    InvoiceTotals,
    InvoiceValidationResult,
)
from app.document_platform.vlm.json_repair import JsonParseOutcome, parse_model_json
from app.document_platform.vlm.payload import DocumentPayloadBuilder, PayloadBuildReport
from app.document_platform.vlm.pipeline import DocumentExtractionPipeline, ExtractionOutcome
from app.document_platform.vlm.ports import (
    DOCUMENT_VLM_PORT_VERSION,
    CostEstimate,
    DocumentImage,
    DocumentPayload,
    DocumentVLMPort,
    ExtractionPrompt,
    ProviderHealth,
    TokenUsage,
    VLMExtractionRequest,
    VLMExtractionResult,
    is_document_vlm,
)
from app.document_platform.vlm.prompts import (
    INVOICE_EXTRACTION_PROMPT_ID,
    InvoiceExtractionPromptProvider,
    PromptProvider,
    PromptTemplate,
)

__all__ = [
    "DOCUMENT_VLM_PORT_VERSION",
    "INVOICE_EXTRACTION_PROMPT_ID",
    "INVOICE_SCHEMA_VERSION",
    "CostEstimate",
    "DocumentExtractionError",
    "DocumentExtractionPipeline",
    "DocumentImage",
    "DocumentPayload",
    "DocumentPayloadBuilder",
    "DocumentTooLargeError",
    "DocumentVLMAuthError",
    "DocumentVLMBadRequestError",
    "DocumentVLMConfigurationError",
    "DocumentVLMConnectionError",
    "DocumentVLMError",
    "DocumentVLMInvalidResponseError",
    "DocumentVLMPort",
    "DocumentVLMRateLimitError",
    "DocumentVLMRefusedError",
    "DocumentVLMTimeoutError",
    "DocumentVLMUnavailableError",
    "DocumentVLMUnsupportedProviderError",
    "DocumentVLMUpstreamError",
    "EmptyDocumentError",
    "ExtractionOutcome",
    "ExtractionPrompt",
    "InvoiceDocument",
    "InvoiceExtractionPromptProvider",
    "InvoiceLineItem",
    "InvoiceParty",
    "InvoiceSchemaError",
    "InvoiceSchemaValidator",
    "InvoiceTotals",
    "InvoiceValidationResult",
    "JsonParseOutcome",
    "PayloadBuildReport",
    "PromptProvider",
    "PromptTemplate",
    "ProviderHealth",
    "TokenUsage",
    "UnsupportedDocumentError",
    "VLMExtractionRequest",
    "VLMExtractionResult",
    "is_document_vlm",
    "parse_model_json",
]
