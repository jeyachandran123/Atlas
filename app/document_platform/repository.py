"""
DIP data access — all SQL for the Document entity lives here.

Every query is owner-scoped (uploaded_by) and excludes soft-deleted rows
unless explicitly asked. No business rules; that's the service's job.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document


class DocumentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @property
    def db(self) -> AsyncSession:
        """The underlying session — shared with sibling repositories."""
        return self._db

    async def create(self, doc: Document) -> Document:
        self._db.add(doc)
        await self._db.flush()
        return doc

    async def get_owned(
        self, document_id: str, user_id: str, include_deleted: bool = False
    ) -> Optional[Document]:
        stmt = select(Document).where(
            Document.id == document_id,
            Document.uploaded_by == user_id,
        )
        if not include_deleted:
            stmt = stmt.where(Document.is_deleted.is_(False))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def find_duplicate(
        self, user_id: str, checksum_sha256: str
    ) -> Optional[Document]:
        stmt = (
            select(Document)
            .where(
                Document.uploaded_by == user_id,
                Document.checksum_sha256 == checksum_sha256,
                Document.is_deleted.is_(False),
                Document.upload_status == "completed",
            )
            .order_by(Document.created_at.desc())
            .limit(1)
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_owned(
        self,
        user_id: str,
        limit: int,
        offset: int,
        search: Optional[str] = None,
        extension: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[list[Document], int]:
        """Paginated, filtered listing. Returns (items, total-before-pagination)."""
        conditions = [
            Document.uploaded_by == user_id,
            Document.is_deleted.is_(False),
        ]
        if search:
            conditions.append(Document.original_filename.ilike(f"%{search}%"))
        if extension:
            ext = extension.lower()
            conditions.append(Document.extension == (ext if ext.startswith(".") else f".{ext}"))
        if status:
            conditions.append(Document.upload_status == status)

        total = (
            await self._db.execute(
                select(func.count()).select_from(Document).where(*conditions)
            )
        ).scalar_one()

        rows = (
            await self._db.execute(
                select(Document)
                .where(*conditions)
                .order_by(Document.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()

        return list(rows), int(total)

    async def mark_status(self, doc: Document, status: str) -> None:
        doc.upload_status = status
        await self._db.flush()

    async def soft_delete(self, doc: Document) -> None:
        doc.is_deleted = True
        doc.deleted_at = datetime.now(timezone.utc)
        await self._db.flush()
