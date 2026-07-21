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
    async def embed(self, texts: list[str]) -> list[EmbeddingResult]:
        """Return one EmbeddingResult per input text, in order."""


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

    async def embed(self, texts: list[str]) -> list[EmbeddingResult]:
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

    raise ValueError(f"Unknown embedding provider: {name}")
