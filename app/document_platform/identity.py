"""
Document Identity (Objective 7) — two identities per document.

Binary Identity is exact-match, already backed by real data (checksum
computed at upload — see validation.py). Content Identity is similarity/
structure-aware; two of its four signatures are honestly computable today
with zero AI (structure and language are deterministic outputs of the
processing pipeline); the other two genuinely require embeddings and stay
None — this module designs the interface Phase 3+ fills in, it does not
fake AI fingerprinting.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

from app.document_platform.processing.models import DocumentNode


@dataclass(frozen=True)
class BinaryIdentity:
    """Exact-match identity of the uploaded bytes. Backs duplicate detection today."""
    sha256: str
    size_bytes: int

    @property
    def binary_hash(self) -> str:
        """Alias for sha256 — the spec names both; they are the same value."""
        return self.sha256


@dataclass(frozen=True)
class ContentIdentity:
    """
    Similarity-aware identity, independent of exact byte layout (e.g. the
    same report re-exported as a different PDF should someday resolve to a
    related ContentIdentity even though its BinaryIdentity differs).
    """
    structure_signature: Optional[str] = None
    language_signature: Optional[str] = None
    semantic_fingerprint: Optional[str] = None   # requires embeddings — Phase 3+
    content_signature: Optional[str] = None       # requires embeddings — Phase 3+
    metadata_signature: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "structure_signature": self.structure_signature,
            "language_signature": self.language_signature,
            "semantic_fingerprint": self.semantic_fingerprint,
            "content_signature": self.content_signature,
            "metadata_signature": self.metadata_signature,
        }


class DocumentIdentityBuilder:
    """Builds both identities. No AI calls — deterministic hashing only."""

    def binary_identity(self, sha256: str, size_bytes: int) -> BinaryIdentity:
        return BinaryIdentity(sha256=sha256, size_bytes=size_bytes)

    def content_identity(
        self,
        tree: DocumentNode,
        language: str,
        metadata_custom: Optional[dict[str, Any]] = None,
    ) -> ContentIdentity:
        return ContentIdentity(
            structure_signature=self._structure_signature(tree),
            language_signature=language if language and language != "unknown" else None,
            semantic_fingerprint=None,   # Phase 3+: derived from chunk embeddings
            content_signature=None,      # Phase 3+: derived from full-document embedding
            metadata_signature=self._metadata_signature(metadata_custom),
        )

    @staticmethod
    def _structure_signature(tree: DocumentNode) -> str:
        """
        A stable fingerprint of the document's SHAPE (node types + nesting +
        order), deliberately excluding text content — two documents with
        identical structure but different wording hash the same, which is
        exactly the "same template, different data" case future duplicate
        detection needs.
        """
        def shape(node: DocumentNode) -> Any:
            return [node.type.value, [shape(c) for c in node.children]]

        payload = json.dumps(shape(tree), separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _metadata_signature(custom: Optional[dict[str, Any]]) -> Optional[str]:
        if not custom:
            return None
        payload = json.dumps(custom, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
