"""The Library — everything a user has shared with the assistant, and everything it made for them.

Three sources, one list: images and documents attached in chat, and the files
the assistant generated. Nothing is copied. Each item points at bytes that
already live in blob storage (S3 in production), and previews and downloads
are short-lived signed URLs straight from the bucket, so the API never
streams a file it does not have to. When the storage backend cannot sign
(local disk), the bytes are served through the API instead.

Ownership is enforced in every query: chat attachments through their
conversation's owner, generated files through their own user id.
"""

from __future__ import annotations

import asyncio
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, GenerationArtifact, Message, MessageDocument, MessageImage

KINDS = ("image", "document", "created")
PREVIEW_TTL = 3600
DOWNLOAD_TTL = 300

_FORMAT_EXT = {"excel": "xlsx", "word": "docx", "markdown": "md"}


class LibraryNotFound(Exception):
    """No such item for this user, or its bytes are gone."""


@dataclass
class LibraryItem:
    id: str
    kind: str
    name: str
    filename: str
    format: str
    mime_type: str
    size_bytes: int
    created_at: datetime
    conversation_id: str | None = None
    conversation_title: str | None = None
    width: int | None = None
    height: int | None = None
    page_count: int | None = None
    origin: str | None = None  # created files: "chat" when made in a chat
    preview_url: str | None = None
    storage_key: str = ""      # internal — never returned by the API


def _ext(filename: str) -> str:
    return PurePosixPath(filename or "").suffix.lstrip(".").lower()


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def ascii_filename(filename: str) -> str:
    """A filename safe in an HTTP header: accents folded, anything else dropped."""
    folded = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode()
    folded = folded.replace('"', "").strip()
    return folded or f"file.{_ext(filename) or 'bin'}"


class LibraryService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── listing ───────────────────────────────────────────────────────────────

    async def page(
        self, user_id: str, *, kind: str | None = None, query: str | None = None,
        limit: int = 48, offset: int = 0,
    ) -> tuple[list[LibraryItem], int, dict[str, int]]:
        """One page, newest first, with the total for this view and a count per kind."""
        kinds = [kind] if kind in KINDS else list(KINDS)
        counts = {k: await self._count(user_id, k, query) for k in KINDS}
        # Each source is already sorted, so the newest ``offset + limit`` of
        # each is enough to cut this page from their merge.
        window = offset + limit
        items: list[LibraryItem] = []
        for k in kinds:
            items.extend(await self._fetch(user_id, k, query, window))
        items.sort(key=lambda i: i.created_at, reverse=True)
        page = items[offset: offset + limit]
        await self._sign_previews(page)
        return page, sum(counts[k] for k in kinds), counts

    def _statement(self, user_id: str, kind: str, query: str | None):
        like = f"%{_escape_like(query)}%" if query else None
        if kind in ("image", "document"):
            model = MessageImage if kind == "image" else MessageDocument
            stmt = (
                select(model, Conversation.title)
                .join(Conversation, Conversation.id == model.conversation_id)
                .where(Conversation.user_id == user_id)
            )
            if like:
                stmt = stmt.where(model.filename.ilike(like, escape="\\"))
            return stmt.order_by(model.created_at.desc())
        stmt = select(GenerationArtifact).where(
            GenerationArtifact.user_id == user_id, GenerationArtifact.status == "ready",
        )
        if like:
            stmt = stmt.where(or_(
                GenerationArtifact.title.ilike(like, escape="\\"),
                GenerationArtifact.filename.ilike(like, escape="\\"),
            ))
        return stmt.order_by(GenerationArtifact.created_at.desc())

    async def _count(self, user_id: str, kind: str, query: str | None) -> int:
        stmt = self._statement(user_id, kind, query).order_by(None)
        result = await self._db.execute(select(func.count()).select_from(stmt.subquery()))
        return int(result.scalar() or 0)

    async def _fetch(self, user_id: str, kind: str, query: str | None, window: int) -> list[LibraryItem]:
        result = await self._db.execute(self._statement(user_id, kind, query).limit(window))
        if kind == "image":
            return [
                LibraryItem(
                    id=img.id, kind="image", name=img.filename, filename=img.filename,
                    format=_ext(img.filename) or img.mime_type.split("/")[-1],
                    mime_type=img.mime_type, size_bytes=img.size_bytes or 0,
                    created_at=img.created_at, conversation_id=img.conversation_id,
                    conversation_title=title, width=img.width, height=img.height,
                    storage_key=img.storage_path,
                )
                for img, title in result.all()
            ]
        if kind == "document":
            return [
                LibraryItem(
                    id=doc.id, kind="document", name=doc.filename, filename=doc.filename,
                    format=_ext(doc.filename), mime_type=doc.mime_type,
                    size_bytes=doc.size_bytes or 0, created_at=doc.created_at,
                    conversation_id=doc.conversation_id, conversation_title=title,
                    page_count=doc.page_count, storage_key=doc.storage_path,
                )
                for doc, title in result.all()
            ]
        artifacts = list(result.scalars().all())
        links = await self._chat_links(user_id, [a.id for a in artifacts])
        items = []
        for a in artifacts:
            conversation_id, conversation_title = links.get(a.id, (None, None))
            items.append(LibraryItem(
                id=a.id, kind="created", name=" ".join((a.title or a.filename).split()),
                filename=a.filename,
                format=_ext(a.filename) or _FORMAT_EXT.get(a.format, a.format),
                mime_type=a.content_type, size_bytes=a.size_bytes or 0,
                created_at=a.created_at, conversation_id=conversation_id,
                conversation_title=conversation_title,
                origin="chat" if conversation_id else None, storage_key=a.storage_key,
            ))
        return items

    async def _chat_links(self, user_id: str, artifact_ids: list[str]) -> dict[str, tuple[str, str]]:
        """Which chat each file was made in — read from the chat's file cards."""
        if not artifact_ids:
            return {}
        rows = await self._db.execute(
            select(Message.content, Message.conversation_id, Conversation.title)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.user_id == user_id,
                Message.agent_used == "file_artifact",
                or_(*[Message.content.contains(i) for i in artifact_ids]),
            )
        )
        links: dict[str, tuple[str, str]] = {}
        for content, conversation_id, title in rows.all():
            try:
                artifact_id = json.loads(content).get("artifact_id")
            except (ValueError, AttributeError):
                continue
            if artifact_id:
                links.setdefault(artifact_id, (conversation_id, title))
        return links

    async def _sign_previews(self, items: list[LibraryItem]) -> None:
        from app.vision.image_storage import get_image_storage

        images = [i for i in items if i.kind == "image" and i.storage_key]
        if not images:
            return
        storage = get_image_storage()
        urls = await asyncio.gather(
            *(storage.signed_url(i.storage_key, expires_in=PREVIEW_TTL) for i in images),
            return_exceptions=True,
        )
        for item, url in zip(images, urls):
            item.preview_url = url if isinstance(url, str) else None

    # ── one item ──────────────────────────────────────────────────────────────

    async def _locate(self, user_id: str, kind: str, item_id: str) -> tuple[str, str, str]:
        """(storage key, filename, content type) of one of this user's items."""
        if kind in ("image", "document"):
            model = MessageImage if kind == "image" else MessageDocument
            row = (await self._db.execute(
                select(model)
                .join(Conversation, Conversation.id == model.conversation_id)
                .where(model.id == item_id, Conversation.user_id == user_id)
            )).scalar_one_or_none()
            if row is not None:
                return row.storage_path, row.filename, row.mime_type
        elif kind == "created":
            artifact = (await self._db.execute(
                select(GenerationArtifact).where(
                    GenerationArtifact.id == item_id,
                    GenerationArtifact.user_id == user_id,
                    GenerationArtifact.status == "ready",
                )
            )).scalar_one_or_none()
            if artifact is not None:
                return artifact.storage_key, artifact.filename, artifact.content_type
        raise LibraryNotFound(item_id)

    async def link(self, user_id: str, kind: str, item_id: str) -> tuple[str, str | None]:
        """(filename, signed download URL) — the URL is None when storage cannot sign."""
        key, filename, _ = await self._locate(user_id, kind, item_id)
        name = ascii_filename(filename)
        if kind == "image":
            from app.vision.image_storage import get_image_storage

            url = await get_image_storage().signed_url(key, expires_in=DOWNLOAD_TTL, download_filename=name)
        elif kind == "document":
            from app.documents.storage import get_document_storage

            url = await get_document_storage().signed_url(key, expires_in=DOWNLOAD_TTL, download_filename=name)
        else:
            from app.document_platform.generation.gateway import STORAGE_PREFIX
            from app.storage import get_blob_storage

            url = await get_blob_storage(STORAGE_PREFIX).signed_url(
                key, expires_in=DOWNLOAD_TTL, download_filename=name,
            )
        return filename, url

    async def read(self, user_id: str, kind: str, item_id: str) -> tuple[str, str, bytes]:
        """(filename, content type, bytes) — for storage that cannot hand out links."""
        from app.documents.storage import DocumentStorageError, get_document_storage
        from app.storage import BlobNotFoundError
        from app.vision.image_storage import ImageStorageError, get_image_storage

        key, filename, content_type = await self._locate(user_id, kind, item_id)
        try:
            if kind == "image":
                data = await get_image_storage().get_bytes_by_key(key)
            elif kind == "document":
                data = await get_document_storage().get_bytes(key)
            else:
                from app.document_platform.generation.gateway import STORAGE_PREFIX
                from app.storage import get_blob_storage

                data = await get_blob_storage(STORAGE_PREFIX).get(key)
        except (ImageStorageError, DocumentStorageError, BlobNotFoundError) as e:
            raise LibraryNotFound(item_id) from e
        return filename, content_type or "application/octet-stream", data
