"""Working Memory reference objects — R4 payload helpers (references only, OL7).

A WM reference is a Cognitive-State object (ObjectType.WORKING_MEMORY_REF, Region
R4) whose payload holds the *target handle* and ephemeral-activation metadata. It
ACTIVATES the target (a relationship edge), it never copies it.
"""

from __future__ import annotations

from typing import Any

from ...state import CognitiveObject
from ...state.contracts import ObjectType, RelationshipEdge, RelationshipType
from .contracts import Slot, Zone

WM_REF_TYPE = ObjectType.WORKING_MEMORY_REF


def build_payload(
    *,
    target: str,
    workspace: str,
    zone: Zone,
    base_activation: float,
    loaded_seq: int,
    pinned: bool = False,
    chunk_of: str | None = None,
    is_chunk: bool = False,
    provenance: str = "",
) -> dict[str, Any]:
    return {
        "target": target,
        "workspace": workspace,
        "zone": zone.value,
        "base_activation": base_activation,
        "loaded_seq": loaded_seq,
        "pinned": pinned,
        "chunk_of": chunk_of,
        "is_chunk": is_chunk,
        "provenance": provenance,
    }


def activation_edge(target: str) -> RelationshipEdge:
    return RelationshipEdge(RelationshipType.ACTIVATION, target)


def to_slot(obj: CognitiveObject) -> Slot:
    p = obj.payload
    return Slot(
        handle=obj.handle,
        target=p["target"],
        workspace=p["workspace"],
        zone=Zone(p["zone"]),
        base_activation=float(p["base_activation"]),
        loaded_seq=int(p["loaded_seq"]),
        pinned=bool(p.get("pinned", False)),
        chunk_of=p.get("chunk_of"),
        is_chunk=bool(p.get("is_chunk", False)),
        salience=obj.salience,
        confidence=obj.confidence,
    )
