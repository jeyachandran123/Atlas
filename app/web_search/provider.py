"""Talking to a search engine.

``SearchProvider`` is the whole contract: given queries, return sources; given
URLs, return their text. You.com implements it today. Swapping to Tavily or
Brave later means writing one class and changing one factory line — nothing
above this file knows which engine answered.

Every method here returns data or raises ``SearchUnavailable``. It never returns
a half-result, and callers treat the exception as "answer without the web".
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import httpx
from loguru import logger

from app.config import settings
from app.web_search.schemas import WebSource

SEARCH_URL = "https://ydc-index.io/v1/search"
CONTENTS_URL = "https://ydc-index.io/v1/contents"


class SearchUnavailable(RuntimeError):
    """The web could not be searched. Never fatal to a chat turn."""


class SearchProvider(Protocol):
    async def search(self, query: str, *, count: int) -> list[WebSource]: ...

    async def contents(self, urls: list[str]) -> dict[str, str]: ...


def _opt(value: object) -> str | None:
    """A trimmed string, or None for anything empty or missing."""
    text = str(value).strip() if value is not None else ""
    return text or None


def _extract_of(item: dict) -> str:
    """The page text this result carries, whichever way it arrived.

    Verified against live responses, because the shape is not obvious:
    ``contents`` is an **object**, not a string — ``{"highlights": [...]}`` under
    highlights extraction and ``{"markdown": "..."}`` under full_page — while
    plain results instead carry a ``snippets`` list and no ``contents`` at all.
    Reading it as a string silently produced empty extracts for every result.
    """
    contents = item.get("contents")
    if isinstance(contents, dict):
        highlights = contents.get("highlights")
        if isinstance(highlights, list) and highlights:
            return "\n".join(str(h) for h in highlights if h)
        for key in ("markdown", "text", "html"):
            body = contents.get(key)
            if isinstance(body, str) and body.strip():
                return body
    elif isinstance(contents, str) and contents.strip():
        return contents
    snippets = item.get("snippets")
    if isinstance(snippets, list):
        return "\n".join(str(s) for s in snippets if s)
    return ""


def _as_source(item: dict) -> WebSource | None:
    """One result from You.com, or None when it carries no usable URL."""
    url = str(item.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    extract = _extract_of(item)
    return WebSource(
        url=url,
        title=" ".join(str(item.get("title") or "").split()),
        description=" ".join(str(item.get("description") or "").split()),
        thumbnail_url=_opt(item.get("thumbnail_url")),
        favicon_url=_opt(item.get("favicon_url")),
        published=_opt(item.get("page_age")),
        content=extract,
    )


class YouComProvider:
    """The You.com Search and Contents APIs.

    One search call returns ranked results, per-result thumbnails and — with
    ``extraction_mode`` — query-relevant passages from each page, which is why
    an ordinary question needs one round trip rather than one per page.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float | None = None,
        country: str | None = None,
    ) -> None:
        self._key = api_key if api_key is not None else settings.you_api_key.get_secret_value()
        self._timeout = timeout if timeout is not None else settings.web_search_timeout_s
        self._country = country or settings.web_search_country

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def _post(self, url: str, payload: dict) -> Any:
        """The two endpoints do not agree on a shape: search replies with an
        object, contents replies with a bare array. So this returns whatever
        was decoded and each caller reads its own shape."""
        if not self._key:
            raise SearchUnavailable("no API key configured")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url, json=payload, headers={"X-API-Key": self._key}
                )
        except httpx.HTTPError as e:
            raise SearchUnavailable(f"{type(e).__name__}: {e}") from e
        if response.status_code == 429:
            raise SearchUnavailable("rate limited by the search provider")
        if response.status_code >= 400:
            # The key itself is never logged; the status is what tells us
            # whether this is our fault, theirs, or a spent quota.
            raise SearchUnavailable(f"search API returned {response.status_code}")
        try:
            return response.json()
        except ValueError as e:
            raise SearchUnavailable("search API returned a non-JSON body") from e

    async def search(self, query: str, *, count: int = 6) -> list[WebSource]:
        """Results for one query, best first, each carrying what could be
        extracted from its page."""
        data = await self._post(
            SEARCH_URL,
            {
                "query": query,
                "count": count,
                "country": self._country,
                # Query-relevant passages rather than whole pages: enough to
                # answer from, a fraction of the tokens a full page costs.
                "extraction": {"extraction_mode": "highlights"},
            },
        )
        results = data.get("results") if isinstance(data, dict) else None
        buckets = results if isinstance(results, dict) else {}
        out: list[WebSource] = []
        seen: set[str] = set()
        # News before web: when both match, the dated item is the better answer
        # to the kind of question that reached a search in the first place.
        for bucket in ("news", "web"):
            for item in buckets.get(bucket) or []:
                if not isinstance(item, dict):
                    continue
                source = _as_source(item)
                if source and source.url not in seen:
                    seen.add(source.url)
                    out.append(source)
        return out[:count]

    async def contents(self, urls: list[str]) -> dict[str, str]:
        """Full text for pages worth opening, keyed by URL.

        A page that fails to fetch is simply absent from the result: one
        unreachable page must not discard the other one's text.
        """
        if not urls:
            return {}
        data = await self._post(
            CONTENTS_URL, {"urls": urls, "formats": ["markdown"], "crawl_timeout": 10}
        )
        # This endpoint answers with a bare array; an object with a "results"
        # key is tolerated in case that ever changes under us.
        items = data if isinstance(data, list) else (data or {}).get("results") or []
        out: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            body = item.get("markdown") or item.get("content") or item.get("text") or ""
            if url and isinstance(body, str) and body.strip():
                out[url] = body
        return out


async def gather_search(
    provider: SearchProvider, queries: list[str], *, count: int, limit: int
) -> list[WebSource]:
    """Run the planned queries together and merge them into one ranked list.

    Queries run concurrently because they are independent and the user is
    waiting. A query that fails contributes nothing and does not sink the rest —
    two good results beat an error page.
    """
    results = await asyncio.gather(
        *(provider.search(q, count=count) for q in queries), return_exceptions=True
    )
    merged: list[WebSource] = []
    seen: set[str] = set()
    failures = 0
    for outcome in results:
        if isinstance(outcome, BaseException):
            failures += 1
            logger.warning(f"Web search query failed: {outcome}")
            continue
        for source in outcome:
            if source.url not in seen:
                seen.add(source.url)
                merged.append(source)
    if failures and not merged:
        raise SearchUnavailable("every search query failed")
    return merged[:limit]
