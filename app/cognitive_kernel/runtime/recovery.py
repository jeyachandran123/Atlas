"""Execution checkpointing & recovery — built on the kernel infrastructure.

The runtime (not the engine) knows *where an execution stopped*: it snapshots
execution position into the kernel's :class:`CheckpointStore` and recovers via
the kernel's ledger replay (RL8). Recovery is deterministic and de-duplicated:
completed executions are never re-run.
"""

from __future__ import annotations

import json

from ..checkpoint import seal
from ..contracts import Checkpoint, EventHandler, KernelServices
from ..recovery import RecoveryManager
from .contracts import ExecutionSnapshot, ExecutionState


def _snapshot_to_bytes(s: ExecutionSnapshot) -> bytes:
    return json.dumps(
        {
            "execution_id": s.execution_id,
            "engine": s.engine,
            "operation": s.operation,
            "state": s.state.value,
            "attempts": s.attempts,
            "parent_id": s.parent_id,
            "correlation_id": s.correlation_id,
            "ledger_head": s.ledger_head,
            "created_at": s.created_at,
        },
        sort_keys=True,
    ).encode("utf-8")


def _snapshot_from_bytes(b: bytes) -> ExecutionSnapshot:
    d = json.loads(b.decode("utf-8"))
    return ExecutionSnapshot(
        execution_id=d["execution_id"],
        engine=d["engine"],
        operation=d["operation"],
        state=ExecutionState(d["state"]),
        attempts=d["attempts"],
        parent_id=d["parent_id"],
        correlation_id=d["correlation_id"],
        ledger_head=d["ledger_head"],
        created_at=d["created_at"],
    )


class ExecutionCheckpointer:
    """Persists execution position via the kernel CheckpointStore (opaque blob)."""

    def __init__(self, services: KernelServices) -> None:
        self._store = services.checkpoints

    @staticmethod
    def _owner(execution_id: str) -> str:
        return f"runtime:{execution_id}"

    def save(self, snapshot: ExecutionSnapshot) -> None:
        blob = _snapshot_to_bytes(snapshot)
        cp = Checkpoint(
            checkpoint_id=f"{snapshot.execution_id}@{snapshot.ledger_head}",
            owner=self._owner(snapshot.execution_id),
            kind="execution",
            sequence=snapshot.ledger_head,
            blob=blob,
            digest=seal(blob),
        )
        self._store.save(cp)

    def latest(self, execution_id: str) -> ExecutionSnapshot | None:
        cp = self._store.latest(self._owner(execution_id))
        return _snapshot_from_bytes(cp.blob) if cp is not None else None


class ExecutionRecovery:
    """Deterministic recovery: integrity gate, ledger replay, checkpoint restore."""

    def __init__(self, services: KernelServices, checkpointer: ExecutionCheckpointer) -> None:
        self._kernel_recovery = RecoveryManager(
            services.ledger, services.checkpoints, services.identity
        )
        self._checkpointer = checkpointer

    def verify_integrity(self) -> None:
        self._kernel_recovery.verify_integrity()

    def replay(self, handler: EventHandler, *, since: int = 0) -> int:
        return self._kernel_recovery.replay(handler, since=since)

    def restore(self, execution_id: str) -> ExecutionSnapshot | None:
        return self._checkpointer.latest(execution_id)

    def last_position(self) -> int:
        return self._kernel_recovery.last_position()
