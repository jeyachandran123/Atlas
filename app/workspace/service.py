"""
WorkspaceService — the orchestrator of the Product Experience Layer. Wraps
the frozen platforms' gateways, adds linking + timeline + titles, and owns
transaction commits for workspace operations (the same boundary rule the
platform gateways follow for theirs).
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DipConversation, User, Workspace
from app.document_platform.conversation.gateway import ConversationGateway
from app.document_platform.conversation.repository import ConversationRepository
from app.document_platform.generation.gateway import GenerationGateway
from app.document_platform.semantic.providers import get_embedding_provider
from app.document_platform.semantic.vector_store import (
    collection_name_for,
    get_vector_store,
)
from app.workspace import titles as titles_mod
from app.workspace.repository import WorkspaceRepository

DEFAULT_WORKSPACE_NAME = "My Workspace"


class WorkspaceNotFoundError(Exception):
    pass


class DuplicateInWorkspaceError(Exception):
    """The same file (by checksum) already exists in this workspace. Allowed
    across different workspaces, rejected within one (Phase 5.6)."""

    def __init__(self, existing_id: str, filename: str) -> None:
        self.existing_id = existing_id
        self.filename = filename
        super().__init__(f"'{filename}' already exists in this workspace")


class WorkspaceService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self.repo = WorkspaceRepository(db)
        self._conv_repo = ConversationRepository(db)

    def _document_service(self):
        """A DocumentPlatformService bound to this request's session — so the
        workspace layer can drive the frozen upload pipeline without router
        plumbing. Never duplicates upload logic; only consumes it."""
        from app.document_platform.audit import DocumentAuditLogger
        from app.document_platform.repository import DocumentRepository
        from app.document_platform.service import DocumentPlatformService
        return DocumentPlatformService(
            repository=DocumentRepository(self._db),
            audit=DocumentAuditLogger(self._db),
        )

    # ── Bootstrap / lifecycle ────────────────────────────────────────────────

    async def ensure_default(self, user: User) -> Workspace:
        """Idempotent: creates the default workspace on first touch and adopts
        any pre-workspace documents/conversations/artifacts the user has."""
        ws = await self.repo.get_default(user.id)
        created = False
        if ws is None:
            ws = await self.repo.create(
                user.id, user.org_id, DEFAULT_WORKSPACE_NAME,
                description="Your default workspace", is_default=True,
            )
            created = True
            await self.repo.add_timeline(
                ws.id, "workspace_created", f"Workspace '{ws.name}' created",
                ref_type="workspace", ref_id=ws.id, correlation_id=ws.correlation_id,
            )

        # Adoption is cheap when there is nothing to adopt — safe to run always.
        for doc_id in await self.repo.unassigned_document_ids(user.org_id, user.id):
            await self.repo.link_document(ws.id, doc_id)
        for conv in await self.repo.unassigned_conversations(user.id):
            await self.repo.link_conversation(ws.id, conv.id, conv.title or "Conversation")
        for artifact_id in await self.repo.unassigned_artifact_ids(user.id):
            await self.repo.link_artifact(ws.id, artifact_id)

        if created:
            await self._db.commit()
        else:
            await self._db.commit()  # adoption links, if any
        return ws

    async def require(self, workspace_id: str, user: User) -> Workspace:
        ws = await self.repo.get(workspace_id, user.id)
        if ws is None or ws.status != "active":
            raise WorkspaceNotFoundError(workspace_id)
        return ws

    async def create_workspace(
        self, user: User, name: str, description: str = "", icon: str = "folder",
    ) -> Workspace:
        ws = await self.repo.create(user.id, user.org_id, name, description, icon)
        await self.repo.add_timeline(
            ws.id, "workspace_created", f"Workspace '{ws.name}' created",
            ref_type="workspace", ref_id=ws.id, correlation_id=ws.correlation_id,
        )
        await self._db.commit()
        return ws

    # ── Documents ────────────────────────────────────────────────────────────

    async def upload_document(
        self, ws: Workspace, content: bytes, filename: str | None,
        declared_mime: str | None, conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Atomic workspace upload (Phase 5.6): checksum → per-workspace duplicate
        check → frozen upload pipeline (allow_duplicate so the SAME file is
        permitted in a DIFFERENT workspace) → link → optional conversation
        attach → timeline. One request, one document, no client-side race.
        """
        import hashlib

        checksum = hashlib.sha256(content).hexdigest()
        existing = await self.repo.document_with_checksum(ws.id, checksum)
        if existing is not None:
            raise DuplicateInWorkspaceError(existing.id, existing.original_filename)

        doc, _ = await self._document_service().upload(
            org_id=ws.org_id, user_id=ws.user_id, filename=filename,
            content=content, declared_mime=declared_mime, allow_duplicate=True,
        )
        await self.repo.link_document(ws.id, doc.id)
        await self.repo.add_timeline(
            ws.id, "document_added", f"Uploaded {doc.original_filename}",
            ref_type="document", ref_id=doc.id,
        )
        attached = False
        if conversation_id:
            wc = await self.repo.ws_conversation(conversation_id)
            if wc is not None and wc.workspace_id == ws.id:
                attached = await self.repo.attach_document(conversation_id, doc.id)
                if attached:
                    await self.repo.add_timeline(
                        ws.id, "document_attached",
                        f"Attached {doc.original_filename} to '{wc.title}'",
                        ref_type="conversation", ref_id=conversation_id,
                    )
        await self._db.commit()
        return {
            "document": doc, "attached_to_conversation": attached,
        }

    async def document_content(
        self, ws: Workspace, document_id: str,
    ) -> tuple[bytes, str, str]:
        """Raw document bytes for the in-app viewer, served inline through the
        API (same origin) so the browser never fetches the S3 signed URL
        cross-origin — which CORS would block. Reuses the frozen proxy read."""
        if not await self.repo.document_in_workspace(ws.id, document_id):
            raise WorkspaceNotFoundError(document_id)
        doc, data = await self._document_service().download_bytes(
            ws.org_id, ws.user_id, document_id,
        )
        return data, doc.mime_type, doc.original_filename

    async def artifact_content(
        self, ws: Workspace, artifact_id: str,
    ) -> tuple[bytes, str, str]:
        """Raw generated-artifact bytes for the in-app viewer (same rationale)."""
        from app.document_platform.generation.gateway import STORAGE_PREFIX
        from app.storage import get_blob_storage

        art = await self.repo.get_artifact(artifact_id)
        if art is None or art.user_id != ws.user_id:
            raise WorkspaceNotFoundError(artifact_id)
        data = await get_blob_storage(STORAGE_PREFIX).get(art.storage_key)
        return data, art.content_type or "application/octet-stream", art.filename

    async def delete_document(self, ws: Workspace, document_id: str) -> dict[str, Any]:
        """
        Complete deletion (Objective 5). The frozen document delete is a SOFT
        delete, so on its own it leaves embeddings, semantic manifests, chunks,
        knowledge, vectors, links, and bookmarks behind — all still
        retrievable. This purges the full footprint by reusing the existing
        platform repositories (never duplicating their logic):

          Chroma vectors → embedding_records/jobs/manifests → chunks/knowledge
          → workspace & conversation links → bookmarks → frozen soft-delete.
        """
        from app.document_platform.knowledge.repository import KnowledgeManifestRepository
        from app.document_platform.processing.persistence import ProcessingRepository
        from app.document_platform.semantic.repository import SemanticRepository
        from app.document_platform.semantic.vector_store import (
            collection_name_for,
            get_vector_store,
        )

        doc = await self.repo.get_document(document_id)
        if doc is None or doc.uploaded_by != ws.user_id:
            raise WorkspaceNotFoundError(document_id)

        proc_repo = ProcessingRepository(self._db)
        sem_repo = SemanticRepository(self._db)
        knowledge = await proc_repo.knowledge_for(document_id)

        removed_vectors = 0
        if knowledge is not None:
            # 1. Remove vectors from the search index (Chroma). Their ids are
            #    the embedding_record ids used at upsert time. Best-effort —
            #    a vector-store hiccup must not block the delete.
            try:
                records, _ = await sem_repo.list_embeddings_for_knowledge(
                    knowledge.id, limit=10000, offset=0,
                )
                vector_ids = [r.id for r in records]
                if vector_ids:
                    removed_vectors = await get_vector_store().delete(
                        collection_name_for(ws.org_id), vector_ids,
                    )
            except Exception as e:
                logger.warning(f"Chroma vector cleanup failed for {document_id} (non-fatal): {e}")
            # 2. Semantic metadata (embedding_records, jobs, events, manifest).
            await sem_repo.wipe_all_semantic_for_document_reprocess(knowledge.id)
            # 3. Knowledge manifest (Phase 2.6) — must go before the knowledge
            #    object it references (FK, no cascade); same order the reprocess
            #    path uses.
            await KnowledgeManifestRepository(self._db).delete_manifests_for_document(document_id)
            # 4. Derived knowledge (chunks, knowledge object, metadata, images).
            await proc_repo.wipe_derived(document_id)

        # 4. Workspace + conversation links (soft-delete won't cascade them).
        await self.repo.purge_document_links(document_id)
        # 5. Bookmarks referencing this document.
        bookmarks_removed = await self.repo.delete_bookmarks_for("document", document_id)
        # 6. Frozen soft-delete (marks is_deleted + audit).
        await self._document_service().delete(ws.org_id, ws.user_id, document_id)
        # 7. Audit the deletion on the workspace timeline (history is kept).
        await self.repo.add_timeline(
            ws.id, "document_deleted", f"Deleted {doc.original_filename}",
            ref_type="document", ref_id=document_id,
            detail={"vectors_removed": removed_vectors, "bookmarks_removed": bookmarks_removed},
        )
        await self._db.commit()
        return {
            "document_id": document_id,
            "vectors_removed": removed_vectors,
            "bookmarks_removed": bookmarks_removed,
        }

    async def add_document(
        self, ws: Workspace, document_id: str, conversation_id: str | None = None,
    ) -> dict[str, Any]:
        doc = await self.repo.get_document(document_id)
        if doc is None or doc.uploaded_by != ws.user_id:
            raise WorkspaceNotFoundError(document_id)
        await self.repo.link_document(ws.id, document_id)
        await self.repo.add_timeline(
            ws.id, "document_added", f"Uploaded {doc.original_filename}",
            ref_type="document", ref_id=document_id,
        )
        attached = False
        if conversation_id:
            wc = await self.repo.ws_conversation(conversation_id)
            if wc is not None and wc.workspace_id == ws.id:
                attached = await self.repo.attach_document(conversation_id, document_id)
                if attached:
                    await self.repo.add_timeline(
                        ws.id, "document_attached",
                        f"Attached {doc.original_filename} to '{wc.title}'",
                        ref_type="conversation", ref_id=conversation_id,
                    )
        await self._db.commit()
        return {"document_id": document_id, "attached_to_conversation": attached}

    # ── Conversations ────────────────────────────────────────────────────────

    async def start_conversation(
        self, ws: Workspace, title: str = "",
    ) -> tuple[DipConversation, str]:
        gateway = ConversationGateway(self._db)
        conv = await gateway.start_conversation(ws.user_id, ws.org_id, title)
        wc = await self.repo.link_conversation(ws.id, conv.id, title or "New conversation")
        await self.repo.add_timeline(
            ws.id, "conversation_started", f"Started '{wc.title}'",
            ref_type="conversation", ref_id=conv.id, correlation_id=conv.correlation_id,
        )
        await self._db.commit()
        return conv, wc.title

    async def conversation_in_workspace(self, ws: Workspace, conversation_id: str):
        wc = await self.repo.ws_conversation(conversation_id)
        if wc is None or wc.workspace_id != ws.id:
            raise WorkspaceNotFoundError(conversation_id)
        conv = await self._conv_repo.get_conversation(conversation_id, ws.user_id)
        if conv is None:
            raise WorkspaceNotFoundError(conversation_id)
        return wc, conv

    async def restore_payload(self, ws: Workspace, conversation_id: str) -> dict[str, Any]:
        """Everything the UI needs to continue exactly where the user left
        off: turns (with citations), attached documents, related artifacts."""
        wc, conv = await self.conversation_in_workspace(ws, conversation_id)
        turns = await self.repo.turns_for_conversation(conversation_id)
        documents = await self.repo.conversation_documents(conversation_id)
        artifacts = [
            {"id": a.id, "title": a.title, "filename": a.filename,
             "format": a.format, "status": a.status}
            for a, conv_ref in await self.repo.artifacts_for(ws.id)
            if conv_ref == conversation_id
        ]
        return {
            "conversation_id": conversation_id,
            "title": wc.title,
            "correlation_id": conv.correlation_id,
            "turns": [
                {
                    "id": t.id, "seq": t.seq, "question": t.question,
                    "answer": t.answer, "status": t.status, "grounded": t.grounded,
                    "grounding_score": t.grounding_score,
                    "citations": json.loads(t.citations_json) if t.citations_json else [],
                    "created_at": t.created_at.isoformat(),
                }
                for t in turns
            ],
            "documents": [
                {"id": d.id, "filename": d.original_filename,
                 "processing_status": d.processing_status}
                for d in documents
            ],
            "artifacts": artifacts,
        }

    async def _conversation_scope(self, ws: Workspace, conversation_id: str) -> list[str] | None:
        """Attached documents win; otherwise all workspace documents; None
        only when the workspace is empty (no possible scope)."""
        attached = await self.repo.conversation_document_ids(conversation_id)
        if attached:
            return attached
        ws_docs = await self.repo.document_ids_for(ws.id)
        return ws_docs or None

    async def ask_stream(
        self, ws: Workspace, conversation_id: str, question: str,
        document_ids: list[str] | None = None,
    ) -> AsyncIterator[str]:
        """Wraps the frozen ConversationGateway stream: resolves the
        multi-document scope, forwards every SSE event untouched, then adds
        timeline + auto-title (emitted as a trailing `title` event)."""
        wc, conv = await self.conversation_in_workspace(ws, conversation_id)

        # Explicitly-passed documents become part of the conversation.
        for doc_id in document_ids or []:
            if await self.repo.document_in_workspace(ws.id, doc_id):
                await self.repo.attach_document(conversation_id, doc_id)
        scope = await self._conversation_scope(ws, conversation_id)
        await self._db.commit()

        gateway = ConversationGateway(self._db)
        done_payload: dict | None = None
        async for frame in gateway.ask_stream(conv, question, scope):
            if frame.startswith("event: done"):
                for line in frame.split("\n"):
                    if line.startswith("data: "):
                        try:
                            done_payload = json.loads(line[6:])
                        except json.JSONDecodeError:
                            pass
            yield frame

        # Post-answer bookkeeping — separate transaction, never blocks tokens.
        try:
            first_turn = len(await self.repo.turns_for_conversation(conversation_id)) == 1
            await self.repo.touch_conversation(wc)
            await self.repo.add_timeline(
                ws.id, "question_answered", question[:200],
                ref_type="conversation", ref_id=conversation_id,
                detail={"status": (done_payload or {}).get("status")},
                correlation_id=conv.correlation_id,
            )
            if first_turn and not wc.title_generated:
                answer = ""
                turns = await self.repo.turns_for_conversation(conversation_id)
                if turns and turns[0].answer:
                    answer = turns[0].answer
                wc.title = await titles_mod.generate_title(question, answer)
                wc.title_generated = True
            await self._db.commit()
            if wc.title_generated:
                yield f"event: title\ndata: {json.dumps({'title': wc.title})}\n\n"
        except Exception as e:
            logger.warning(f"Post-answer workspace bookkeeping failed: {e}")

    async def delete_conversation(self, ws: Workspace, conversation_id: str) -> None:
        """Soft delete (Objective 4): archive the workspace link so it drops
        out of every list, while the underlying turns/citations stay intact
        (no orphans, fully auditable). The frozen conversation is untouched."""
        wc, _ = await self.conversation_in_workspace(ws, conversation_id)
        title = wc.title
        await self.repo.archive_conversation(wc)
        await self.repo.delete_bookmarks_for("conversation", conversation_id)
        await self.repo.add_timeline(
            ws.id, "conversation_deleted", f"Deleted '{title}'",
            ref_type="conversation", ref_id=conversation_id,
        )
        await self._db.commit()

    async def remove_document_from_conversation(
        self, ws: Workspace, conversation_id: str, document_id: str,
    ) -> bool:
        """Remove a document from ONE conversation's context (Objective 9).
        The document stays in the workspace — only the conversation link goes."""
        wc, _ = await self.conversation_in_workspace(ws, conversation_id)
        removed = await self.repo.detach_document(conversation_id, document_id)
        if removed:
            doc = await self.repo.get_document(document_id)
            await self.repo.add_timeline(
                ws.id, "document_detached",
                f"Removed {doc.original_filename if doc else 'a document'} from '{wc.title}'",
                ref_type="conversation", ref_id=conversation_id,
            )
        await self._db.commit()
        return removed

    async def rename_conversation(self, ws: Workspace, conversation_id: str, title: str) -> str:
        wc, _ = await self.conversation_in_workspace(ws, conversation_id)
        wc.title = title[:300]
        wc.title_generated = True
        await self.repo.add_timeline(
            ws.id, "conversation_renamed", f"Renamed to '{wc.title}'",
            ref_type="conversation", ref_id=conversation_id,
        )
        await self._db.commit()
        return wc.title

    # ── Generation ───────────────────────────────────────────────────────────

    async def generate_stream(
        self, ws: Workspace, prompt: str, format_name: str,
        conversation_id: str | None = None,
    ) -> AsyncIterator[str]:
        scope: list[str] | None = None
        if conversation_id:
            wc, _ = await self.conversation_in_workspace(ws, conversation_id)
            scope = await self._conversation_scope(ws, conversation_id)
        else:
            scope = (await self.repo.document_ids_for(ws.id)) or None

        gateway = GenerationGateway(self._db)
        artifact_id: str | None = None
        status = ""
        title = ""
        async for frame in gateway.generate_stream(
            ws.user_id, ws.org_id, prompt, format_name, scope,
        ):
            if frame.startswith("event: meta") or frame.startswith("event: done"):
                for line in frame.split("\n"):
                    if line.startswith("data: "):
                        try:
                            payload = json.loads(line[6:])
                            artifact_id = payload.get("artifact_id", artifact_id)
                            status = payload.get("status", status)
                            title = payload.get("title", title)
                        except json.JSONDecodeError:
                            pass
            yield frame

        if artifact_id:
            try:
                await self.repo.link_artifact(ws.id, artifact_id, conversation_id)
                await self.repo.add_timeline(
                    ws.id, "artifact_generated",
                    f"Generated {title or format_name} ({format_name})",
                    ref_type="artifact", ref_id=artifact_id,
                    detail={"status": status, "format": format_name},
                )
                await self._db.commit()
            except Exception as e:
                logger.warning(f"Artifact workspace linking failed: {e}")

    # ── Save conversation as Knowledge ───────────────────────────────────────

    async def save_as_knowledge(
        self, ws: Workspace, conversation_id: str,
    ) -> dict[str, Any]:
        """Renders the conversation to Markdown and pushes it through the
        EXISTING upload pipeline — it becomes a real document → knowledge
        object → embeddings, searchable forever. Zero duplicated logic.
        Recovery (see processing.recovery) guarantees it reaches
        knowledge_ready even if the enqueue is dropped."""
        from app.workspace.export import conversation_markdown

        wc, _ = await self.conversation_in_workspace(ws, conversation_id)
        turns = await self.repo.turns_for_conversation(conversation_id)
        markdown = conversation_markdown(wc.title, turns)
        doc, duplicate_of = await self._document_service().upload(
            org_id=ws.org_id, user_id=ws.user_id,
            filename=f"{wc.title[:80] or 'conversation'}.md",
            content=markdown.encode("utf-8"),
            declared_mime="text/markdown",
            allow_duplicate=True,
        )
        await self.repo.link_document(ws.id, doc.id)
        await self.repo.add_timeline(
            ws.id, "saved_as_knowledge", f"Saved '{wc.title}' as knowledge",
            ref_type="document", ref_id=doc.id,
            detail={"conversation_id": conversation_id},
        )
        await self._db.commit()
        return {"document_id": doc.id, "duplicate_of": duplicate_of}

    # ── Related / suggestions (Objective 16) ─────────────────────────────────

    async def related(
        self, ws: Workspace, query: str, conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Semantic recommendation of workspace documents (and the
        conversations that used them) relevant to the current question."""
        exclude: set[str] = set()
        if conversation_id:
            exclude = set(await self.repo.conversation_document_ids(conversation_id))
        doc_ids = [d for d in await self.repo.document_ids_for(ws.id)]
        candidates = [d for d in doc_ids if d not in exclude]
        if not candidates or not query.strip():
            return {"documents": [], "conversations": []}
        try:
            provider = get_embedding_provider()
            qvec = (await provider.embed([query]))[0].vector
            hits = await get_vector_store().search(
                collection_name_for(ws.org_id), qvec, top_k=8,
                filters={"document_id": candidates},
            )
        except Exception as e:
            logger.warning(f"Related-document search unavailable: {e}")
            return {"documents": [], "conversations": []}

        seen: dict[str, float] = {}
        for h in hits:
            did = str(h.metadata.get("document_id", ""))
            if did and (did not in seen or h.score > seen[did]):
                seen[did] = h.score
        documents = []
        for did, score in sorted(seen.items(), key=lambda kv: -kv[1])[:3]:
            doc = await self.repo.get_document(did)
            if doc is not None:
                documents.append({
                    "id": did, "filename": doc.original_filename,
                    "score": round(score, 4),
                })
        related_convs = []
        if documents:
            top_ids = {d["id"] for d in documents}
            for wc in await self.repo.conversations_for(ws.id):
                if wc.conversation_id == conversation_id:
                    continue
                attached = set(await self.repo.conversation_document_ids(wc.conversation_id))
                if attached & top_ids:
                    related_convs.append(
                        {"conversation_id": wc.conversation_id, "title": wc.title})
                if len(related_convs) >= 3:
                    break
        return {"documents": documents, "conversations": related_convs}

    # ── Timeline helper for downloads ────────────────────────────────────────

    async def record_download(self, ws: Workspace, artifact_id: str, title: str) -> None:
        await self.repo.add_timeline(
            ws.id, "artifact_downloaded", f"Downloaded {title}",
            ref_type="artifact", ref_id=artifact_id,
        )
        await self._db.commit()
