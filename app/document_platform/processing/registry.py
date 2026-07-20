"""
Knowledge Registry (Objective 10).

The single source of truth every future AI subsystem (Document AI, Vision AI,
Coding AI, Knowledge AI, Meeting AI, Automation AI) reads Knowledge Objects
through — never raw storage directly. `persistence.py` still owns the SQL;
this is the semantic façade: registering (not just storing) means writing
the object AND making its lifecycle status queryable and updatable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.db.models import KnowledgeObject
from app.document_platform.processing.chunker import Chunk
from app.document_platform.processing.events import EventPublisher, ProcessingEvent, ProcessingEventType
from app.document_platform.processing.images import StoredImage
from app.document_platform.processing.knowledge import BuiltKnowledgeObject
from app.document_platform.processing.metadata import ExtractedMetadata
from app.document_platform.processing.persistence import ProcessingRepository


@dataclass(frozen=True)
class RegistryEntry:
    """Read-model view of a registered Knowledge Object — what consumers see."""
    knowledge_id: str
    document_id: str
    parser_version: str
    chunk_version: str
    processing_version: str
    schema_version: str
    language: str
    status: str
    embedding_status: str
    index_status: str
    retrieval_status: str
    generation_status: str
    parent_knowledge_id: Optional[str]

    @classmethod
    def from_model(cls, ko: KnowledgeObject) -> "RegistryEntry":
        return cls(
            knowledge_id=ko.id,
            document_id=ko.document_id,
            parser_version=ko.parser_version,
            chunk_version=ko.chunk_version,
            processing_version=ko.processing_version,
            schema_version=ko.schema_version,
            language=ko.language,
            status=ko.status,
            embedding_status=ko.embedding_status,
            index_status=ko.index_status,
            retrieval_status=ko.retrieval_status,
            generation_status=ko.generation_status,
            parent_knowledge_id=ko.parent_knowledge_id,
        )


_STATUS_FIELDS = {"embedding_status", "index_status", "retrieval_status", "generation_status", "status"}


class KnowledgeRegistry:
    def __init__(self, repo: ProcessingRepository, events: Optional[EventPublisher] = None) -> None:
        self._repo = repo
        self._events = events

    async def register(
        self,
        *,
        document_id: str,
        built: BuiltKnowledgeObject,
        metadata: ExtractedMetadata,
        language: str,
        stored_images: list[StoredImage],
        chunks: list[Chunk],
        parser_version: str,
        chunk_version: str,
        processing_version: str,
        schema_version: str,
        job_id: str,
        correlation_id: str,
    ) -> RegistryEntry:
        ko = await self._repo.persist_knowledge(
            document_id, built, metadata, language, stored_images, chunks,
            parser_version=parser_version,
            chunk_version=chunk_version,
            processing_version=processing_version,
            schema_version=schema_version,
        )
        entry = RegistryEntry.from_model(ko)
        if self._events:
            await self._events.publish(job_id, ProcessingEvent(
                event_type=ProcessingEventType.KNOWLEDGE_REGISTERED,
                document_id=document_id,
                correlation_id=correlation_id,
                stage="knowledge_registered",
                detail={"knowledge_id": ko.id, "processing_version": processing_version},
            ))
        return entry

    async def get(self, document_id: str) -> Optional[RegistryEntry]:
        ko = await self._repo.knowledge_for(document_id)
        return RegistryEntry.from_model(ko) if ko else None

    async def update_status(self, document_id: str, **statuses: str) -> None:
        """
        Flip one or more lifecycle status fields (embedding_status,
        index_status, retrieval_status, generation_status, status). Future
        phases (embeddings, indexing, retrieval, generation) call this
        instead of writing to knowledge_objects directly.
        """
        unknown = set(statuses) - _STATUS_FIELDS
        if unknown:
            raise ValueError(f"Unknown registry status field(s): {unknown}")
        ko = await self._repo.knowledge_for(document_id)
        if ko is None:
            raise ValueError(f"No knowledge object registered for document {document_id}")
        for field_name, value in statuses.items():
            setattr(ko, field_name, value)
        await self._repo.db.flush()
