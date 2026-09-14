"""The note delivered with a generated file survives a provider that refuses to stream."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.chat_artifacts.service import ChatFileService

CARD = {"artifact_id": "a1", "title": "Dishes", "format": "csv", "source": "knowledge"}
CSV = b"Dish,State\nAppam,Kerala\nDosa,Tamil Nadu\n"


class FakeGateway:
    def __init__(self, *, stream_chunks=(), stream_error=None, complete_text="**Plain note.**"):
        self.stream_chunks = list(stream_chunks)
        self.stream_error = stream_error
        self.complete_text = complete_text
        self.completed = 0

    async def stream(self, **_):
        for chunk in self.stream_chunks:
            yield SimpleNamespace(kind="content", text=chunk)
        if self.stream_error:
            raise self.stream_error

    async def complete(self, **_):
        self.completed += 1
        return SimpleNamespace(text=self.complete_text)


@pytest.fixture
def file_on_disk(monkeypatch):
    artifact = SimpleNamespace(title="Dishes", filename="dishes.csv", storage_key="k")

    class Repo:
        def __init__(self, _db):
            pass

        async def get_artifact(self, *_):
            return artifact

    class Storage:
        async def get(self, _key):
            return CSV

    monkeypatch.setattr("app.document_platform.generation.repository.GenerationRepository", Repo)
    monkeypatch.setattr("app.storage.get_blob_storage", lambda _prefix: Storage())


async def overview(monkeypatch, gateway: FakeGateway) -> str:
    monkeypatch.setattr("app.llm.get_chat_gateway", lambda: gateway)
    parts = [c async for c in ChatFileService(None)._overview(CARD, user_id="u1", request="a list")]
    return "".join(parts)


async def test_a_stream_the_provider_refuses_falls_back_to_one_plain_call(monkeypatch, file_on_disk):
    gateway = FakeGateway(stream_error=RuntimeError("Service temporarily overloaded"))
    assert await overview(monkeypatch, gateway) == "**Plain note.**"
    assert gateway.completed == 1


async def test_a_stream_that_says_nothing_falls_back_too(monkeypatch, file_on_disk):
    gateway = FakeGateway()
    assert await overview(monkeypatch, gateway) == "**Plain note.**"
    assert gateway.completed == 1


async def test_a_stream_cut_short_keeps_what_was_written_and_does_not_repeat_it(monkeypatch, file_on_disk):
    gateway = FakeGateway(stream_chunks=["**A list ", "of dishes.**"], stream_error=RuntimeError("reset"))
    assert await overview(monkeypatch, gateway) == "**A list of dishes.**"
    assert gateway.completed == 0


async def test_a_working_stream_is_used_as_is(monkeypatch, file_on_disk):
    gateway = FakeGateway(stream_chunks=["**Two dishes.**"])
    assert await overview(monkeypatch, gateway) == "**Two dishes.**"
    assert gateway.completed == 0


async def test_no_note_when_neither_call_works(monkeypatch, file_on_disk):
    class Down(FakeGateway):
        async def complete(self, **_):
            self.completed += 1
            raise RuntimeError("down")

    gateway = Down(stream_error=RuntimeError("overloaded"))
    assert await overview(monkeypatch, gateway) == ""
    assert gateway.completed == 1
