"""NVIDIA's hosted embeddings: batched, back in order, questions and passages told apart."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.document_platform.semantic.providers import (
    EmbeddingProviderError,
    NvidiaEmbeddingProvider,
    get_embedding_provider,
)


class FakeEmbeddings:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    async def create(self, *, model, input, encoding_format, extra_body):
        self.calls.append({"model": model, "input": list(input), "extra": extra_body})
        if self.fail:
            raise RuntimeError("provider echoed the request: nvapi-SECRET")
        data = [SimpleNamespace(index=i, embedding=[float(len(t)), float(i)]) for i, t in enumerate(input)]
        # Out of order on purpose: the provider must put them back by index.
        return SimpleNamespace(data=list(reversed(data)))


def provider_with(fake: FakeEmbeddings) -> NvidiaEmbeddingProvider:
    provider = NvidiaEmbeddingProvider(model_name="nvidia/nemotron-3-embed-1b")
    provider._client = SimpleNamespace(embeddings=fake)
    return provider


async def test_vectors_come_back_in_input_order_across_batches():
    fake = FakeEmbeddings()
    provider = provider_with(fake)
    texts = [f"chunk {'x' * i}" for i in range(70)]

    out = await provider.embed(texts)

    assert len(out) == 70
    assert len(fake.calls) == 3  # 32 + 32 + 6
    assert [r.vector[0] for r in out] == [float(len(t)) for t in texts]
    assert provider.dimensions == 2


async def test_documents_embed_as_passages_and_questions_as_queries():
    fake = FakeEmbeddings()
    provider = provider_with(fake)

    await provider.embed(["a passage from the file"])
    await provider.embed(["what does the file say?"], purpose="query")

    assert [c["extra"]["input_type"] for c in fake.calls] == ["passage", "query"]
    assert all(c["extra"]["truncate"] == "END" for c in fake.calls)
    assert all(c["model"] == "nvidia/nemotron-3-embed-1b" for c in fake.calls)


async def test_a_failed_call_is_an_embedding_error_without_the_provider_message():
    with pytest.raises(EmbeddingProviderError) as caught:
        await provider_with(FakeEmbeddings(fail=True)).embed(["x"])
    assert "SECRET" not in str(caught.value)


async def test_nothing_to_embed_makes_no_call():
    fake = FakeEmbeddings()
    assert await provider_with(fake).embed([]) == []
    assert fake.calls == []


def test_the_factory_selects_nvidia_by_name():
    assert isinstance(get_embedding_provider("nvidia"), NvidiaEmbeddingProvider)
