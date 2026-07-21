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
    EXPIRED = "expired"
    DELETED = "deleted"


ALLOWED_TRANSITIONS: dict[GenerationLifecycle, set[GenerationLifecycle]] = {
    GenerationLifecycle.REQUESTED: {GenerationLifecycle.PLANNING, GenerationLifecycle.FAILED},
    GenerationLifecycle.PLANNING: {GenerationLifecycle.TRANSFORMING, GenerationLifecycle.FAILED},
    GenerationLifecycle.TRANSFORMING: {GenerationLifecycle.BUILDING, GenerationLifecycle.FAILED},
    GenerationLifecycle.BUILDING: {GenerationLifecycle.STORING, GenerationLifecycle.FAILED},
    GenerationLifecycle.STORING: {GenerationLifecycle.READY, GenerationLifecycle.FAILED},
    GenerationLifecycle.READY: {GenerationLifecycle.EXPIRED, GenerationLifecycle.DELETED},
    GenerationLifecycle.EXPIRED: {GenerationLifecycle.DELETED},
    GenerationLifecycle.FAILED: set(),
    GenerationLifecycle.DELETED: set(),
}


class InvalidGenerationTransition(Exception):
    pass


def validate_transition(current: GenerationLifecycle, new: GenerationLifecycle) -> None:
    if new not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidGenerationTransition(f"{current.value} → {new.value} is not allowed")
