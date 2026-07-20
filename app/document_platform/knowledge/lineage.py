"""
Knowledge Lineage (Objective 8) — a generic provenance graph.

Deliberately generic (node_type + node_id, not typed foreign keys per node
type) so future node types — Embedding, RetrievalResult, ReasoningStep,
GeneratedAnswer, GeneratedDocument — attach without a schema change. Today
only two edge types are actually recorded (Document→KnowledgeObject and
KnowledgeObject→Chunk); the mechanism is proven end-to-end so later phases
just call `record()` for their own node types.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class LineageNodeType:
    """String constants, not an enum — future phases add new node type
    strings without touching this module (an enum would need editing here
    for every new AI subsystem, which defeats the point of "plug in without
    modifying existing services")."""
    DOCUMENT = "document"
    SECTION = "section"
    CHUNK = "chunk"
    KNOWLEDGE_OBJECT = "knowledge_object"
    EMBEDDING = "embedding"          # Phase 3+
    RETRIEVAL_RESULT = "retrieval_result"  # Phase 3+
    REASONING_STEP = "reasoning_step"      # Phase 4+
    GENERATED_ANSWER = "generated_answer"  # Phase 4+
    GENERATED_DOCUMENT = "generated_document"  # Phase 4+


@dataclass(frozen=True)
class LineageEdge:
    node_type: str
    node_id: str
    parent_type: Optional[str]
    parent_id: Optional[str]
    correlation_id: str


class LineageTracker:
    """Thin service over the repository — records and traces provenance edges."""

    def __init__(self, repo) -> None:  # KnowledgeManifestRepository — avoid import cycle
        self._repo = repo

    async def record(
        self,
        node_type: str,
        node_id: str,
        parent_type: Optional[str],
        parent_id: Optional[str],
        correlation_id: str,
    ) -> None:
        await self._repo.add_lineage_edge(LineageEdge(
            node_type=node_type, node_id=node_id,
            parent_type=parent_type, parent_id=parent_id,
            correlation_id=correlation_id,
        ))

    async def trace_to_origin(self, node_type: str, node_id: str) -> list[dict]:
        """Walk parent edges up to the root, answering 'where did this come from?'."""
        chain: list[dict] = []
        current_type, current_id = node_type, node_id
        seen: set[tuple[str, str]] = set()
        while current_type and current_id and (current_type, current_id) not in seen:
            seen.add((current_type, current_id))
            edge = await self._repo.get_lineage_parent(current_type, current_id)
            if edge is None:
                break
            chain.append({
                "node_type": edge.node_type, "node_id": edge.node_id,
                "parent_type": edge.parent_type, "parent_id": edge.parent_id,
            })
            current_type, current_id = edge.parent_type, edge.parent_id
        return chain
