"""CognitiveObject construction, evolution, and (de)serialization.

Every mutation produces a NEW immutable version (OL4). Serialization is used for
snapshots, checkpoints, and ledger events (RL8 event-sourced reconstruction).
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import (
    IMMUTABLE_TYPES,
    TYPE_REGION,
    CognitiveObject,
    ObjectStatus,
    ObjectType,
    Region,
    RelationshipEdge,
    RelationshipType,
)
from .errors import ImmutableObjectError, PlacementError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_object(
    handle: str,
    type: ObjectType,
    *,
    payload: Mapping[str, Any] | None = None,
    status: ObjectStatus = ObjectStatus.PROPOSED,
    confidence: float | None = None,
    salience: float = 0.0,
    relationships: tuple[RelationshipEdge, ...] = (),
    provenance: str = "",
    seq: int = 0,
) -> CognitiveObject:
    """Create version 1 of a cognitive object, enforcing placement + immutability."""
    region = TYPE_REGION.get(type)
    if region is None:
        raise PlacementError(f"Unknown object type has no Region: {type}")
    return CognitiveObject(
        handle=handle,
        type=type,
        region=region,
        version=1,
        status=status,
        immutable=type in IMMUTABLE_TYPES,
        payload=MappingProxyType(dict(payload or {})),
        confidence=confidence,
        salience=salience,
        relationships=tuple(relationships),
        provenance=provenance,
        created_seq=seq,
        modified_seq=seq,
        created_at=_now(),
        modified_at=_now(),
    )


def evolve(
    current: CognitiveObject,
    *,
    payload_merge: Mapping[str, Any] | None = None,
    payload_replace: Mapping[str, Any] | None = None,
    status: ObjectStatus | None = None,
    confidence: float | None = None,
    salience: float | None = None,
    add_relationships: tuple[RelationshipEdge, ...] = (),
    remove_relationships: tuple[RelationshipEdge, ...] = (),
    provenance: str = "",
    seq: int = 0,
    _allow_immutable: bool = False,
) -> CognitiveObject:
    """Produce the next version of an object.

    In-place evolution of an immutable object is refused unless ``_allow_immutable``
    (reserved for the constitutionally-gated identity-evolution path used by a
    future Learning engine, never by ordinary writers).
    """
    if current.immutable and not _allow_immutable:
        raise ImmutableObjectError(
            f"{current.type.value} objects are immutable and cannot be edited in place "
            f"(supersede with a new object instead)."
        )
    if payload_replace is not None:
        new_payload: dict[str, Any] = dict(payload_replace)
    else:
        new_payload = dict(current.payload)
        if payload_merge:
            new_payload.update(payload_merge)

    rels = [r for r in current.relationships if r not in remove_relationships]
    for r in add_relationships:
        if r not in rels:
            rels.append(r)

    return CognitiveObject(
        handle=current.handle,
        type=current.type,
        region=current.region,
        version=current.version + 1,
        status=status if status is not None else current.status,
        immutable=current.immutable,
        payload=MappingProxyType(new_payload),
        confidence=confidence if confidence is not None else current.confidence,
        salience=salience if salience is not None else current.salience,
        relationships=tuple(rels),
        provenance=provenance or current.provenance,
        created_seq=current.created_seq,
        modified_seq=seq,
        created_at=current.created_at,
        modified_at=_now(),
    )


# --------------------------------------------------------------------------- #
# Serialization (deterministic; JSON-friendly)
# --------------------------------------------------------------------------- #


def to_dict(obj: CognitiveObject) -> dict[str, Any]:
    return {
        "handle": obj.handle,
        "type": obj.type.value,
        "region": obj.region.value,
        "version": obj.version,
        "status": obj.status.value,
        "immutable": obj.immutable,
        "payload": dict(obj.payload),
        "confidence": obj.confidence,
        "salience": obj.salience,
        "relationships": [
            {"rel": r.rel_type.value, "target": r.target, "weight": r.weight}
            for r in obj.relationships
        ],
        "provenance": obj.provenance,
        "created_seq": obj.created_seq,
        "modified_seq": obj.modified_seq,
        "created_at": obj.created_at.isoformat(),
        "modified_at": obj.modified_at.isoformat(),
    }


def from_dict(d: Mapping[str, Any]) -> CognitiveObject:
    return CognitiveObject(
        handle=d["handle"],
        type=ObjectType(d["type"]),
        region=Region(d["region"]),
        version=int(d["version"]),
        status=ObjectStatus(d["status"]),
        immutable=bool(d["immutable"]),
        payload=MappingProxyType(dict(d["payload"])),
        confidence=d["confidence"],
        salience=d["salience"],
        relationships=tuple(
            RelationshipEdge(RelationshipType(r["rel"]), r["target"], r["weight"])
            for r in d["relationships"]
        ),
        provenance=d["provenance"],
        created_seq=int(d["created_seq"]),
        modified_seq=int(d["modified_seq"]),
        created_at=datetime.fromisoformat(d["created_at"]),
        modified_at=datetime.fromisoformat(d["modified_at"]),
    )
