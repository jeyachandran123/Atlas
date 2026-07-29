"""Development Checkpoint & Recovery (items 22/23).

Development's durable footprint is its own history (capability score trajectories)
and certification versions. It is checkpointed as an opaque, integrity-sealed blob
through the kernel ``CheckpointStore`` and restored deterministically. No canonical
state is touched (DeL13).
"""

from __future__ import annotations

import json
from typing import Any

from ...checkpoint import seal
from ...contracts import Checkpoint, KernelServices

_OWNER = "development"


class DevelopmentRecovery:
    def __init__(self, services: KernelServices) -> None:
        self._services = services

    def checkpoint(self, seq: int, history: list[dict[str, Any]], versions: dict[str, int]) -> str:
        blob = json.dumps({"seq": seq, "history": history, "versions": versions},
                          sort_keys=True).encode("utf-8")
        cp = Checkpoint(checkpoint_id=f"{_OWNER}@{seq}", owner=_OWNER, kind="development_history",
                        sequence=seq, blob=blob, digest=seal(blob))
        self._services.checkpoints.save(cp)
        return cp.checkpoint_id

    def recover(self, checkpoint_id: str | None = None) -> dict[str, Any]:
        if checkpoint_id is None:
            cp = self._services.checkpoints.latest(_OWNER)
        else:
            cp = self._services.checkpoints.load(checkpoint_id)
        if cp is None:
            return {"restored": False, "history": [], "versions": {}}
        data = json.loads(cp.blob.decode("utf-8"))
        return {"restored": True, "history": data.get("history", []),
                "versions": data.get("versions", {}), "seq": data.get("seq", 0)}
