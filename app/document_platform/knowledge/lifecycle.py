"""
Knowledge Lifecycle (Objective 1).

Ten states with explicit transition rules. Knowledge is never physically
deleted — DELETED is a state, reached only from ARCHIVED, and even then the
row persists (soft state, matching the Document/soft-delete convention
already used across this platform). Every transition is auditable via a
KnowledgeEvent (events.py) — the manager itself never writes SQL.
"""
from __future__ import annotations

from enum import Enum


class KnowledgeLifecycle(str, Enum):
    DRAFT = "draft"
    PROCESSING = "processing"
    ACTIVE = "active"
    INDEXED = "indexed"
    EMBEDDED = "embedded"
    VERIFIED = "verified"
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    DELETED = "deleted"


# Allowed forward/lateral transitions. Enrichment states (INDEXED, EMBEDDED,
# VERIFIED) are reachable from ACTIVE in any order — a document can be
# embedded before it's indexed, or verified without ever being embedded —
# so they all point back to each other rather than forming a strict chain.
_ENRICHED = {
    KnowledgeLifecycle.INDEXED,
    KnowledgeLifecycle.EMBEDDED,
    KnowledgeLifecycle.VERIFIED,
}

ALLOWED_TRANSITIONS: dict[KnowledgeLifecycle, frozenset[KnowledgeLifecycle]] = {
    KnowledgeLifecycle.DRAFT: frozenset({KnowledgeLifecycle.PROCESSING}),
    KnowledgeLifecycle.PROCESSING: frozenset({
        KnowledgeLifecycle.ACTIVE, KnowledgeLifecycle.DRAFT,  # DRAFT = reprocessing restart
    }),
    KnowledgeLifecycle.ACTIVE: frozenset(
        _ENRICHED | {KnowledgeLifecycle.DEPRECATED, KnowledgeLifecycle.PROCESSING}
    ),
    KnowledgeLifecycle.INDEXED: frozenset(
        (_ENRICHED - {KnowledgeLifecycle.INDEXED}) | {KnowledgeLifecycle.DEPRECATED, KnowledgeLifecycle.PROCESSING}
    ),
    KnowledgeLifecycle.EMBEDDED: frozenset(
        (_ENRICHED - {KnowledgeLifecycle.EMBEDDED}) | {KnowledgeLifecycle.DEPRECATED, KnowledgeLifecycle.PROCESSING}
    ),
    KnowledgeLifecycle.VERIFIED: frozenset(
        (_ENRICHED - {KnowledgeLifecycle.VERIFIED}) | {KnowledgeLifecycle.DEPRECATED, KnowledgeLifecycle.PROCESSING}
    ),
    KnowledgeLifecycle.DEPRECATED: frozenset({
        KnowledgeLifecycle.SUPERSEDED, KnowledgeLifecycle.ARCHIVED, KnowledgeLifecycle.ACTIVE,  # un-deprecate
    }),
    KnowledgeLifecycle.SUPERSEDED: frozenset({KnowledgeLifecycle.ARCHIVED}),
    KnowledgeLifecycle.ARCHIVED: frozenset({KnowledgeLifecycle.DELETED, KnowledgeLifecycle.ACTIVE}),  # restore
    KnowledgeLifecycle.DELETED: frozenset(),  # terminal
}


class InvalidLifecycleTransition(Exception):
    def __init__(self, current: KnowledgeLifecycle, target: KnowledgeLifecycle) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition knowledge from '{current.value}' to '{target.value}'")


def validate_transition(current: KnowledgeLifecycle, target: KnowledgeLifecycle) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidLifecycleTransition(current, target)


def is_terminal(state: KnowledgeLifecycle) -> bool:
    return not ALLOWED_TRANSITIONS.get(state)
