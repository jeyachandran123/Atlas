"""Workspace Search (Objective 11) — one query across documents,
conversations, turns, artifacts, timeline, and semantic chunk content.
SQL matching comes from the repository; semantic hits reuse the existing
embedding provider + vector store search scoped to the workspace's
documents via the $in filter."""
from __future__ import annotations

from typing import Any

from loguru import logger

from app.document_platform.semantic.providers import get_embedding_provider
from app.document_platform.semantic.vector_store import (
    collection_name_for,
    get_vector_store,
)
from app.workspace.repository import WorkspaceRepository


class WorkspaceSearch:
    def __init__(self, repo: WorkspaceRepository) -> None:
        self._repo = repo

    async def search(self, workspace_id: str, org_id: str, q: str) -> dict[str, Any]:
        results: dict[str, Any] = {
            "documents": [], "conversations": [], "turns": [],
            "artifacts": [], "timeline": [], "chunks": [],
        }
        results["documents"] = [
            {"id": d.id, "filename": d.original_filename,
             "processing_status": d.processing_status}
            for d in await self._repo.search_documents(workspace_id, q)
        ]
        results["conversations"] = [
            {"conversation_id": c.conversation_id, "title": c.title}
            for c in await self._repo.search_conversations(workspace_id, q)
        ]
        results["turns"] = [
            {"conversation_id": t.conversation_id, "turn_id": t.id,
             "question": t.question[:200], "conversation_title": title,
             "answer_snippet": (t.answer or "")[:200]}
            for t, title in await self._repo.search_turns(workspace_id, q)
        ]
        results["artifacts"] = [
            {"id": a.id, "title": a.title, "filename": a.filename,
             "format": a.format, "status": a.status}
            for a in await self._repo.search_artifacts(workspace_id, q)
        ]
        results["timeline"] = [
            {"event_type": e.event_type, "title": e.title,
             "created_at": e.created_at.isoformat()}
            for e in await self._repo.search_timeline(workspace_id, q)
        ]

        # Semantic content search inside the workspace's documents.
        doc_ids = await self._repo.document_ids_for(workspace_id)
        if doc_ids:
            try:
                provider = get_embedding_provider()
                qvec = (await provider.embed([q]))[0].vector
                hits = await get_vector_store().search(
                    collection_name_for(org_id), qvec, top_k=6,
                    filters={"document_id": doc_ids},
                )
                results["chunks"] = [
                    {"document_id": str(h.metadata.get("document_id", "")),
                     "section": str(h.metadata.get("section_path", "")),
                     "snippet": h.text[:240], "score": round(h.score, 4)}
                    for h in hits
                ]
            except Exception as e:
                logger.warning(f"Semantic workspace search unavailable: {e}")
        return results
