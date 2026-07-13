"""
Observability — Prometheus metrics, OpenTelemetry tracing, structured logging.

Design principle: measure what matters, ignore the rest.
Every metric answers a specific operational question.
"""

from __future__ import annotations

import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, Request, Response
from loguru import logger
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

from app.config import get_settings

cfg = get_settings()

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────────────────────────────────────


def configure_logging() -> None:
    """Configure loguru for structured JSON logging."""
    logger.remove()

    if cfg.log_format == "json":
        logger.add(
            sys.stdout,
            format=(
                '{{"time":"{time:YYYY-MM-DD HH:mm:ss.SSS}", '
                '"level":"{level}", '
                '"name":"{name}", '
                '"message":"{message}", '
                '"extra":{extra}}}'
            ),
            level=cfg.log_level,
            serialize=True,
            filter=lambda r: not (
                r["level"].name == "DEBUG"
                and "reasoning" not in r["name"]
                and "intelligence" not in r["name"]
            ),
        )
    else:
        logger.add(
            sys.stdout,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> — {message}",
            level=cfg.log_level,
            colorize=True,
            filter=lambda r: not (
                r["level"].name == "DEBUG"
                and "reasoning" not in r["name"]
                and "intelligence" not in r["name"]
            ),
        )


# ─────────────────────────────────────────────────────────────────────────────
# PROMETHEUS METRICS
# ─────────────────────────────────────────────────────────────────────────────

# API layer
http_request_duration = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint", "status_code"],
)
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

# Indexing pipeline
indexing_job_duration = Histogram(
    "indexing_job_duration_seconds",
    "Time to complete a full index job",
    ["job_type"],
)
indexing_chunks_total = Counter(
    "indexing_chunks_total",
    "Total code chunks created",
    ["language"],
)
indexing_queue_depth = Gauge(
    "indexing_queue_depth",
    "Current number of jobs waiting in the index queue",
)

# Agent / LLM
agent_execution_duration = Histogram(
    "agent_execution_duration_seconds",
    "Time for an agent to complete",
    ["agent_name"],
)
agent_executions_total = Counter(
    "agent_executions_total",
    "Total agent executions",
    ["agent_name", "status"],
)
ollama_request_duration = Histogram(
    "ollama_request_duration_seconds",
    "Ollama API call latency",
    ["model", "operation"],
)
ollama_tokens_total = Counter(
    "ollama_tokens_total",
    "Total tokens processed by Ollama",
    ["model", "type"],  # type: input|output
)

# Retrieval
retrieval_duration = Histogram(
    "retrieval_duration_seconds",
    "Time for a retrieval + re-ranking operation",
)
retrieval_results_count = Histogram(
    "retrieval_results_count",
    "Number of results returned per retrieval",
    buckets=[0, 1, 2, 3, 5, 8, 10, 15, 20],
)

# System health
ollama_available = Gauge(
    "ollama_available",
    "1 if Ollama is reachable, 0 otherwise",
)
chroma_collection_size = Gauge(
    "chroma_collection_chunks",
    "Number of chunks in a ChromaDB collection",
    ["repo_id"],
)


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST MIDDLEWARE
# ─────────────────────────────────────────────────────────────────────────────


async def metrics_middleware(request: Request, call_next: Callable) -> Response:
    """
    Middleware that:
    1. Assigns X-Request-ID to every request (propagates if already set)
    2. Records HTTP metrics
    3. Logs every request with timing
    """
    # Request ID
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    # Timer
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    # Normalise path for metric label (avoid high cardinality from path params)
    path = request.url.path
    for segment in path.split("/"):
        # Replace UUIDs and numeric IDs with placeholders
        if len(segment) == 36 and segment.count("-") == 4:  # UUID
            path = path.replace(segment, "{id}")
        elif segment.isdigit():
            path = path.replace(segment, "{id}")

    status = str(response.status_code)
    method = request.method

    http_request_duration.labels(method, path, status).observe(duration)
    http_requests_total.labels(method, path, status).inc()

    logger.info(
        f"{method} {request.url.path} → {status} ({duration * 1000:.1f}ms)",
        extra={"request_id": request_id, "duration_ms": round(duration * 1000, 1)},
    )

    response.headers["X-Request-ID"] = request_id
    return response


# ─────────────────────────────────────────────────────────────────────────────
# OPENTELEMETRY
# ─────────────────────────────────────────────────────────────────────────────


def setup_opentelemetry(app: FastAPI) -> None:
    """Configure OpenTelemetry tracing with OTLP export."""
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": "ai-coding-assistant"})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=cfg.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry tracing enabled")
    except ImportError:
        logger.warning("OpenTelemetry packages not fully installed — tracing disabled")
    except Exception as e:
        logger.warning(f"OpenTelemetry setup failed: {e} — tracing disabled")
