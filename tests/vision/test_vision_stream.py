"""NVIDIA vision streaming: a chunk that carries no choices is skipped.

nemotron-3.5-super-vl ends every stream with a usage-only chunk whose
``choices`` list is empty. Indexing it raised IndexError after the whole reply
had streamed, so every image chat ended in "I didn't get to finish this reply".
"""

from __future__ import annotations

from types import SimpleNamespace

from app.vision.vision_model import VisionModel


def _chunk(content: str | None) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


class _FakeCompletions:
    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self._chunks = chunks

    async def create(self, **kwargs):  # noqa: ANN003
        async def stream():
            for chunk in self._chunks:
                yield chunk

        return stream()


def _fake_client(chunks: list[SimpleNamespace]):
    class FakeAsyncOpenAI:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            self.chat = SimpleNamespace(completions=_FakeCompletions(chunks))

    return FakeAsyncOpenAI


async def test_a_usage_only_chunk_ends_the_stream_cleanly(monkeypatch) -> None:
    usage_only = SimpleNamespace(choices=[], usage=SimpleNamespace(total_tokens=42))
    monkeypatch.setattr(
        "openai.AsyncOpenAI", _fake_client([_chunk("Total "), _chunk("20.80"), usage_only])
    )

    parts = [
        part
        async for part in VisionModel()._nvidia_vision_stream(
            "what is the total?", "", [b"\xff\xd8\xff" + b"0" * 16], 0.0
        )
    ]

    assert "".join(parts) == "Total 20.80"


async def test_empty_deltas_are_not_yielded(monkeypatch) -> None:
    monkeypatch.setattr("openai.AsyncOpenAI", _fake_client([_chunk(None), _chunk("ok"), _chunk("")]))

    parts = [part async for part in VisionModel()._nvidia_vision_stream("q", "", [], 0.0)]

    assert parts == ["ok"]
