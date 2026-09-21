"""The You.com adapter, against a stubbed transport — no live calls, no cost.

The two endpoints disagree about their response shape (search returns an object,
contents returns a bare array), which is exactly the kind of detail a mocked
"whatever I assumed" test would hide. These assert the documented shapes.
"""

from __future__ import annotations

import httpx
import pytest

from app.web_search.provider import (
    SearchUnavailable,
    YouComProvider,
    gather_search,
)
from app.web_search.schemas import WebSource

SEARCH_BODY = {
    "results": {
        "web": [
            {
                "url": "https://example.com/a",
                "title": "Alpha",
                "description": "about alpha",
                "snippets": ["first fragment", "second fragment"],
                "thumbnail_url": "https://img.example.com/a.png",
                "favicon_url": "https://example.com/favicon.ico",
            },
            {"url": "not-a-url", "title": "skipped"},
        ],
        "news": [
            {
                "url": "https://news.example.com/b",
                "title": "Beta",
                "description": "about beta",
                "page_age": "2026-09-20",
            }
        ],
    },
    "metadata": {"search_uuid": "x"},
}


@pytest.fixture
def patch_client(monkeypatch):
    def apply(handler):
        transport = httpx.MockTransport(handler)
        original = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs.setdefault("transport", transport)
            return original(*args, **kwargs)

        monkeypatch.setattr("app.web_search.provider.httpx.AsyncClient", factory)

    return apply


class TestSearch:
    async def test_results_become_sources_news_first(self, patch_client):
        """A dated item answers "what happened" better than an undated one."""
        patch_client(lambda request: httpx.Response(200, json=SEARCH_BODY))
        sources = await YouComProvider(api_key="k").search("anything", count=6)
        assert [s.title for s in sources] == ["Beta", "Alpha"]

    async def test_a_result_without_a_usable_url_is_dropped(self, patch_client):
        patch_client(lambda request: httpx.Response(200, json=SEARCH_BODY))
        sources = await YouComProvider(api_key="k").search("anything", count=6)
        assert all(s.url.startswith("https://") for s in sources)

    async def test_snippets_and_thumbnails_are_carried(self, patch_client):
        patch_client(lambda request: httpx.Response(200, json=SEARCH_BODY))
        alpha = (await YouComProvider(api_key="k").search("q", count=6))[1]
        assert alpha.content == "first fragment\nsecond fragment"
        assert alpha.thumbnail_url == "https://img.example.com/a.png"
        assert alpha.favicon_url == "https://example.com/favicon.ico"
        assert alpha.domain == "example.com"

    async def test_the_api_key_is_sent_as_a_header(self, patch_client):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["key"] = request.headers.get("X-API-Key")
            seen["body"] = request.read().decode()
            return httpx.Response(200, json=SEARCH_BODY)

        patch_client(handler)
        await YouComProvider(api_key="secret-key", country="IN").search("q", count=3)
        assert seen["key"] == "secret-key"
        assert '"country": "IN"' in seen["body"] or '"country":"IN"' in seen["body"]
        assert "highlights" in seen["body"]

    @pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
    async def test_every_error_status_is_a_clean_unavailable(self, patch_client, status):
        """Callers answer without the web on this exception; an unexpected
        exception type would escape and lose the user's reply."""
        patch_client(lambda request: httpx.Response(status, json={"error": "no"}))
        with pytest.raises(SearchUnavailable):
            await YouComProvider(api_key="k").search("q", count=3)

    async def test_a_network_failure_is_a_clean_unavailable(self, patch_client):
        def handler(request):
            raise httpx.ConnectError("dns down")

        patch_client(handler)
        with pytest.raises(SearchUnavailable):
            await YouComProvider(api_key="k").search("q", count=3)

    async def test_a_non_json_body_is_a_clean_unavailable(self, patch_client):
        patch_client(lambda request: httpx.Response(200, text="<html>nope</html>"))
        with pytest.raises(SearchUnavailable):
            await YouComProvider(api_key="k").search("q", count=3)

    async def test_no_key_means_unavailable_not_a_request(self):
        provider = YouComProvider(api_key="")
        assert provider.configured is False
        with pytest.raises(SearchUnavailable):
            await provider.search("q", count=3)


class TestExtractShapes:
    """Three shapes come back from one endpoint, confirmed against live calls.

    Reading ``contents`` as a string — which is what it looks like from the
    docs — gave every result an empty extract, so the model was answering from
    titles alone while the code reported a successful search.
    """

    async def test_highlights_extraction_returns_an_object_of_passages(self, patch_client):
        patch_client(lambda request: httpx.Response(200, json={"results": {"web": [{
            "url": "https://a.com", "title": "A",
            "contents": {"highlights": ["first passage", "second passage"]},
        }]}}))
        got = await YouComProvider(api_key="k").search("q", count=3)
        assert got[0].content == "first passage\nsecond passage"

    async def test_full_page_extraction_returns_markdown_in_that_object(self, patch_client):
        patch_client(lambda request: httpx.Response(200, json={"results": {"web": [{
            "url": "https://a.com", "title": "A",
            "contents": {"markdown": "# the whole page"},
        }]}}))
        got = await YouComProvider(api_key="k").search("q", count=3)
        assert got[0].content == "# the whole page"

    async def test_plain_results_fall_back_to_the_snippets_list(self, patch_client):
        patch_client(lambda request: httpx.Response(200, json={"results": {"web": [{
            "url": "https://a.com", "title": "A", "snippets": ["one", "two"],
        }]}}))
        got = await YouComProvider(api_key="k").search("q", count=3)
        assert got[0].content == "one\ntwo"

    async def test_a_result_with_neither_still_carries_its_description(self, patch_client):
        patch_client(lambda request: httpx.Response(200, json={"results": {"web": [{
            "url": "https://a.com", "title": "A", "description": "what it is about",
        }]}}))
        got = await YouComProvider(api_key="k").search("q", count=3)
        assert got[0].content == "" and got[0].description == "what it is about"


class TestContents:
    async def test_the_bare_array_response_is_read_correctly(self, patch_client):
        """The documented shape is a top-level array, not {"results": [...]}."""
        patch_client(
            lambda request: httpx.Response(
                200,
                json=[
                    {"url": "https://a.com", "title": "A", "markdown": "# full text"},
                    {"url": "https://b.com", "title": "B", "markdown": "   "},
                ],
            )
        )
        got = await YouComProvider(api_key="k").contents(["https://a.com", "https://b.com"])
        assert got == {"https://a.com": "# full text"}

    async def test_no_urls_makes_no_request(self, patch_client):
        def handler(request):  # pragma: no cover - must never run
            raise AssertionError("contents() called the API with no URLs")

        patch_client(handler)
        assert await YouComProvider(api_key="k").contents([]) == {}


class FakeProvider:
    def __init__(self, by_query: dict[str, list[WebSource] | Exception]) -> None:
        self._by_query = by_query

    async def search(self, query: str, *, count: int) -> list[WebSource]:
        result = self._by_query[query]
        if isinstance(result, Exception):
            raise result
        return result

    async def contents(self, urls: list[str]) -> dict[str, str]:
        return {}


class TestGatherSearch:
    async def test_results_merge_and_duplicates_collapse(self):
        shared = WebSource(url="https://same.com", title="Shared")
        provider = FakeProvider({
            "one": [shared, WebSource(url="https://a.com", title="A")],
            "two": [shared, WebSource(url="https://b.com", title="B")],
        })
        merged = await gather_search(provider, ["one", "two"], count=6, limit=10)
        assert [s.url for s in merged] == ["https://same.com", "https://a.com", "https://b.com"]

    async def test_one_failed_query_does_not_sink_the_others(self):
        provider = FakeProvider({
            "good": [WebSource(url="https://a.com", title="A")],
            "bad": SearchUnavailable("boom"),
        })
        merged = await gather_search(provider, ["good", "bad"], count=6, limit=10)
        assert [s.url for s in merged] == ["https://a.com"]

    async def test_every_query_failing_raises_so_the_caller_can_fall_back(self):
        provider = FakeProvider({"bad": SearchUnavailable("boom")})
        with pytest.raises(SearchUnavailable):
            await gather_search(provider, ["bad"], count=6, limit=10)

    async def test_the_limit_is_honoured(self):
        many = [WebSource(url=f"https://s{i}.com", title=str(i)) for i in range(20)]
        provider = FakeProvider({"q": many})
        assert len(await gather_search(provider, ["q"], count=20, limit=6)) == 6
