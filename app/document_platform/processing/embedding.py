"""
Embedding preparation — INTERFACE ONLY in Phase 2.

Nothing in this phase calls embed(). Phase 3 wires the provider into the
pipeline after chunk persistence; new providers (OpenAI, Azure, Voyage,
Cohere) are one adapter class each.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class AbstractEmbeddingProvider(ABC):
    name: str = "abstract"
    dimensions: int = 0

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text."""


class OllamaEmbeddingProvider(AbstractEmbeddingProvider):
    """Adapter over the existing Ollama client (used by repo indexing)."""

    name = "ollama"

    def __init__(self, model: str = "nomic-embed-text") -> None:
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from app.ollama_client import get_ollama_client
        client = get_ollama_client()
        return [await client.embed(text=t, model=self._model) for t in texts]


def get_embedding_provider() -> AbstractEmbeddingProvider:
    """Provider factory — Phase 3 extends selection via config."""
    return OllamaEmbeddingProvider()
