"""The Executive Audit Layer (Phase 5 Ch2 §15; ExL5).

Guarantees that *every* executive act — decision, allocation, policy change,
intervention, override — is recorded, explainable, and auditable, by publishing
to the Cognitive Ledger through the event bus. It records; it never influences
governance (separation of powers, ExL25). It is structurally independent of the
governor so the record cannot be quietly shaped by what it records.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from ...contracts import CognitiveEvent, EventPriority, KernelServices


class ExecutiveAuditLayer:
    def __init__(self, services: KernelServices) -> None:
        self._services = services

    def record(self, act: str, payload: Mapping[str, Any], context: Any, *,
               priority: EventPriority = EventPriority.NORMAL) -> None:
        cid = getattr(context, "correlation_id", "executive") if context is not None else "executive"
        event = CognitiveEvent(
            event_id=uuid.uuid4().hex, type=f"executive.{act}", sequence=self._services.clock.tick(),
            source="executive", correlation_id=cid, payload=dict(payload), priority=priority,
        )
        self._services.events.publish(event)
