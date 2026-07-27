"""Checkpoint infrastructure — persistence only, no interpretation.

Future engines persist opaque snapshots (working memory, goals, plans,
reasoning, prediction, reflection, learning) here. The store saves the ``blob``
verbatim, verifies its integrity seal on load, and tracks lineage — but never
interprets contents (that is the owning engine's concern). Checkpoints are
consistent with a ledger position (Phase 1.5 Ch10).
"""

from __future__ import annotations

import hashlib
import threading

from .contracts import Checkpoint, CheckpointStore
from .errors import CheckpointError


def seal(blob: bytes) -> str:
    """Compute the integrity digest for a checkpoint blob."""
    return hashlib.sha256(blob).hexdigest()


class InMemoryCheckpointStore(CheckpointStore):
    def __init__(self) -> None:
        self._by_id: dict[str, Checkpoint] = {}
        self._by_owner: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    def save(self, checkpoint: Checkpoint) -> None:
        if seal(checkpoint.blob) != checkpoint.digest:
            raise CheckpointError(f"Checkpoint {checkpoint.checkpoint_id} failed integrity seal")
        with self._lock:
            self._by_id[checkpoint.checkpoint_id] = checkpoint
            self._by_owner.setdefault(checkpoint.owner, []).append(checkpoint.checkpoint_id)

    def load(self, checkpoint_id: str) -> Checkpoint:
        with self._lock:
            cp = self._by_id.get(checkpoint_id)
        if cp is None:
            raise CheckpointError(f"Unknown checkpoint: {checkpoint_id}")
        if seal(cp.blob) != cp.digest:
            raise CheckpointError(f"Checkpoint {checkpoint_id} is corrupt")
        return cp

    def latest(self, owner: str) -> Checkpoint | None:
        with self._lock:
            ids = list(self._by_owner.get(owner, []))
            candidates = [self._by_id[i] for i in ids]
        if not candidates:
            return None
        # Latest by ledger sequence, then creation time (deterministic).
        return max(candidates, key=lambda c: (c.sequence, c.created_at))

    def list(self, owner: str | None = None) -> list[Checkpoint]:
        with self._lock:
            values = list(self._by_id.values())
        if owner is not None:
            values = [c for c in values if c.owner == owner]
        return sorted(values, key=lambda c: (c.sequence, c.created_at))
