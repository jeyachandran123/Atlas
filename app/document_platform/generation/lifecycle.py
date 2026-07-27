"""Generation Lifecycle (Objective 18) — validated transitions, same
discipline as the embedding lifecycle."""
from __future__ import annotations

from enum import Enum


class GenerationLifecycle(str, Enum):
    REQUESTED = "requested"
    PLANNING = "planning"
    TRANSFORMING = "transforming"
    BUILDING = "building"
    STORING = "storing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    DELETED = "deleted"


# CANCELLED is reachable from any in-flight state — the Product Experience Layer
# marks it when the user presses Stop and the SSE stream is aborted (client
# disconnect). It is terminal, like FAILED. This is additive: the frozen
# pipeline never transitions here itself; only the workspace layer does.
ALLOWED_TRANSITIONS: dict[GenerationLifecycle, set[GenerationLifecycle]] = {
    GenerationLifecycle.REQUESTED: {GenerationLifecycle.PLANNING, GenerationLifecycle.FAILED, GenerationLifecycle.CANCELLED},
    GenerationLifecycle.PLANNING: {GenerationLifecycle.TRANSFORMING, GenerationLifecycle.FAILED, GenerationLifecycle.CANCELLED},
    GenerationLifecycle.TRANSFORMING: {GenerationLifecycle.BUILDING, GenerationLifecycle.FAILED, GenerationLifecycle.CANCELLED},
    GenerationLifecycle.BUILDING: {GenerationLifecycle.STORING, GenerationLifecycle.FAILED, GenerationLifecycle.CANCELLED},
    GenerationLifecycle.STORING: {GenerationLifecycle.READY, GenerationLifecycle.FAILED, GenerationLifecycle.CANCELLED},
    GenerationLifecycle.READY: {GenerationLifecycle.EXPIRED, GenerationLifecycle.DELETED},
    GenerationLifecycle.EXPIRED: {GenerationLifecycle.DELETED},
    GenerationLifecycle.FAILED: set(),
    GenerationLifecycle.CANCELLED: {GenerationLifecycle.DELETED},
    GenerationLifecycle.DELETED: set(),
}


class InvalidGenerationTransition(Exception):
    pass


def validate_transition(current: GenerationLifecycle, new: GenerationLifecycle) -> None:
    if new not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidGenerationTransition(f"{current.value} → {new.value} is not allowed")
