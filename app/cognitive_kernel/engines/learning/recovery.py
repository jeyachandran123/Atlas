"""Learning Checkpoint & Recovery (items 27/28).

The learning **history** (immutable records) and the **calibration model** are the
engine's own durable footprint; committed knowledge revisions live in Cognitive
State (recovered by the State Manager). Both are checkpointed as an opaque,
integrity-sealed blob through the kernel ``CheckpointStore`` and restored
deterministically.
"""

from __future__ import annotations

import json
from typing import Any

from ...checkpoint import seal
from ...contracts import Checkpoint, KernelServices

_OWNER = "learning"


class LearningRecovery:
    def __init__(self, services: KernelServices) -> None:
        self._services = services

    def checkpoint(self, seq: int, history: list[dict[str, Any]], calibration: dict[str, Any]) -> str:
        blob = json.dumps({"seq": seq, "history": history, "calibration": calibration},
                          sort_keys=True).encode("utf-8")
        cp = Checkpoint(checkpoint_id=f"{_OWNER}@{seq}", owner=_OWNER, kind="learning_history",
                        sequence=seq, blob=blob, digest=seal(blob))
        self._services.checkpoints.save(cp)
        return cp.checkpoint_id

    def recover(self, checkpoint_id: str | None = None) -> dict[str, Any]:
        if checkpoint_id is None:
            cp = self._services.checkpoints.latest(_OWNER)
        else:
            cp = self._services.checkpoints.load(checkpoint_id)
        if cp is None:
            return {"restored": False, "history": [], "calibration": {}}
        data = json.loads(cp.blob.decode("utf-8"))
        return {"restored": True, "history": data.get("history", []),
                "calibration": data.get("calibration", {}), "seq": data.get("seq", 0)}
