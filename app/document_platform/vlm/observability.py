"""Telemetry for VLM calls — everything worth knowing, no credentials, ever.

Recorded per call: provider, model, prompt version, latency (whole call and per
stage), token usage when the provider reports it, retry count, JSON-repair
count, outcome and error class, and the correlation id that ties all of it back
to one HTTP request.

Not recorded, at any level, under any log setting: API keys, bearer tokens,
authorization headers, or query strings that might carry them. ``redact()``
below is the single chokepoint, and every structure that leaves this module for
a log line or a metric label passes through it. Port obligation V7 is enforced
here rather than trusted to each adapter's discipline.

Metric *labels* are deliberately low-cardinality — provider, model, outcome,
error code. Request ids and filenames go in the log line, never in a label: a
metric with unbounded cardinality takes a Prometheus down, which is a strange
way to improve observability.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from prometheus_client import REGISTRY, Counter, Histogram

# ── redaction ────────────────────────────────────────────────────────────────

#: Word-parts whose presence in a key name means the *value* is never safe to
#: record, however the key is spelled.
#:
#: Matched against the key split into words rather than as a substring, because
#: a substring match on ``token`` also redacts ``prompt_tokens`` — and a
#: telemetry pipeline that reports every token count as ``***redacted***`` is
#: one nobody can use to explain a bill.
_SECRET_WORDS = frozenset(
    {
        "key", "apikey", "secret", "token", "password", "passwd", "pwd",
        "credential", "credentials", "authorization", "auth", "bearer", "cookie",
        "signature", "sig",
    }
)

#: Splits ``nvidia_api_key``, ``apiKey``, ``API-KEY`` and ``Authorization`` into
#: comparable words.
_WORD_SPLIT = re.compile(r"[^A-Za-z0-9]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

#: Values that look like credentials regardless of the key they arrived under —
#: NVIDIA's ``nvapi-…``, an OpenAI-style ``sk-…``, a bearer header, a JWT.
_SECRET_VALUE = re.compile(
    r"(nvapi-[\w-]{8,}|sk-[\w-]{16,}|Bearer\s+[\w.\-]{8,}|eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,})",
    re.IGNORECASE,
)

REDACTED = "***redacted***"


def _is_secret_key(key: Any) -> bool:
    """Whether a key name means "the value here is a credential".

    Word-wise rather than substring: ``api_key`` and ``apiKey`` are secrets,
    ``prompt_tokens`` and ``total_tokens`` are measurements, and a redactor that
    cannot tell them apart destroys the telemetry it was added to protect.
    """
    spaced = _CAMEL_BOUNDARY.sub("_", str(key))
    return any(part.lower() in _SECRET_WORDS for part in _WORD_SPLIT.split(spaced) if part)


def _is_scalar_fact(value: Any) -> bool:
    """Whether a value is a number, flag or absence — never a credential.

    ``api_key_configured: true`` is the fact an operator needs and the fact a
    key-shaped name would otherwise destroy. A secret is text; a boolean is an
    answer *about* a secret.
    """
    return value is None or isinstance(value, bool | int | float)


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Return ``value`` with anything credential-shaped removed.

    Recursive over mappings and sequences, bounded in depth so a cyclic or
    pathological structure cannot turn a log line into an outage.
    """
    if _depth > 6:
        return REDACTED
    if isinstance(value, Mapping):
        return {
            key: (
                REDACTED
                if _is_secret_key(key) and not _is_scalar_fact(item)
                else redact(item, _depth=_depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(item, _depth=_depth + 1) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub(REDACTED, value)
    return value


def safe_url(url: str) -> str:
    """An endpoint without its query string.

    Some providers accept credentials as query parameters. Logging a bare URL is
    how one ends up in an aggregator that a hundred people can read.
    """
    cleaned = _SECRET_VALUE.sub(REDACTED, url or "")
    return cleaned.split("?", 1)[0]


# ── metrics ──────────────────────────────────────────────────────────────────


def _counter(name: str, documentation: str, labels: tuple[str, ...]) -> Any:
    """Register a counter, or return the one already registered.

    Module-level metric definitions blow up on re-import (a test that reloads
    the module, a worker that imports it twice). Reusing the existing collector
    keeps that from being an error nobody can fix from the call site.
    """
    try:
        return Counter(name, documentation, labels)
    except ValueError:  # pragma: no cover - only on duplicate registration
        existing = getattr(REGISTRY, "_names_to_collectors", {}).get(name)
        return existing if existing is not None else _NullMetric()


def _histogram(
    name: str, documentation: str, labels: tuple[str, ...], buckets: tuple[float, ...]
) -> Any:
    try:
        return Histogram(name, documentation, labels, buckets=buckets)
    except ValueError:  # pragma: no cover - only on duplicate registration
        existing = getattr(REGISTRY, "_names_to_collectors", {}).get(name)
        return existing if existing is not None else _NullMetric()


class _NullMetric:  # pragma: no cover - defensive fallback
    """Absorbs metric calls when registration is impossible. Never raises."""

    def labels(self, *_: Any, **__: Any) -> _NullMetric:
        return self

    def inc(self, *_: Any, **__: Any) -> None:
        return None

    def observe(self, *_: Any, **__: Any) -> None:
        return None


vlm_requests_total = _counter(
    "document_vlm_requests_total",
    "VLM extraction calls by provider, model and outcome",
    ("provider", "model", "outcome", "error_code"),
)

vlm_latency_seconds = _histogram(
    "document_vlm_latency_seconds",
    "End-to-end latency of a VLM extraction call",
    ("provider", "model"),
    # A local 7B model answers in seconds; a cold cloud call with eight pages
    # can take a minute. Buckets span both, or the p95 is meaningless for one.
    (0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)

vlm_retries_total = _counter(
    "document_vlm_retries_total",
    "Retried VLM attempts, by the failure class that caused the retry",
    ("provider", "model", "reason"),
)

vlm_tokens_total = _counter(
    "document_vlm_tokens_total",
    "Tokens reported by the provider (absent for providers that do not report)",
    ("provider", "model", "kind"),
)

vlm_json_repairs_total = _counter(
    "document_vlm_json_repairs_total",
    "Model responses that needed JSON repair before they parsed",
    ("provider", "model", "strategy"),
)

document_extractions_total = _counter(
    "document_extractions_total",
    "Document extraction pipeline runs by document type and outcome",
    ("document_type", "provider", "outcome"),
)

extraction_stage_seconds = _histogram(
    "document_extraction_stage_seconds",
    "Duration of one extraction pipeline stage",
    ("stage", "provider"),
    (0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
)


# ── records ──────────────────────────────────────────────────────────────────


@dataclass
class VLMCallRecord:
    """One call to a provider, as it will be logged and counted.

    Mutable while the call is in flight, then emitted once. The adapter fills
    what it knows; the pipeline fills the rest.
    """

    provider: str
    model: str
    request_id: str = ""
    prompt_id: str = ""
    prompt_version: str = ""
    outcome: str = "success"
    error_code: str = ""
    latency_ms: float = 0.0
    retry_count: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    json_strategy: str = ""
    json_repaired: bool = False
    finish_reason: str = ""
    image_count: int = 0
    image_bytes: int = 0
    text_chars: int = 0
    endpoint: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def as_log_fields(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "request_id": self.request_id,
            "prompt": f"{self.prompt_id}@{self.prompt_version}" if self.prompt_id else "",
            "outcome": self.outcome,
            "latency_ms": round(self.latency_ms, 2),
            "retry_count": self.retry_count,
            "image_count": self.image_count,
            "image_bytes": self.image_bytes,
            "text_chars": self.text_chars,
            "endpoint": safe_url(self.endpoint),
        }
        if self.error_code:
            payload["error_code"] = self.error_code
        if self.finish_reason:
            payload["finish_reason"] = self.finish_reason
        if self.json_strategy:
            payload["json_strategy"] = self.json_strategy
            payload["json_repaired"] = self.json_repaired
        for name, value in (
            ("prompt_tokens", self.prompt_tokens),
            ("completion_tokens", self.completion_tokens),
            ("total_tokens", self.total_tokens),
        ):
            if value is not None:
                payload[name] = value
        if self.context:
            payload.update(redact(self.context))
        return redact(payload)


def record_vlm_call(record: VLMCallRecord) -> None:
    """Emit one call's telemetry to logs and metrics. Never raises.

    Telemetry that can fail a request is worse than no telemetry: an extraction
    that succeeded must not be reported as failed because a counter was
    unhappy.
    """
    try:
        vlm_requests_total.labels(
            provider=record.provider,
            model=record.model,
            outcome=record.outcome,
            error_code=record.error_code or "none",
        ).inc()
        vlm_latency_seconds.labels(
            provider=record.provider, model=record.model
        ).observe(record.latency_ms / 1000.0)

        for kind, value in (
            ("prompt", record.prompt_tokens),
            ("completion", record.completion_tokens),
        ):
            if value:
                vlm_tokens_total.labels(
                    provider=record.provider, model=record.model, kind=kind
                ).inc(value)

        if record.json_repaired:
            vlm_json_repairs_total.labels(
                provider=record.provider,
                model=record.model,
                strategy=record.json_strategy or "unknown",
            ).inc()

        fields = record.as_log_fields()
        if record.outcome == "success":
            logger.bind(**fields).info(
                f"VLM extraction ok [{record.provider}/{record.model}] "
                f"{record.latency_ms:.0f}ms"
            )
        else:
            logger.bind(**fields).warning(
                f"VLM extraction {record.outcome} [{record.provider}/{record.model}] "
                f"{record.error_code or 'unknown'}"
            )
    except Exception as exc:  # pragma: no cover - telemetry must never fail a call
        logger.debug(f"VLM telemetry suppressed: {type(exc).__name__}")


def record_retry(provider: str, model: str, reason: str) -> None:
    """Count one retried attempt. ``reason`` is an error *code*, never a message."""
    try:
        vlm_retries_total.labels(provider=provider, model=model, reason=reason).inc()
    except Exception as exc:  # pragma: no cover - a counter must not fail a call
        logger.debug(f"VLM retry metric suppressed: {type(exc).__name__}")


def record_stage(stage: str, provider: str, seconds: float) -> None:
    """Time one pipeline stage (ocr, prompt, vlm, validation)."""
    try:
        extraction_stage_seconds.labels(stage=stage, provider=provider).observe(seconds)
    except Exception as exc:  # pragma: no cover - a timer must not fail a call
        logger.debug(f"VLM stage metric suppressed: {type(exc).__name__}")


def record_extraction(document_type: str, provider: str, outcome: str) -> None:
    """Count one pipeline run."""
    try:
        document_extractions_total.labels(
            document_type=document_type, provider=provider, outcome=outcome
        ).inc()
    except Exception as exc:  # pragma: no cover - a counter must not fail a call
        logger.debug(f"VLM extraction metric suppressed: {type(exc).__name__}")


__all__ = [
    "REDACTED",
    "VLMCallRecord",
    "record_extraction",
    "record_retry",
    "record_stage",
    "record_vlm_call",
    "redact",
    "safe_url",
]
