"""
KnowledgeManifestService — the LifecycleManager for Objective 1, wired to
Objective 2's event domain. Every lifecycle transition is validated against
the allowed-transition table and emits an audited KnowledgeEvent; nothing
else in the platform is allowed to write `lifecycle_state` directly.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.db.models import KnowledgeManifest
from app.document_platform.identity import ContentIdentity
from app.document_platform.knowledge.events import (
    KnowledgeEvent,
    KnowledgeEventPublisher,
    KnowledgeEventType,
)
from app.document_platform.knowledge.lifecycle import KnowledgeLifecycle, validate_transition
from app.document_platform.knowledge.repository import KnowledgeManifestRepository


class KnowledgeManifestService:
    def __init__(self, repo: KnowledgeManifestRepository, events: KnowledgeEventPublisher) -> None:
        self._repo = repo
        self._events = events

    async def register(
        self,
        *,
        document_id: str,
        knowledge_object_id: str,
        parser_name: str,
        parser_version: str,
        chunk_version: str,
        processing_version: str,
        schema_version: str,
        correlation_id: str,
        content_identity: ContentIdentity,
        capabilities_snapshot: dict[str, str],
        warnings: list[str],
        retry_count: int,
        embedding_version: str = "1.0.0",
        relationship_version: str = "1.0.0",
        source: str = "orchestrator",
    ) -> KnowledgeManifest:
        """
        Creates the manifest and immediately walks it DRAFT → PROCESSING →
        ACTIVE. All three transitions are real (validated + audited) even
        though they happen back-to-back here — by the time this is called,
        the pipeline has already validated the Knowledge Object, so the
        manifest is describing work that already succeeded.
        """
        manifest = KnowledgeManifest(
            knowledge_object_id=knowledge_object_id,
            document_id=document_id,
            lifecycle_state=KnowledgeLifecycle.DRAFT.value,
            parser_name=parser_name,
            parser_version=parser_version,
            chunk_version=chunk_version,
            embedding_version=embedding_version,
            knowledge_version=1,
            relationship_version=relationship_version,
            schema_version=schema_version,
            processing_version=processing_version,
            validation_status="passed",
            current_stage="persist",
            capabilities_json=json.dumps(capabilities_snapshot),
            warnings_json=json.dumps(warnings) if warnings else None,
            retry_count=retry_count,
            content_identity_json=json.dumps(content_identity.to_dict()),
            correlation_id=correlation_id,
        )
        await self._repo.create_manifest(manifest)
        await self._events.publish(KnowledgeEvent(
            event_type=KnowledgeEventType.CREATED,
            knowledge_id=knowledge_object_id, document_id=document_id, correlation_id=correlation_id,
            current_state=KnowledgeLifecycle.DRAFT, source=source,
        ))

        await self.transition(manifest, KnowledgeLifecycle.PROCESSING, KnowledgeEventType.UPDATED, correlation_id, source)
        await self.transition(manifest, KnowledgeLifecycle.ACTIVE, KnowledgeEventType.ACTIVATED, correlation_id, source)
        return manifest

    async def transition(
        self,
        manifest: KnowledgeManifest,
        target: KnowledgeLifecycle,
        event_type: KnowledgeEventType,
        correlation_id: str,
        source: str = "system",
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        current = KnowledgeLifecycle(manifest.lifecycle_state)
        validate_transition(current, target)
        manifest.lifecycle_state = target.value
        await self._repo.db.flush()
        await self._events.publish(KnowledgeEvent(
            event_type=event_type,
            knowledge_id=manifest.knowledge_object_id, document_id=manifest.document_id,
            correlation_id=correlation_id, previous_state=current, current_state=target,
            source=source, metadata=metadata or {},
        ))

    async def get_for_document(self, document_id: str) -> Optional[KnowledgeManifest]:
        return await self._repo.get_by_document_id(document_id)
