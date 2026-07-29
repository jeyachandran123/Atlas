"""Prediction Checkpoint & Recovery (items 28, 29).

Prediction writes no Cognitive State, so its durable footprint is the engine's own
forecast **history** (hypothetical, tagged). It is checkpointed as an opaque,
integrity-sealed blob through the kernel ``CheckpointStore`` (as the State Manager
checkpoints its own repo) and restored deterministically. No canonical state is
touched by checkpoint or recovery (PrL8).
"""

from __future__ import annotations

import json
from typing import Any

from ...checkpoint import seal
from ...contracts import Checkpoint, KernelServices

_OWNER = "prediction"


class PredictionRecovery:
    def __init__(self, services: KernelServices) -> None:
        self._services = services

    def checkpoint(self, seq: int, history: list[dict[str, Any]]) -> str:
        blob = json.dumps({"seq": seq, "history": history}, sort_keys=True).encode("utf-8")
        cp = Checkpoint(
            checkpoint_id=f"{_OWNER}@{seq}", owner=_OWNER, kind="prediction_history",
            sequence=seq, blob=blob, digest=seal(blob),
        )
        self._services.checkpoints.save(cp)
        return cp.checkpoint_id

    def recover(self, checkpoint_id: str | None = None) -> dict[str, Any]:
        if checkpoint_id is None:
            cp = self._services.checkpoints.latest(_OWNER)
        else:
            cp = self._services.checkpoints.load(checkpoint_id)
        if cp is None:
            return {"restored": False, "history": []}
        data = json.loads(cp.blob.decode("utf-8"))
        return {"restored": True, "history": data.get("history", []), "seq": data.get("seq", 0)}
