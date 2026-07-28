"""State serialization, snapshotting, and integrity digests.

Snapshots serialize the current object versions; the digest is a sha256 over the
canonical serialization (integrity verification). Used for checkpoints (kernel
CheckpointStore) and restoration.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Sequence

from .contracts import CognitiveObject, StateSnapshot
from .objects import from_dict, to_dict


def digest_objects(objects: Sequence[CognitiveObject]) -> str:
    ordered = sorted((to_dict(o) for o in objects), key=lambda d: (d["handle"], d["version"]))
    canonical = json.dumps(ordered, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def make_snapshot(objects: Sequence[CognitiveObject], seq: int) -> StateSnapshot:
    objs = tuple(objects)
    return StateSnapshot(
        snapshot_id=uuid.uuid4().hex,
        seq=seq,
        digest=digest_objects(objs),
        objects=objs,
    )


def serialize_snapshot(snapshot: StateSnapshot) -> bytes:
    return json.dumps(
        {
            "snapshot_id": snapshot.snapshot_id,
            "seq": snapshot.seq,
            "digest": snapshot.digest,
            "objects": [to_dict(o) for o in snapshot.objects],
            "created_at": snapshot.created_at.isoformat(),
        },
        sort_keys=True,
    ).encode("utf-8")


def deserialize_snapshot(blob: bytes) -> StateSnapshot:
    from datetime import datetime

    d = json.loads(blob.decode("utf-8"))
    objects = tuple(from_dict(o) for o in d["objects"])
    return StateSnapshot(
        snapshot_id=d["snapshot_id"],
        seq=int(d["seq"]),
        digest=d["digest"],
        objects=objects,
        created_at=datetime.fromisoformat(d["created_at"]),
    )
