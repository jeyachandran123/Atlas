"""
Embedding Lifecycle (Objective 10) — same pattern as
document_platform/knowledge/lifecycle.py, applied to individual embedding
records instead of Knowledge Objects.
"""
from __future__ import annotations

from enum import Enum


class EmbeddingLifecycle(str, Enum):
    QUEUED = "queued"
    GENERATING = "generating"
    VALIDATING = "validating"
    INDEXED = "indexed"
    VERIFIED = "verified"
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    DELETED = "deleted"


ALLOWED_TRANSITIONS: dict[EmbeddingLifecycle, frozenset[EmbeddingLifecycle]] = {
    EmbeddingLifecycle.QUEUED: frozenset({EmbeddingLifecycle.GENERATING}),
    EmbeddingLifecycle.GENERATING: frozenset({
        EmbeddingLifecycle.VALIDATING, EmbeddingLifecycle.QUEUED,  # QUEUED = retry restart
    }),
    EmbeddingLifecycle.VALIDATING: frozenset({
        EmbeddingLifecycle.INDEXED, EmbeddingLifecycle.QUEUED,  # failed validation -> retry
    }),
    EmbeddingLifecycle.INDEXED: frozenset({
        EmbeddingLifecycle.VERIFIED, EmbeddingLifecycle.DEPRECATED,
    }),
    EmbeddingLifecycle.VERIFIED: frozenset({
        EmbeddingLifecycle.DEPRECATED, EmbeddingLifecycle.QUEUED,  # QUEUED = re-embed on demand
    }),
    EmbeddingLifecycle.DEPRECATED: frozenset({
        EmbeddingLifecycle.SUPERSEDED, EmbeddingLifecycle.ARCHIVED, EmbeddingLifecycle.VERIFIED,
    }),
    EmbeddingLifecycle.SUPERSEDED: frozenset({EmbeddingLifecycle.ARCHIVED}),
    EmbeddingLifecycle.ARCHIVED: frozenset({EmbeddingLifecycle.DELETED, EmbeddingLifecycle.VERIFIED}),
    EmbeddingLifecycle.DELETED: frozenset(),  # terminal
}


class InvalidEmbeddingTransition(Exception):
    def __init__(self, current: EmbeddingLifecycle, target: EmbeddingLifecycle) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition embedding from '{current.value}' to '{target.value}'")


def validate_transition(current: EmbeddingLifecycle, target: EmbeddingLifecycle) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidEmbeddingTransition(current, target)


def is_terminal(state: EmbeddingLifecycle) -> bool:
    return not ALLOWED_TRANSITIONS.get(state)
