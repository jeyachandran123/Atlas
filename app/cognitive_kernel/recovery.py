"""Recovery infrastructure.

Supports crash/restart recovery, checkpoint recovery, ledger replay, safe
rollback, and graceful shutdown — always preserving constitutional integrity
(a recovery that cannot restore a consistent, identity-bearing state fails
rather than proceeding). Recovery performs no interpretation; it verifies,
replays, and hands sealed checkpoints back to their owning engines.
"""

from __future__ import annotations

from .contracts import (
    CheckpointStore,
    CognitiveEvent,
    EventHandler,
    IdentityProvider,
    Ledger,
)
from .errors import RecoveryError


class RecoveryManager:
    def __init__(
        self,
        ledger: Ledger,
        checkpoints: CheckpointStore,
        identity: IdentityProvider,
    ) -> None:
        self._ledger = ledger
        self._checkpoints = checkpoints
        self._identity = identity

    def verify_integrity(self) -> None:
        """Constitutional integrity gate for any recovery (P12/DeL1/RL8)."""
        if not self._ledger.verify():
            raise RecoveryError("Ledger integrity check failed; refusing to recover.")
        if not self._identity.is_established():
            raise RecoveryError("Identity not established; refusing to recover (DeL1).")

    def replay(self, handler: EventHandler, *, since: int = 0) -> int:
        """Deterministically rebuild state by replaying the ledger (RL8).

        Replay reads the immutable ledger and drives ``handler`` directly. It
        does NOT re-publish through the recording bus, so history is never
        double-recorded.
        """
        self.verify_integrity()
        count = 0
        for entry in self._ledger.read(since=since):
            handler(entry.event)
            count += 1
        return count

    def restore_checkpoint(self, owner: str):
        """Return the latest sealed checkpoint for an engine (or ``None``)."""
        return self._checkpoints.latest(owner)

    def last_position(self) -> int:
        return self._ledger.head()
