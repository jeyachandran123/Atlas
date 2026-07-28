"""The Resource Governor (Phase 5 Ch5) — the mind's central bank.

The single **bounded global allocator** over the local economies (attention,
reasoning, …). It allocates a finite total of cognitive resource by priority x
expected-value − cost, reserves guaranteed shares for critical matters, prevents
starvation (aging), detects and repairs **priority inversion** (priority
inheritance), and never over-commits the finite total (ExL4). Working-Memory
capacity is *guided* here as a budget (item 24) — a recommendation, never a
forced mutation of WM's own bounded store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import Allocation, AllocationResult, ExecutiveConfig, ResourceKind
from .errors import BudgetExceededError


@dataclass(slots=True)
class _Record:
    resource: ResourceKind
    matter_id: str
    share: float
    reserved: bool
    priority: float
    inherited: float = 0.0

    @property
    def effective_priority(self) -> float:
        return max(self.priority, self.inherited)


class ResourceGovernor:
    def __init__(self, config: ExecutiveConfig) -> None:
        self._config = config
        self._records: dict[tuple[str, str], _Record] = {}

    # --- accounting ------------------------------------------------------ #

    def committed(self) -> float:
        return round(sum(r.share for r in self._records.values()), 6)

    def available(self, *, for_safety: bool = False) -> float:
        reserved_floor = 0.0 if for_safety else self._config.safety_reservation
        return round(max(0.0, self._config.total_budget - self.committed() - reserved_floor), 6)

    def allocations(self) -> tuple[Allocation, ...]:
        return tuple(
            Allocation(r.resource, r.matter_id, round(r.share, 6), r.reserved)
            for r in sorted(self._records.values(), key=lambda r: (r.resource.value, r.matter_id))
        )

    # --- allocation (items 18, 19; ExL4) --------------------------------- #

    def allocate(
        self, resource: ResourceKind, matter_id: str, share: float, *,
        priority: float = 0.5, reserved: bool = False, strict: bool = False,
    ) -> AllocationResult:
        key = (resource.value, matter_id)
        share = max(0.0, share)
        current = self._records.get(key)
        delta = share - (current.share if current else 0.0)
        if delta > self.available(for_safety=reserved):
            if strict:
                raise BudgetExceededError(
                    f"allocation of {share} to {matter_id} exceeds the finite total (ExL4)."
                )
            return AllocationResult(
                False, resource, matter_id, 0.0, self.committed(), "resource exhausted — shed/narrow/escalate",
            )
        self._records[key] = _Record(resource, matter_id, share, reserved, priority)
        return AllocationResult(True, resource, matter_id, share, self.committed(), "granted")

    def reserve(self, resource: ResourceKind, matter_id: str, share: float) -> AllocationResult:
        return self.allocate(resource, matter_id, share, priority=1.0, reserved=True)

    def release(self, resource: ResourceKind, matter_id: str) -> bool:
        return self._records.pop((resource.value, matter_id), None) is not None

    def wm_capacity_guidance(self, matter_id: str, slots: float) -> AllocationResult:
        """Guide (never force) Working-Memory capacity as a budget (item 24)."""
        return self.allocate(ResourceKind.WORKING_MEMORY, matter_id, slots, priority=0.6)

    # --- starvation & priority inversion (ExL17/ExL18) ------------------- #

    def age(self, matter_id: str, boost: float) -> None:
        for r in self._records.values():
            if r.matter_id == matter_id:
                r.inherited = max(r.inherited, r.priority + boost)

    def detect_priority_inversion(self, resource: ResourceKind, blocked_priority: float) -> str | None:
        """A lower-priority holder blocking a higher-priority matter (OS inversion)."""
        holders = [r for r in self._records.values() if r.resource is resource]
        if not holders or self.available() > 0.0:
            return None
        lowest = min(holders, key=lambda r: r.effective_priority)
        return lowest.matter_id if lowest.effective_priority < blocked_priority else None

    def apply_priority_inheritance(self, resource: ResourceKind, holder_matter: str, blocked_priority: float) -> bool:
        """The blocker temporarily inherits the blocked matter's priority to release (ExL18)."""
        rec = self._records.get((resource.value, holder_matter))
        if rec is None:
            return False
        rec.inherited = max(rec.inherited, blocked_priority)
        return True

    # --- checkpoint / recovery ------------------------------------------- #

    def to_payload(self) -> list[dict[str, Any]]:
        return [
            {"resource": r.resource.value, "matter_id": r.matter_id, "share": r.share,
             "reserved": r.reserved, "priority": r.priority, "inherited": r.inherited}
            for r in self._records.values()
        ]

    def load_payload(self, rows: list[dict[str, Any]]) -> None:
        self._records.clear()
        for r in rows:
            rec = _Record(ResourceKind(r["resource"]), r["matter_id"], r["share"], r["reserved"],
                          r["priority"], r.get("inherited", 0.0))
            self._records[(rec.resource.value, rec.matter_id)] = rec
