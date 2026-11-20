"""Web search for voice: always an answer for the model, never an error."""

from __future__ import annotations

import pytest

from app.voice import search
from app.web_search.provider import SearchUnavailable
from app.web_search.schemas import WebSource


class FakeProvider:
    def __init__(self, sources=None, error: Exception | None = None) -> None:
        self.sources = sources or []
        self.error = error
        self.queries: list[str] = []

    async def search(self, query: str, *, count: int) -> list[WebSource]:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.sources[:count]

    async def contents(self, urls: list[str]) -> dict[str, str]:
        return {}


@pytest.fixture
def searchable(monkeypatch):
    monkeypatch.setattr(search, "web_search_available", lambda: True)

    async def claim(cap: int) -> bool:
        return True

    monkeypatch.setattr(search.budget, "claim_search", claim)


async def test_results_carry_source_and_text_within_budget(searchable) -> None:
    provider = FakeProvider([
        WebSource(url="https://www.thehindu.com/a", title="New CM sworn in",
                  published="2026-05-10", content="word " * 400),
    ])
    result = await search.voice_search("  current CM   of Tamil Nadu ", provider)
    assert provider.queries == ["current CM of Tamil Nadu"]
    assert result["found"] is True
    first = result["results"][0]
    assert first["source"] == "thehindu.com"
    assert first["published"] == "2026-05-10"
    assert len(first["text"]) <= search.RESULT_CHARS + 1


async def test_explicit_results_are_dropped(searchable) -> None:
    provider = FakeProvider([WebSource(url="https://pornhub.com/x", title="x", content="x")])
    assert (await search.voice_search("anything", provider))["found"] is False


async def test_a_failed_search_is_a_result_not_an_error(searchable) -> None:
    provider = FakeProvider(error=SearchUnavailable("down"))
    result = await search.voice_search("gold rate", provider)
    assert result["found"] is False
    assert "couldn't check" in result["note"]


async def test_an_explicit_request_is_never_searched(searchable) -> None:
    provider = FakeProvider([WebSource(url="https://a.com", title="a", content="a")])
    result = await search.voice_search("nude pics of someone", provider)
    assert result["found"] is False
    assert provider.queries == []


async def test_no_budget_means_no_search(monkeypatch) -> None:
    monkeypatch.setattr(search, "web_search_available", lambda: True)

    async def spent(cap: int) -> bool:
        return False

    monkeypatch.setattr(search.budget, "claim_search", spent)
    provider = FakeProvider([WebSource(url="https://a.com", title="a", content="a")])
    assert (await search.voice_search("gold rate", provider))["found"] is False
    assert provider.queries == []


async def test_search_switched_off_means_no_search(monkeypatch) -> None:
    monkeypatch.setattr(search, "web_search_available", lambda: False)
    provider = FakeProvider([WebSource(url="https://a.com", title="a", content="a")])
    assert (await search.voice_search("gold rate", provider))["found"] is False
    assert provider.queries == []
