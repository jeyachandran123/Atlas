"""Workspace Memory (Objective 6) — a COMPUTED read-model over what the
frozen platforms already store, plus the workspace's own timeline/summary.
Deliberately not a table: no duplicated state, nothing to drift."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.workspace.repository import WorkspaceRepository


@dataclass(frozen=True)
class WorkspaceMemory:
    workspace_id: str
    stats: dict[str, int]
    documents: list[dict[str, Any]] = field(default_factory=list)
    conversations: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    recent_activity: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""


async def build_workspace_memory(
    repo: WorkspaceRepository, workspace_id: str, activity_limit: int = 20,
) -> WorkspaceMemory:
    stats = await repo.stats(workspace_id)
    documents = [
        {"id": d.id, "filename": d.original_filename,
         "processing_status": d.processing_status, "created_at": d.created_at.isoformat()}
        for d in await repo.documents_for(workspace_id)
    ]
    conversations = [
        {"conversation_id": c.conversation_id, "title": c.title,
         "updated_at": c.updated_at.isoformat()}
        for c in await repo.conversations_for(workspace_id)
    ]
    artifacts = [
        {"id": a.id, "title": a.title, "format": a.format, "status": a.status,
         "conversation_id": conv_id}
        for a, conv_id in await repo.artifacts_for(workspace_id)
    ]
    activity = [
        {"event_type": e.event_type, "title": e.title, "created_at": e.created_at.isoformat()}
        for e in await repo.timeline_for(workspace_id, limit=activity_limit)
    ]
    summary_row = await repo.get_summary(workspace_id)
    return WorkspaceMemory(
        workspace_id=workspace_id, stats=stats, documents=documents,
        conversations=conversations, artifacts=artifacts,
        recent_activity=activity,
        summary=summary_row.summary if summary_row else "",
    )
