"""Keeping the source cards after the stream has ended.

The cards are sent once, while the answer is being written. A page refresh
re-reads the conversation from the database, so without these rows the answer
would come back with nothing behind it and the links would be gone.

Only what a card shows is stored. The page text did its job when the reply was
written, and keeping copies of other people's pages is not this app's business.
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MessageSource
from app.web_search.schemas import SourceImage, WebSource

_TITLE = 512
_DESCRIPTION = 2000
_URL = 2048
_QUERY = 255

#: ``agent_used`` on an answer that was built from the web. It is how the next
#: turn knows a follow-up belongs to a searched conversation.
WEB_SEARCH_AGENT = "web_search"


async def save_sources(
    db: AsyncSession,
    message_id: str,
    sources: list[WebSource],
    *,
    images: list[SourceImage] | None = None,
    query: str = "",
) -> int:
    """Store the cards for one answer, in the order they were shown.

    Never raises: the reply has already been written and streamed, and losing
    its links is not worth losing the message itself.
    """
    # Which sources supplied a displayed picture, so a reload shows the same
    # ones rather than guessing from whatever has a thumbnail.
    shown = {image.source_url for image in (images or [])}
    rows = []
    for position, source in enumerate(sources):
        if not source.url or len(source.url) > _URL:
            continue
        rows.append(
            MessageSource(
                message_id=message_id,
                position=position,
                url=source.url,
                title=(source.title or "")[:_TITLE],
                domain=source.domain[:255],
                description=(source.description or "")[:_DESCRIPTION],
                thumbnail_url=(source.thumbnail_url or None),
                favicon_url=(source.favicon_url or None),
                published=(source.published or None),
                show_image=source.url in shown,
                query=(query or None) and query[:_QUERY],
            )
        )
    if not rows:
        return 0
    try:
        db.add_all(rows)
        await db.flush()
        return len(rows)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not store web sources for message {message_id}: {e}")
        return 0


async def last_answer_searched(db: AsyncSession, conversation_id: str) -> bool:
    """Was the answer before this one built from the web?

    A follow-up then searches too. Without this, "is there any reddit post
    about him" was answered from memory, and the model invented threads that
    contradicted the sourced answer directly above them.
    """
    from sqlalchemy import select

    from app.db.models import Message

    try:
        agent = (await db.execute(
            select(Message.agent_used)
            .where(Message.conversation_id == conversation_id, Message.role == "assistant")
            .order_by(Message.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Could not read the previous answer's origin: {e}")
        return False
    return agent == WEB_SEARCH_AGENT


def _rows_of(message) -> list:
    return sorted(getattr(message, "sources", []) or [], key=lambda r: r.position)


def cards_of(message) -> list[dict]:
    """The stored cards for a loaded message, ready for the browser."""
    return [
        {
            "url": row.url,
            "title": row.title or row.domain or row.url,
            "domain": row.domain,
            "description": row.description,
            "thumbnail_url": row.thumbnail_url,
            "favicon_url": row.favicon_url,
            "published": row.published,
        }
        for row in _rows_of(message)
    ]


def images_of(message) -> list[dict]:
    """The pictures that were shown with this answer, if any were."""
    return [
        {"url": row.thumbnail_url, "source_url": row.url, "title": row.title or row.domain}
        for row in _rows_of(message)
        if row.show_image and row.thumbnail_url
    ]


def query_of(message) -> str:
    """What was searched for, for the header line. Empty when not recorded."""
    for row in _rows_of(message):
        if row.query:
            return row.query
    return ""
