"""Wire contract for the Document Extraction API.

Field names are camelCase on the wire and snake_case in Python, via aliases —
the consumers are ERP integrations, and an ERP that has to remember which of two
conventions this one endpoint uses is an ERP whose integration breaks on a
Friday.

The envelope is provider-shaped only in its *labels*: ``provider`` and ``model``
are reported so an operator can attribute a result, never so a client can branch
on them. A client that changes behaviour based on ``provider`` has coupled
itself to a deployment detail that is expected to change.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Camel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class TokenUsageOut(_Camel):
    prompt_tokens: int | None = Field(None, alias="promptTokens")
    completion_tokens: int | None = Field(None, alias="completionTokens")
    total_tokens: int | None = Field(None, alias="totalTokens")


class DocumentInfoOut(_Camel):
    """What actually reached the model. The difference between "the model missed
    it" and "the page was never sent"."""

    filename: str = ""
    media_type: str = Field("", alias="mediaType")
    page_count: int = Field(0, alias="pageCount")
    images_sent: int = Field(0, alias="imagesSent")
    text_source: str = Field("none", alias="textSource")
    text_chars: int = Field(0, alias="textChars")
    ocr_provider: str = Field("none", alias="ocrProvider")
    ocr_performed: bool = Field(False, alias="ocrPerformed")


class ExtractionResponse(_Camel):
    """The success envelope required of this endpoint."""

    success: bool = True
    provider: str
    model: str
    processing_time: float = Field(
        ..., alias="processingTime", description="End-to-end pipeline time in milliseconds"
    )
    data: dict[str, Any] = Field(default_factory=dict)

    request_id: str = Field("", alias="requestId")
    prompt_version: str = Field("", alias="promptVersion")
    schema_version: str = Field("", alias="schemaVersion")
    warnings: list[str] = Field(default_factory=list)
    usage: TokenUsageOut = Field(default_factory=TokenUsageOut)
    retry_count: int = Field(0, alias="retryCount")
    json_repaired: bool = Field(False, alias="jsonRepaired")
    stages: dict[str, float] = Field(default_factory=dict)
    document: DocumentInfoOut = Field(default_factory=DocumentInfoOut)


class ExtractionErrorDetail(_Camel):
    code: str
    message: str
    retryable: bool = False
    violations: list[str] = Field(default_factory=list)


class ExtractionErrorResponse(_Camel):
    """The failure envelope. Same top-level shape as success, so a client can
    read ``success`` before anything else and never has to guess."""

    success: bool = False
    provider: str = ""
    model: str = ""
    processing_time: float = Field(0.0, alias="processingTime")
    request_id: str = Field("", alias="requestId")
    error: ExtractionErrorDetail


class ProviderHealthOut(_Camel):
    healthy: bool
    provider: str
    model: str
    latency_ms: float = Field(0.0, alias="latencyMs")
    detail: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class ProviderInfoOut(_Camel):
    """Configuration as an operator should see it. Never a credential."""

    provider: str
    model: str
    available_providers: list[str] = Field(default_factory=list, alias="availableProviders")
    base_url: str = Field("", alias="baseUrl")
    api_key_configured: bool = Field(False, alias="apiKeyConfigured")
    prompt_id: str = Field("", alias="promptId")
    prompt_version: str = Field("", alias="promptVersion")
    available_prompt_versions: list[str] = Field(
        default_factory=list, alias="availablePromptVersions"
    )
    schema_version: str = Field("", alias="schemaVersion")
    port_version: str = Field("", alias="portVersion")
    limits: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "DocumentInfoOut",
    "ExtractionErrorDetail",
    "ExtractionErrorResponse",
    "ExtractionResponse",
    "ProviderHealthOut",
    "ProviderInfoOut",
    "TokenUsageOut",
]
