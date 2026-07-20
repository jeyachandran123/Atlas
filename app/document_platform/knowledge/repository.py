"""
All SQL for the Knowledge Platform layer (manifests, knowledge events,
lineage edges) lives here — services (LifecycleManager, LineageTracker,
event publishers) never issue queries themselves.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeEventRecord, KnowledgeLineageEdge, KnowledgeManifest
from app.document_platform.knowledge.events import KnowledgeEvent
from app.document_platform.knowledge.lineage import LineageEdge


class KnowledgeManifestRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @property
    def db(self) -> AsyncSession:
        return self._db

    # ── Manifest ─────────────────────────────────────────────────────────────

    async def create_manifest(self, manifest: KnowledgeManifest) -> KnowledgeManifest:
        self._db.add(manifest)
        await self._db.flush()
        return manifest

    async def get_by_knowledge_id(self, knowledge_object_id: str) -> Optional[KnowledgeManifest]:
        return (
            await self._db.execute(
                select(KnowledgeManifest).where(
                    KnowledgeManifest.knowledge_object_id == knowledge_object_id
                )
            )
        ).scalar_one_or_none()

    async def get_by_document_id(self, document_id: str) -> Optional[KnowledgeManifest]:
        return (
            await self._db.execute(
                select(KnowledgeManifest)
                .where(KnowledgeManifest.document_id == document_id)
                .order_by(KnowledgeManifest.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def delete_manifests_for_document(self, document_id: str) -> None:
        """Idempotent reprocessing support — mirrors ProcessingRepository.wipe_derived."""
        from sqlalchemy import delete
        await self._db.execute(
            delete(KnowledgeManifest).where(KnowledgeManifest.document_id == document_id)
        )
        await self._db.flush()

    # ── Knowledge events ─────────────────────────────────────────────────────

    async def add_knowledge_event(self, event: KnowledgeEvent) -> None:
        self._db.add(KnowledgeEventRecord(
            event_type=event.event_type.value,
            knowledge_id=event.knowledge_id,
            document_id=event.document_id,
            correlation_id=event.correlation_id,
            previous_state=event.previous_state.value if event.previous_state else None,
            current_state=event.current_state.value if event.current_state else None,
            version=event.version,
            source=event.source,
            metadata_json=json.dumps(event.metadata) if event.metadata else None,
            warnings_json=json.dumps(event.warnings) if event.warnings else None,
            errors_json=json.dumps(event.errors) if event.errors else None,
        ))
        await self._db.flush()

    async def list_knowledge_events(self, knowledge_id: str) -> list[KnowledgeEventRecord]:
        rows = (
            await self._db.execute(
                select(KnowledgeEventRecord)
                .where(KnowledgeEventRecord.knowledge_id == knowledge_id)
                .order_by(KnowledgeEventRecord.created_at)
            )
        ).scalars().all()
        return list(rows)

    # ── Lineage ──────────────────────────────────────────────────────────────

    async def add_lineage_edge(self, edge: LineageEdge) -> None:
        self._db.add(KnowledgeLineageEdge(
            node_type=edge.node_type,
            node_id=edge.node_id,
            parent_type=edge.parent_type,
            parent_id=edge.parent_id,
            correlation_id=edge.correlation_id,
        ))
        await self._db.flush()

    async def get_lineage_parent(self, node_type: str, node_id: str) -> Optional[LineageEdge]:
        row = (
            await self._db.execute(
                select(KnowledgeLineageEdge)
                .where(
                    KnowledgeLineageEdge.node_type == node_type,
                    KnowledgeLineageEdge.node_id == node_id,
                )
                .order_by(KnowledgeLineageEdge.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return LineageEdge(
            node_type=row.node_type, node_id=row.node_id,
            parent_type=row.parent_type, parent_id=row.parent_id,
            correlation_id=row.correlation_id,
        )
