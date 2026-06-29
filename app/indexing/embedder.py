"""
Embedding worker.

Converts CodeChunks to float vectors using Ollama's embedding model.
Processes in batches for throughput. Uses structured prefixes to improve
embedding quality for code.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from app.ollama_client import OllamaClient, get_ollama_client
from app.shared.schemas import CodeChunk

# Structured prefix improves embedding quality for code chunks.
# The embedding model uses this to understand context.
EMBED_PREFIX_TEMPLATE = "{language} {chunk_type}: {name}\nFile: {file_path}\n\n{content}"


def _build_embed_text(chunk: CodeChunk) -> str:
    """Build the text to embed for a code chunk."""
    name = chunk.function_name or chunk.class_name or ""
    return EMBED_PREFIX_TEMPLATE.format(
        language=chunk.language,
        chunk_type=chunk.chunk_type.value,
        name=name,
        file_path=chunk.file_path,
        content=chunk.content,
    )


class ChunkEmbedder:
    """
    Embeds CodeChunks using Ollama.

    Processes in configurable batches to balance:
    - Memory usage (large batches use more RAM)
    - Throughput (larger batches amortise HTTP overhead)
    - Failure isolation (smaller batches = less work lost on error)
    """

    def __init__(
        self,
        client: Optional[OllamaClient] = None,
        batch_size: int = 32,
        max_parallel: int = 4,
    ) -> None:
        self._client = client or get_ollama_client()
        self.batch_size = batch_size
        self.max_parallel = max_parallel

    async def embed_chunks(
        self,
        chunks: list[CodeChunk],
    ) -> list[tuple[CodeChunk, list[float]]]:
        """
        Embed a list of chunks.
        Returns list of (chunk, embedding_vector) pairs.
        Chunks that fail to embed are skipped (logged, not raised).
        """
        if not chunks:
            return []

        # Split into batches
        batches = [
            chunks[i : i + self.batch_size]
            for i in range(0, len(chunks), self.batch_size)
        ]

        results: list[tuple[CodeChunk, list[float]]] = []

        # Process batches with limited parallelism
        semaphore = asyncio.Semaphore(self.max_parallel)

        async def process_batch(batch: list[CodeChunk]) -> list[tuple[CodeChunk, list[float]]]:
            async with semaphore:
                return await self._embed_batch(batch)

        batch_results = await asyncio.gather(
            *[process_batch(b) for b in batches],
            return_exceptions=True,
        )

        for result in batch_results:
            if isinstance(result, Exception):
                # Log but continue — don't fail the entire index job
                continue
            results.extend(result)

        return results

    async def _embed_batch(
        self, chunks: list[CodeChunk]
    ) -> list[tuple[CodeChunk, list[float]]]:
        """Embed one batch of chunks."""
        texts = [_build_embed_text(c) for c in chunks]
        embeddings = await self._client.embed(texts)
        return list(zip(chunks, embeddings, strict=False))
