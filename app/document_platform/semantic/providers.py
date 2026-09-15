"""
Embedding Provider abstraction (Objectives 3 + 4).

AbstractEmbeddingProvider is the only contract the orchestrator depends on.
Adding OpenAI/Azure/Voyage/Cohere/Jina later is one new class implementing
this interface plus one registration call — the orchestrator never changes.

Supersedes the Phase 2 stub in processing/embedding.py (documented there as
"interface only... Phase 3 wires the provider in"). That file is part of the
frozen processing package and is left untouched; this is its real successor,
config-driven per Objective 4 rather than hardcoded.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    latency_ms: int


class EmbeddingProviderError(Exception):
    """The provider failed to generate an embedding (network, timeout, model error)."""


class AbstractEmbeddingProvider(ABC):
    name: str = "abstract"
    version: str = "1.0.0"
    model_name: str = ""
    dimensions: int = 0
    timeout_seconds: int = 60

    @abstractmethod
    async def embed(self, texts: list[str], *, purpose: str = "passage") -> list[EmbeddingResult]:
        """Return one EmbeddingResult per input text, in order.

        ``purpose`` is "passage" for text being stored and "query" for a search
        question. Retrieval models embed the two differently; symmetric models
        (nomic-embed-text) ignore it.
        """


class OllamaEmbeddingProvider(AbstractEmbeddingProvider):
    """
    Wraps the existing app.ollama_client.OllamaClient — no new HTTP client,
    no new connection pool. Model/endpoint/timeout are all config-driven
    (Objective 4): defaults come from Settings, never hardcoded here.
    """

    name = "ollama"
    version = "1.0.0"

    # nomic-embed-text's real output width; used only as a pre-flight sanity
    # default until the first real response confirms the actual dimension.
    _KNOWN_DIMENSIONS = {"nomic-embed-text": 768}

    def __init__(
        self,
        model_name: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        from app.config import get_settings
        cfg = get_settings()
        self.model_name = model_name or cfg.ollama_embed_model
        self.timeout_seconds = timeout_seconds or cfg.ollama_timeout
        self.dimensions = self._KNOWN_DIMENSIONS.get(self.model_name, 0)

    async def embed(self, texts: list[str], *, purpose: str = "passage") -> list[EmbeddingResult]:
        from app.ollama_client import get_ollama_client, OllamaUnavailableError

        if not texts:
            return []
        client = get_ollama_client()
        started = time.monotonic()
        try:
            vectors = await client.embed(texts=texts, model=self.model_name)
        except OllamaUnavailableError as e:
            raise EmbeddingProviderError(f"Ollama unavailable: {e}") from e
        except Exception as e:
            raise EmbeddingProviderError(f"Ollama embedding call failed: {e}") from e

        total_ms = int((time.monotonic() - started) * 1000)
        per_item_ms = max(1, total_ms // max(1, len(texts)))
        if vectors and self.dimensions == 0:
            self.dimensions = len(vectors[0])
        return [EmbeddingResult(vector=v, latency_ms=per_item_ms) for v in vectors]


class NvidiaEmbeddingProvider(AbstractEmbeddingProvider):
    """
    NVIDIA's hosted embeddings, over its OpenAI-compatible /v1/embeddings.

    For a deployment with no Ollama in reach — a hosted backend cannot see the
    GPU on someone's desk. Uses the same NVIDIA key as the chat model. The
    model is a retrieval model, so ``purpose`` goes through as ``input_type``.
    """

    name = "nvidia"
    version = "1.0.0"

    _BATCH = 32  # inputs per request; a document's chunks arrive in one call

    def __init__(
        self,
        model_name: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        from app.config import get_settings
        self._cfg = get_settings()
        self.model_name = model_name or self._cfg.nvidia_embed_model
        self.timeout_seconds = timeout_seconds or 60
        self.dimensions = 0  # learned from the first response
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            key = ""
            for field_name in ("nvidia_api_key", "vision_nvidia_api_key"):
                value = getattr(self._cfg, field_name, "")
                value = value.get_secret_value() if hasattr(value, "get_secret_value") else value
                if value:
                    key = str(value)
                    break
            if not key:
                raise EmbeddingProviderError("No NVIDIA API key is configured (NVIDIA_API_KEY).")
            self._client = AsyncOpenAI(
                base_url=str(getattr(self._cfg, "nvidia_base_url", "")
                             or "https://integrate.api.nvidia.com/v1"),
                api_key=key,
                timeout=self.timeout_seconds,
                max_retries=2,
            )
        return self._client

    async def embed(self, texts: list[str], *, purpose: str = "passage") -> list[EmbeddingResult]:
        if not texts:
            return []
        client = self._get_client()
        input_type = "query" if purpose == "query" else "passage"
        started = time.monotonic()
        vectors: list[list[float]] = []
        try:
            for i in range(0, len(texts), self._BATCH):
                res = await client.embeddings.create(
                    model=self.model_name,
                    input=texts[i:i + self._BATCH],
                    encoding_format="float",
                    extra_body={"input_type": input_type, "truncate": "END"},
                )
                vectors.extend(d.embedding for d in sorted(res.data, key=lambda d: d.index))
        except Exception as e:
            # Class only: provider error bodies can echo the request back.
            raise EmbeddingProviderError(f"NVIDIA embedding call failed ({type(e).__name__})") from e

        total_ms = int((time.monotonic() - started) * 1000)
        per_item_ms = max(1, total_ms // max(1, len(texts)))
        if vectors and self.dimensions == 0:
            self.dimensions = len(vectors[0])
        return [EmbeddingResult(vector=v, latency_ms=per_item_ms) for v in vectors]


def get_embedding_provider(provider_name: str | None = None) -> AbstractEmbeddingProvider:
    """
    Provider factory. `provider_name` defaults to config (dip_embedding_provider).
    Adding a new provider = one new elif branch + its own class — the
    orchestrator only ever sees AbstractEmbeddingProvider.
    """
    from app.config import get_settings
    cfg = get_settings()
    name = provider_name or cfg.dip_embedding_provider

    if name == "ollama":
        return OllamaEmbeddingProvider()
    if name == "nvidia":
        return NvidiaEmbeddingProvider()

    raise ValueError(f"Unknown embedding provider: {name}")
