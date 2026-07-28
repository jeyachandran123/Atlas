"""State diff engine — compute change tracking between object versions/snapshots."""

from __future__ import annotations

from typing import Any

from .contracts import CognitiveObject, RelationshipEdge, StateDiff, StateSnapshot

_FIELDS = ("status", "confidence", "salience", "provenance")


def diff_objects(old: CognitiveObject, new: CognitiveObject) -> StateDiff:
    changed: dict[str, tuple[Any, Any]] = {}
    for f in _FIELDS:
        ov, nv = getattr(old, f), getattr(new, f)
        if ov != nv:
            changed[f] = (ov, nv)
    # payload key-level diff
    okeys, nkeys = set(old.payload), set(new.payload)
    for k in okeys | nkeys:
        ov = old.payload.get(k)
        nv = new.payload.get(k)
        if ov != nv:
            changed[f"payload.{k}"] = (ov, nv)
    old_rels = set(old.relationships)
    new_rels = set(new.relationships)
    added = tuple(new_rels - old_rels)
    removed = tuple(old_rels - new_rels)
    return StateDiff(
        handle=old.handle,
        from_version=old.version,
        to_version=new.version,
        changed_fields=changed,
        added_relationships=added,
        removed_relationships=removed,
    )


def diff_snapshots(a: StateSnapshot, b: StateSnapshot) -> dict[str, Any]:
    """Structural diff between two snapshots: added/removed/changed objects."""
    a_map = {o.handle: o for o in a.objects}
    b_map = {o.handle: o for o in b.objects}
    added = sorted(set(b_map) - set(a_map))
    removed = sorted(set(a_map) - set(b_map))
    changed = []
    for h in sorted(set(a_map) & set(b_map)):
        if a_map[h].version != b_map[h].version or a_map[h] != b_map[h]:
            changed.append(diff_objects(a_map[h], b_map[h]))
    return {"added": added, "removed": removed, "changed": changed}
