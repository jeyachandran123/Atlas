"""All SQL for the Workspace layer. Reads of frozen platform tables
(documents, dip_conversations, dip_conversation_turns, generation_artifacts)
are centralized here, read-only — the platforms stay the source of truth."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ConversationDocument,
    DipConversation,
    DipConversationTurn,
    Document,
    GenerationArtifact,
    Workspace,
    WorkspaceArtifact,
    WorkspaceBookmark,
    WorkspaceConversation,
    WorkspaceDocument,
    WorkspaceSummaryRow,
    WorkspaceTimelineEvent,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WorkspaceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Workspaces ───────────────────────────────────────────────────────────

    async def create(
        self, user_id: str, org_id: str, name: str,
        description: str = "", icon: str = "folder", is_default: bool = False,
    ) -> Workspace:
        ws = Workspace(
            user_id=user_id, org_id=org_id, name=name[:120],
            description=description[:500], icon=icon[:30], is_default=is_default,
        )
        self._db.add(ws)
        await self._db.flush()
        return ws

    async def get(self, workspace_id: str, user_id: str) -> Optional[Workspace]:
        return (
            await self._db.execute(
                select(Workspace).where(
                    Workspace.id == workspace_id, Workspace.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    async def get_default(self, user_id: str) -> Optional[Workspace]:
        return (
            await self._db.execute(
                select(Workspace).where(
                    Workspace.user_id == user_id, Workspace.is_default.is_(True),
                )
            )
        ).scalar_one_or_none()

    async def list_for_user(self, user_id: str) -> list[Workspace]:
        rows = (
            await self._db.execute(
                select(Workspace)
                .where(Workspace.user_id == user_id, Workspace.status == "active")
                .order_by(Workspace.is_default.desc(), Workspace.created_at)
            )
        ).scalars().all()
        return list(rows)

    async def delete_workspace(self, ws: Workspace) -> None:
        ws.status = "archived"
        await self._db.flush()

    # ── Adoption (lazy backfill of pre-workspace content) ────────────────────

    async def unassigned_document_ids(self, org_id: str, user_id: str) -> list[str]:
        assigned = select(WorkspaceDocument.document_id)
        rows = (
            await self._db.execute(
                select(Document.id).where(
                    Document.org_id == org_id,
                    Document.uploaded_by == user_id,
                    Document.id.not_in(assigned),
                )
            )
        ).scalars().all()
        return list(rows)

    async def unassigned_conversations(self, user_id: str) -> list[DipConversation]:
        assigned = select(WorkspaceConversation.conversation_id)
        rows = (
            await self._db.execute(
                select(DipConversation).where(
                    DipConversation.user_id == user_id,
                    DipConversation.id.not_in(assigned),
                )
            )
        ).scalars().all()
        return list(rows)

    async def unassigned_artifact_ids(self, user_id: str) -> list[str]:
        assigned = select(WorkspaceArtifact.artifact_id)
        rows = (
            await self._db.execute(
                select(GenerationArtifact.id).where(
                    GenerationArtifact.user_id == user_id,
                    GenerationArtifact.id.not_in(assigned),
                )
            )
        ).scalars().all()
        return list(rows)

    # ── Documents ────────────────────────────────────────────────────────────

    async def link_document(self, workspace_id: str, document_id: str) -> None:
        existing = (
            await self._db.execute(
                select(WorkspaceDocument).where(WorkspaceDocument.document_id == document_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            self._db.add(WorkspaceDocument(workspace_id=workspace_id, document_id=document_id))
            await self._db.flush()

    async def documents_for(self, workspace_id: str) -> list[Document]:
        rows = (
            await self._db.execute(
                select(Document)
                .join(WorkspaceDocument, WorkspaceDocument.document_id == Document.id)
                .where(
                    WorkspaceDocument.workspace_id == workspace_id,
                    Document.is_deleted.is_(False),
                )
                .order_by(WorkspaceDocument.added_at.desc())
            )
        ).scalars().all()
        return list(rows)

    async def document_ids_for(self, workspace_id: str) -> list[str]:
        rows = (
            await self._db.execute(
                select(WorkspaceDocument.document_id)
                .join(Document, Document.id == WorkspaceDocument.document_id)
                .where(
                    WorkspaceDocument.workspace_id == workspace_id,
                    Document.is_deleted.is_(False),
                )
            )
        ).scalars().all()
        return list(rows)

    async def document_in_workspace(self, workspace_id: str, document_id: str) -> bool:
        return (
            await self._db.execute(
                select(WorkspaceDocument.id).where(
                    WorkspaceDocument.workspace_id == workspace_id,
                    WorkspaceDocument.document_id == document_id,
                )
            )
        ).scalar_one_or_none() is not None

    async def document_with_checksum(
        self, workspace_id: str, checksum: str,
    ) -> Optional[Document]:
        """Per-workspace duplicate detection (Phase 5.6): the SAME file is
        rejected within one workspace but allowed across different ones."""
        return (
            await self._db.execute(
                select(Document)
                .join(WorkspaceDocument, WorkspaceDocument.document_id == Document.id)
                .where(
                    WorkspaceDocument.workspace_id == workspace_id,
                    Document.checksum_sha256 == checksum,
                )
                .limit(1)
            )
        ).scalar_one_or_none()

    async def unlink_document(self, workspace_id: str, document_id: str) -> None:
        await self._db.execute(
            delete(WorkspaceDocument).where(
                WorkspaceDocument.workspace_id == workspace_id,
                WorkspaceDocument.document_id == document_id,
            )
        )
        await self._db.flush()

    async def purge_document_links(self, document_id: str) -> None:
        """Remove every workspace/conversation link to a document. Needed on
        delete because the frozen document delete is a SOFT delete (the row
        survives), so the FK cascades never fire."""
        await self._db.execute(
            delete(WorkspaceDocument).where(WorkspaceDocument.document_id == document_id)
        )
        await self._db.execute(
            delete(ConversationDocument).where(ConversationDocument.document_id == document_id)
        )
        await self._db.flush()

    async def delete_bookmarks_for(self, target_type: str, target_id: str) -> int:
        """Remove bookmarks pointing at a now-deleted target (documents,
        artifacts, conversations) — target_id is generic, not an FK, so these
        would otherwise orphan."""
        result = await self._db.execute(
            delete(WorkspaceBookmark).where(
                WorkspaceBookmark.target_type == target_type,
                WorkspaceBookmark.target_id == target_id,
            )
        )
        await self._db.flush()
        return result.rowcount or 0

    async def detach_document(self, conversation_id: str, document_id: str) -> bool:
        """Remove a document from ONE conversation's context (not the
        workspace). Returns True if a link was removed."""
        result = await self._db.execute(
            delete(ConversationDocument).where(
                ConversationDocument.conversation_id == conversation_id,
                ConversationDocument.document_id == document_id,
            )
        )
        await self._db.flush()
        return result.rowcount > 0

    # ── Conversations ────────────────────────────────────────────────────────

    async def link_conversation(
        self, workspace_id: str, conversation_id: str, title: str,
    ) -> WorkspaceConversation:
        existing = (
            await self._db.execute(
                select(WorkspaceConversation)
                .where(WorkspaceConversation.conversation_id == conversation_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        wc = WorkspaceConversation(
            workspace_id=workspace_id, conversation_id=conversation_id,
            title=(title or "New conversation")[:300],
        )
        self._db.add(wc)
        await self._db.flush()
        return wc

    async def conversations_for(self, workspace_id: str) -> list[WorkspaceConversation]:
        rows = (
            await self._db.execute(
                select(WorkspaceConversation)
                .where(
                    WorkspaceConversation.workspace_id == workspace_id,
                    WorkspaceConversation.status == "active",
                )
                .order_by(WorkspaceConversation.updated_at.desc())
            )
        ).scalars().all()
        return list(rows)

    async def archive_conversation(self, wc: WorkspaceConversation) -> None:
        """Soft delete — turns and citations are preserved, never orphaned."""
        wc.status = "archived"
        await self._db.flush()

    async def ws_conversation(
        self, conversation_id: str, include_archived: bool = False,
    ) -> Optional[WorkspaceConversation]:
        stmt = select(WorkspaceConversation).where(
            WorkspaceConversation.conversation_id == conversation_id
        )
        if not include_archived:
            stmt = stmt.where(WorkspaceConversation.status == "active")
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def touch_conversation(self, wc: WorkspaceConversation) -> None:
        wc.updated_at = _now()
        await self._db.flush()

    # ── Conversation ↔ documents (the many-to-many) ──────────────────────────

    async def attach_document(self, conversation_id: str, document_id: str) -> bool:
        """Returns True if newly attached (False when already present)."""
        existing = (
            await self._db.execute(
                select(ConversationDocument.id).where(
                    ConversationDocument.conversation_id == conversation_id,
                    ConversationDocument.document_id == document_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False
        self._db.add(ConversationDocument(
            conversation_id=conversation_id, document_id=document_id,
        ))
        await self._db.flush()
        return True

    async def conversation_document_ids(self, conversation_id: str) -> list[str]:
        rows = (
            await self._db.execute(
                select(ConversationDocument.document_id)
                .where(ConversationDocument.conversation_id == conversation_id)
                .order_by(ConversationDocument.added_at)
            )
        ).scalars().all()
        return list(rows)

    async def conversation_documents(self, conversation_id: str) -> list[Document]:
        rows = (
            await self._db.execute(
                select(Document)
                .join(ConversationDocument, ConversationDocument.document_id == Document.id)
                .where(
                    ConversationDocument.conversation_id == conversation_id,
                    Document.is_deleted.is_(False),
                )
                .order_by(ConversationDocument.added_at)
            )
        ).scalars().all()
        return list(rows)

    # ── Artifacts ────────────────────────────────────────────────────────────

    async def link_artifact(
        self, workspace_id: str, artifact_id: str, conversation_id: str | None = None,
    ) -> None:
        existing = (
            await self._db.execute(
                select(WorkspaceArtifact).where(WorkspaceArtifact.artifact_id == artifact_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            self._db.add(WorkspaceArtifact(
                workspace_id=workspace_id, artifact_id=artifact_id,
                conversation_id=conversation_id,
            ))
            await self._db.flush()

    async def artifacts_for(self, workspace_id: str) -> list[tuple[GenerationArtifact, Optional[str]]]:
        rows = (
            await self._db.execute(
                select(GenerationArtifact, WorkspaceArtifact.conversation_id)
                .join(WorkspaceArtifact, WorkspaceArtifact.artifact_id == GenerationArtifact.id)
                .where(WorkspaceArtifact.workspace_id == workspace_id)
                .order_by(WorkspaceArtifact.added_at.desc())
            )
        ).all()
        return [(r[0], r[1]) for r in rows]

    # ── Timeline ─────────────────────────────────────────────────────────────

    async def add_timeline(
        self, workspace_id: str, event_type: str, title: str,
        ref_type: str | None = None, ref_id: str | None = None,
        detail: dict[str, Any] | None = None, correlation_id: str | None = None,
    ) -> None:
        event = WorkspaceTimelineEvent(
            workspace_id=workspace_id, event_type=event_type, title=title[:300],
            ref_type=ref_type, ref_id=ref_id,
            detail_json=json.dumps(detail) if detail else None,
        )
        if correlation_id:
            event.correlation_id = correlation_id
        self._db.add(event)
        await self._db.flush()

    async def timeline_for(
        self, workspace_id: str, limit: int = 100,
    ) -> list[WorkspaceTimelineEvent]:
        rows = (
            await self._db.execute(
                select(WorkspaceTimelineEvent)
                .where(WorkspaceTimelineEvent.workspace_id == workspace_id)
                .order_by(WorkspaceTimelineEvent.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    # ── Bookmarks ────────────────────────────────────────────────────────────

    async def add_bookmark(
        self, workspace_id: str, user_id: str, target_type: str, target_id: str,
        note: str | None = None,
    ) -> Optional[WorkspaceBookmark]:
        existing = (
            await self._db.execute(
                select(WorkspaceBookmark).where(
                    WorkspaceBookmark.workspace_id == workspace_id,
                    WorkspaceBookmark.target_type == target_type,
                    WorkspaceBookmark.target_id == target_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        bm = WorkspaceBookmark(
            workspace_id=workspace_id, user_id=user_id,
            target_type=target_type, target_id=target_id,
            note=note[:500] if note else None,
        )
        self._db.add(bm)
        await self._db.flush()
        return bm

    async def bookmarks_for(self, workspace_id: str) -> list[WorkspaceBookmark]:
        rows = (
            await self._db.execute(
                select(WorkspaceBookmark)
                .where(WorkspaceBookmark.workspace_id == workspace_id)
                .order_by(WorkspaceBookmark.created_at.desc())
            )
        ).scalars().all()
        return list(rows)

    async def delete_bookmark(self, workspace_id: str, bookmark_id: str) -> bool:
        result = await self._db.execute(
            delete(WorkspaceBookmark).where(
                WorkspaceBookmark.id == bookmark_id,
                WorkspaceBookmark.workspace_id == workspace_id,
            )
        )
        await self._db.flush()
        return result.rowcount > 0

    # ── Summary cache ────────────────────────────────────────────────────────

    async def get_summary(self, workspace_id: str) -> Optional[WorkspaceSummaryRow]:
        return (
            await self._db.execute(
                select(WorkspaceSummaryRow)
                .where(WorkspaceSummaryRow.workspace_id == workspace_id)
            )
        ).scalar_one_or_none()

    async def upsert_summary(
        self, workspace_id: str, summary: str, stats: dict, suggestions: list[str],
        model: str,
    ) -> WorkspaceSummaryRow:
        row = await self.get_summary(workspace_id)
        if row is None:
            row = WorkspaceSummaryRow(workspace_id=workspace_id)
            self._db.add(row)
        row.summary = summary
        row.stats_json = json.dumps(stats)
        row.suggestions_json = json.dumps(suggestions)
        row.model = model
        row.generated_at = _now()
        await self._db.flush()
        return row

    # ── Stats ────────────────────────────────────────────────────────────────

    async def stats(self, workspace_id: str) -> dict[str, int]:
        async def count(model, col) -> int:
            return int((
                await self._db.execute(
                    select(func.count()).select_from(model).where(col == workspace_id)
                )
            ).scalar_one())

        active_conversations = int((
            await self._db.execute(
                select(func.count()).select_from(WorkspaceConversation).where(
                    WorkspaceConversation.workspace_id == workspace_id,
                    WorkspaceConversation.status == "active",
                )
            )
        ).scalar_one())
        return {
            "documents": await count(WorkspaceDocument, WorkspaceDocument.workspace_id),
            "conversations": active_conversations,
            "artifacts": await count(WorkspaceArtifact, WorkspaceArtifact.workspace_id),
            "bookmarks": await count(WorkspaceBookmark, WorkspaceBookmark.workspace_id),
            "timeline_events": await count(WorkspaceTimelineEvent, WorkspaceTimelineEvent.workspace_id),
        }

    # ── Search (SQL side — semantic hits are added by WorkspaceSearch) ──────

    async def search_documents(self, workspace_id: str, q: str, limit: int = 8) -> list[Document]:
        rows = (
            await self._db.execute(
                select(Document)
                .join(WorkspaceDocument, WorkspaceDocument.document_id == Document.id)
                .where(
                    WorkspaceDocument.workspace_id == workspace_id,
                    Document.is_deleted.is_(False),
                    Document.original_filename.ilike(f"%{q}%"),
                )
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def search_turns(
        self, workspace_id: str, q: str, limit: int = 8,
    ) -> list[tuple[DipConversationTurn, str]]:
        """Matching turns with their workspace display title."""
        rows = (
            await self._db.execute(
                select(DipConversationTurn, WorkspaceConversation.title)
                .join(WorkspaceConversation,
                      WorkspaceConversation.conversation_id == DipConversationTurn.conversation_id)
                .where(
                    WorkspaceConversation.workspace_id == workspace_id,
                    or_(
                        DipConversationTurn.question.ilike(f"%{q}%"),
                        DipConversationTurn.answer.ilike(f"%{q}%"),
                    ),
                )
                .order_by(DipConversationTurn.created_at.desc())
                .limit(limit)
            )
        ).all()
        return [(r[0], r[1]) for r in rows]

    async def search_conversations(
        self, workspace_id: str, q: str, limit: int = 8,
    ) -> list[WorkspaceConversation]:
        rows = (
            await self._db.execute(
                select(WorkspaceConversation)
                .where(
                    WorkspaceConversation.workspace_id == workspace_id,
                    WorkspaceConversation.title.ilike(f"%{q}%"),
                )
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def search_artifacts(
        self, workspace_id: str, q: str, limit: int = 8,
    ) -> list[GenerationArtifact]:
        rows = (
            await self._db.execute(
                select(GenerationArtifact)
                .join(WorkspaceArtifact, WorkspaceArtifact.artifact_id == GenerationArtifact.id)
                .where(
                    WorkspaceArtifact.workspace_id == workspace_id,
                    or_(
                        GenerationArtifact.title.ilike(f"%{q}%"),
                        GenerationArtifact.filename.ilike(f"%{q}%"),
                        GenerationArtifact.prompt.ilike(f"%{q}%"),
                    ),
                )
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def search_timeline(
        self, workspace_id: str, q: str, limit: int = 8,
    ) -> list[WorkspaceTimelineEvent]:
        rows = (
            await self._db.execute(
                select(WorkspaceTimelineEvent)
                .where(
                    WorkspaceTimelineEvent.workspace_id == workspace_id,
                    WorkspaceTimelineEvent.title.ilike(f"%{q}%"),
                )
                .order_by(WorkspaceTimelineEvent.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    # ── Read-only helpers into frozen tables ─────────────────────────────────

    async def turns_for_conversation(self, conversation_id: str) -> list[DipConversationTurn]:
        rows = (
            await self._db.execute(
                select(DipConversationTurn)
                .where(DipConversationTurn.conversation_id == conversation_id)
                .order_by(DipConversationTurn.seq)
            )
        ).scalars().all()
        return list(rows)

    async def get_document(self, document_id: str) -> Optional[Document]:
        return (
            await self._db.execute(select(Document).where(Document.id == document_id))
        ).scalar_one_or_none()

    async def get_artifact(self, artifact_id: str) -> Optional[GenerationArtifact]:
        return (
            await self._db.execute(
                select(GenerationArtifact).where(GenerationArtifact.id == artifact_id)
            )
        ).scalar_one_or_none()

    async def recent_conversation_titles(self, workspace_id: str, limit: int = 6) -> list[str]:
        rows = (
            await self._db.execute(
                select(WorkspaceConversation.title)
                .where(
                    WorkspaceConversation.workspace_id == workspace_id,
                    WorkspaceConversation.status == "active",
                )
                .order_by(WorkspaceConversation.updated_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)
