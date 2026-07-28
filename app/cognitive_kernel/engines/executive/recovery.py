"""Executive Checkpoint & Recovery (Phase 5 Ch2 §13-14; ExL27).

Goals and Executive Decisions are durable Cognitive-State objects (recovered
through the State Manager). The executive's *governance configuration* — its
policies and resource allocations — is engine-internal state, so it is
checkpointed as an opaque, integrity-sealed blob through the kernel
``CheckpointStore`` (exactly as the State Manager checkpoints its own repo). On
recovery the portfolio is rebuilt from R2 GOAL objects and the governance
configuration is restored from the latest executive checkpoint.
"""

from __future__ import annotations

import json
from typing import Any

from ...checkpoint import seal
from ...contracts import Checkpoint, KernelServices
from .policy import PolicyManager
from .resources import ResourceGovernor

_OWNER = "executive"


class ExecutiveRecovery:
    def __init__(self, services: KernelServices, policy: PolicyManager, resources: ResourceGovernor) -> None:
        self._services = services
        self._policy = policy
        self._resources = resources

    def checkpoint(self, seq: int) -> str:
        blob = json.dumps(
            {"seq": seq, "policies": self._policy.to_payload(), "allocations": self._resources.to_payload()},
            sort_keys=True,
        ).encode("utf-8")
        cp = Checkpoint(
            checkpoint_id=f"{_OWNER}@{seq}", owner=_OWNER, kind="executive_governance",
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
            return {"restored": False, "policies": 0, "allocations": 0}
        data = json.loads(cp.blob.decode("utf-8"))
        self._policy.load_payload(data.get("policies", []))
        self._resources.load_payload(data.get("allocations", []))
        return {"restored": True, "policies": len(data.get("policies", [])),
                "allocations": len(data.get("allocations", [])), "seq": data.get("seq", 0)}
