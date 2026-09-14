"""The Library — uploads and creations across every chat.

  GET /api/v1/library                          → one page (kind, q, limit, offset)
  GET /api/v1/library/{kind}/{id}/download     → a signed link, or where to fetch the bytes
  GET /api/v1/library/{kind}/{id}/file         → the bytes, for storage that cannot sign
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.db.models import User
from app.library.service import DOWNLOAD_TTL, LibraryNotFound, LibraryService, ascii_filename

router = APIRouter(prefix="/library", tags=["Library"])

Kind = Literal["image", "document", "created"]


class LibraryItemOut(BaseModel):
    id: str
    kind: Kind
    name: str
    filename: str
    format: str
    mime_type: str
    size_bytes: int
    created_at: datetime
    conversation_id: Optional[str] = None
    conversation_title: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    page_count: Optional[int] = None
    origin: Optional[str] = None
    preview_url: Optional[str] = None


class LibraryCounts(BaseModel):
    image: int
    document: int
    created: int


class LibraryPageOut(BaseModel):
    items: list[LibraryItemOut]
    total: int
    counts: LibraryCounts
    limit: int
    offset: int


class LibraryDownloadOut(BaseModel):
    mode: Literal["signed_url", "proxy"]
    url: Optional[str] = None
    filename: str
    expires_in: Optional[int] = None


@router.get("", response_model=LibraryPageOut)
async def list_library(
    kind: Optional[Kind] = Query(None),
    q: Optional[str] = Query(None, max_length=200),
    limit: int = Query(48, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryPageOut:
    items, total, counts = await LibraryService(db).page(
        current_user.id, kind=kind, query=(q or "").strip() or None, limit=limit, offset=offset,
    )
    fields = LibraryItemOut.model_fields
    return LibraryPageOut(
        items=[LibraryItemOut(**{f: getattr(i, f) for f in fields}) for i in items],
        total=total, counts=LibraryCounts(**counts), limit=limit, offset=offset,
    )


@router.get("/{kind}/{item_id}/download", response_model=LibraryDownloadOut)
async def download_link(
    kind: Kind,
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryDownloadOut:
    try:
        filename, url = await LibraryService(db).link(current_user.id, kind, item_id)
    except LibraryNotFound:
        raise HTTPException(404, "Not found")
    if url:
        return LibraryDownloadOut(mode="signed_url", url=url, filename=filename, expires_in=DOWNLOAD_TTL)
    return LibraryDownloadOut(mode="proxy", filename=filename)


@router.get("/{kind}/{item_id}/file")
async def download_file(
    kind: Kind,
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        filename, content_type, data = await LibraryService(db).read(current_user.id, kind, item_id)
    except LibraryNotFound:
        raise HTTPException(404, "Not found")
    # RFC 6266 / 5987: an ASCII fallback, then the real name for browsers that read it.
    disposition = f'attachment; filename="{ascii_filename(filename)}"; filename*=UTF-8\'\'{quote(filename)}'
    return Response(content=data, media_type=content_type, headers={"Content-Disposition": disposition})
