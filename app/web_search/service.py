"""Running a search for one chat turn, and reporting it as it happens.

The service is an async generator of chat events, the same contract the file
flow uses: the route forwards whatever comes out to the browser, and the last
event carries the result the route needs. Progress is streamed rather than
awaited silently because a search adds seconds to a reply, and a status line
naming what it is doing is the difference between "working" and "frozen".

Nothing in here raises at the caller. Every failure — no key, no budget, a bad
decision, a dead network — ends the generator with an empty outcome, and the
turn is answered without the web.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from typing import Any

from loguru import logger

from app.web_search import budget
from app.web_search.decision import (
    DECIDE_SYSTEM,
    ENOUGH_SYSTEM,
    MAX_READS,
    build_decide_user,
    build_enough_user,
    parse_plan,
    parse_reads,
    worth_searching,
)
from app.web_search.images import vet
from app.web_search.provider import SearchProvider, SearchUnavailable, YouComProvider, gather_search
from app.web_search.schemas import SearchOutcome, SearchPlan, SourceImage, WebSource

#: The decision calls are short and must be certain, not creative.
_DECIDE_TEMPERATURE = 0.1
_DECIDE_MAX_TOKENS = 300


def _stage(stage: str, **extra: Any) -> dict[str, Any]:
    return {"type": "search_stage", "stage": stage, **extra}


#: Two is a glance; more is a gallery, and this is an answer, not an album.
MAX_IMAGES = 2
#: Candidates offered to the vetting step. Most results carry a preview and
#: most previews are branding, so the shortlist has to be longer than the two
#: pictures that survive it.
_CANDIDATES = 8


def pick_images(sources: list[WebSource], *, limit: int = _CANDIDATES) -> list[SourceImage]:
    """The pictures worth considering, taken from what the search returned.

    These are page previews rather than an image search, so the same picture
    can come back for several results from one site. Duplicates are dropped and
    the first distinct ones win, which keeps the best-ranked page's image.

    What comes out is a shortlist, not a choice: ``images.vet`` decides which
    of these is a photograph rather than a logo.
    """
    out: list[SourceImage] = []
    seen: set[str] = set()
    for source in sources:
        url = (source.thumbnail_url or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append(SourceImage(url=url, source_url=source.url, title=source.title))
        if len(out) == limit:
            break
    return out


def _with_page(source: WebSource, pages: dict[str, str]) -> WebSource:
    """The same source carrying its full text, when that page was opened."""
    body = pages.get(source.url)
    if not body:
        return source
    return WebSource(
        url=source.url, title=source.title, description=source.description,
        thumbnail_url=source.thumbnail_url, favicon_url=source.favicon_url,
        published=source.published, content=body,
    )


class WebSearchService:
    """Decide, search, read, and hand back what was found."""

    def __init__(self, provider: SearchProvider | None = None, *, complete=None) -> None:
        self._provider = provider if provider is not None else YouComProvider()
        # Injected so the decision calls can be tested without a model.
        self._complete = complete

    async def _ask(self, *, system: str, user: str) -> str:
        if self._complete is not None:
            return await self._complete(system=system, user=user)
        from app.llm import GENERAL, get_chat_gateway

        result = await get_chat_gateway().complete(
            user=user, system=system, profile=GENERAL, thinking=False,
            temperature=_DECIDE_TEMPERATURE, max_tokens=_DECIDE_MAX_TOKENS,
        )
        return result.text

    async def _plan(self, message: str, history: list[str], *, forced: bool):
        """What to search for, or None to answer without searching."""
        if forced:
            # The user pressed the globe. Their words are the query; spending a
            # model call to re-ask whether they meant it would be absurd.
            query = " ".join(message.split())[:200]
            return SearchPlan(queries=(query,), reason="requested by the user") if query else None
        try:
            text = await self._ask(
                system=DECIDE_SYSTEM, user=build_decide_user(message, history)
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Web search decision unavailable ({e}); answering without it")
            return None
        return parse_plan(text, message=message)

    async def _read_more(self, message: str, sources: list[WebSource]) -> tuple[str, ...]:
        """URLs worth opening in full, at most two, never invented."""
        try:
            text = await self._ask(
                system=ENOUGH_SYSTEM, user=build_enough_user(message, sources)
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Web search follow-up check failed ({e}); using search results only")
            return ()
        return parse_reads(text, allowed=[s.url for s in sources])

    async def run(
        self, message: str, *, history: list[str] | None = None, forced: bool = False,
        after_search: bool = False,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Chat events for this turn, ending with one ``_sources`` event.

        The final event always arrives, carrying an outcome that may be empty.
        The route reads it and streams the answer either way.
        """
        outcome = SearchOutcome()
        started = time.monotonic()
        # One path with no early return: the closing events below must always be
        # reached, and a `finally` that yields breaks if the client disconnects.
        try:
            from app.config import settings

            plan = (
                await self._plan(message, history or [], forced=forced)
                if worth_searching(message, forced=forced, after_search=after_search)
                else None
            )
            if plan is not None and await budget.claim_search(settings.web_search_daily_cap):
                yield _stage("searching", queries=list(plan.queries))
                sources = await gather_search(
                    self._provider, list(plan.queries),
                    count=settings.web_search_max_results,
                    limit=settings.web_search_max_results,
                )
                if sources:
                    outcome.sources = sources
                    outcome.queries = list(plan.queries)
                    if plan.wants_images:
                        # Vetted, not just picked: a page's preview image is
                        # as often its publisher's logo as a photograph of
                        # what was asked about.
                        outcome.images = await vet(
                            pick_images(sources),
                            limit=MAX_IMAGES,
                            query=plan.queries[0],
                        )

                    # ── The read round: at most one, never a third hop ──────
                    urls = await self._read_more(message, sources)
                    if urls:
                        yield _stage("reading", count=min(len(urls), MAX_READS))
                        pages = await self._open(list(urls))
                        if pages:
                            outcome.read = list(pages)
                            outcome.sources = [_with_page(s, pages) for s in sources]
                else:
                    logger.info(f"Web search returned nothing for {plan.queries}")
        except SearchUnavailable as e:
            logger.warning(f"Web search unavailable ({e}); answering without it")
            outcome = SearchOutcome()
        except Exception as e:  # noqa: BLE001 - a search must never lose a reply
            logger.exception(f"Web search failed unexpectedly: {e}")
            outcome = SearchOutcome()

        if outcome.sources:
            logger.info(
                f"Web search: {len(outcome.sources)} sources, {len(outcome.read)} read, "
                f"{int((time.monotonic() - started) * 1000)}ms"
            )
            yield {
                "type": "sources",
                "sources": [s.card() for s in outcome.sources],
                "images": [i.as_dict() for i in outcome.images],
                "queries": outcome.queries,
            }
        yield {"type": "_sources", "outcome": outcome}

    async def _open(self, urls: list[str]) -> dict[str, str]:
        """Full text for the chosen pages. One unreachable page is not a failure
        of the turn — the search results are still an answer."""
        try:
            return await self._provider.contents(urls)
        except SearchUnavailable as e:
            logger.warning(f"Could not open pages ({e}); using search results only")
            return {}


def web_search_available() -> bool:
    """Is search switched on and configured? Checked before any work is done."""
    from app.config import settings

    return bool(settings.web_search_enabled and settings.you_api_key.get_secret_value())
