"""The Goal Governor (Phase 5 Ch3) — owner and portfolio manager of the goal graph.

The executive does not *pursue* goals; it *governs a portfolio* of them: a bounded
active working set, most suspended/dormant, the impossible abandoned (audited,
resurrectable), promising ones resurrected, periodically reviewed against neglect
(Duncan). Goals are persisted as ``GOAL`` objects in **R2** through the State
Manager; the fine-grained governance state lives in each object's payload. Every
goal has exactly one accountable owner (ExL2); abandonment/completion are declared
on evaluated conditions (ExL19/ExL20), never assumed.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from ...state import CognitiveStateManager, ObjectStatus, ObjectType, Region
from ...state.contracts import RelationshipEdge, RelationshipType
from .contracts import ExecutiveConfig, Goal, GoalState, GoalTier
from .errors import GoalNotFoundError, OwnershipError

# Fine governance state -> coarse persisted status.
_STATE_STATUS = {
    GoalState.PROPOSED: ObjectStatus.PROPOSED,
    GoalState.ACTIVE: ObjectStatus.ACTIVE,
    GoalState.SUSPENDED: ObjectStatus.SUSPENDED,
    GoalState.DELEGATED: ObjectStatus.ACTIVE,
    GoalState.DORMANT: ObjectStatus.ARCHIVED,
    GoalState.ABANDONED: ObjectStatus.ARCHIVED,
    GoalState.COMPLETED: ObjectStatus.ARCHIVED,
    GoalState.FAILED: ObjectStatus.ARCHIVED,
}


class GoalGovernor:
    def __init__(self, state: CognitiveStateManager, config: ExecutiveConfig, clock: Any) -> None:
        self._state = state
        self._config = config
        self._clock = clock

    # --- creation & ownership (ExL2) ------------------------------------- #

    def create_goal(
        self, context: Any, *, title: str, owner: str, tier: GoalTier = GoalTier.TACTICAL,
        priority: float = 0.5, parent: str | None = None, dependencies: Sequence[str] = (),
        success_condition: str | None = None, deadline_seq: int | None = None, provenance: str = "",
    ) -> Goal:
        if not owner:
            raise OwnershipError("Every goal requires a single accountable owner (ExL2).")
        goal_id = "goal-" + uuid.uuid4().hex
        deps = tuple(d for d in dependencies if self._state.exists(d))
        tx = self._state.begin_transaction(context)
        tx.create(
            ObjectType.GOAL, handle=goal_id, status=ObjectStatus.ACTIVE, salience=priority,
            payload={
                "title": title, "tier": tier.value, "state": GoalState.ACTIVE.value, "owner": owner,
                "parent": parent, "dependencies": list(deps), "success_condition": success_condition,
                "deadline_seq": deadline_seq, "budget": 0.0,
            },
            relationships=tuple(RelationshipEdge(RelationshipType.DEPENDENCY, d) for d in deps),
            provenance=provenance or f"executive-owner:{owner}",
        )
        tx.commit()
        return self.get_goal(goal_id)

    # --- reads ----------------------------------------------------------- #

    def get_goal(self, goal_id: str) -> Goal:
        if not self._state.exists(goal_id):
            raise GoalNotFoundError(goal_id)
        return self._to_goal(self._state.get(goal_id))

    def portfolio(self) -> list[Goal]:
        objs = self._state.query(region=Region.R2_INTENTIONAL, type=ObjectType.GOAL)
        return [self._to_goal(o) for o in objs if "title" in o.payload]

    def active_goals(self) -> list[Goal]:
        return sorted(
            [g for g in self.portfolio() if g.state is GoalState.ACTIVE],
            key=lambda g: (-g.priority, g.goal_id),
        )

    def children(self, goal_id: str) -> list[Goal]:
        return [g for g in self.portfolio() if g.parent == goal_id]

    def dependencies_ready(self, goal: Goal) -> bool:
        for dep in goal.dependencies:
            if not self._state.exists(dep):
                return False
            if self._to_goal(self._state.get(dep)).state is not GoalState.COMPLETED:
                return False
        return True

    # --- lifecycle transitions ------------------------------------------- #

    def transition(self, context: Any, goal_id: str, new_state: GoalState, *, priority: float | None = None) -> Goal:
        goal = self.get_goal(goal_id)
        tx = self._state.begin_transaction(context)
        merge: dict[str, Any] = {"state": new_state.value}
        tx.update(
            goal_id, status=_STATE_STATUS[new_state], payload_merge=merge,
            salience=priority if priority is not None else goal.priority,
        )
        tx.commit()
        return self.get_goal(goal_id)

    def set_priority(self, context: Any, goal_id: str, priority: float) -> Goal:
        tx = self._state.begin_transaction(context)
        tx.update(goal_id, salience=priority)
        tx.commit()
        return self.get_goal(goal_id)

    def delegate(self, context: Any, goal_id: str, agent: str) -> Goal:
        goal = self.get_goal(goal_id)
        tx = self._state.begin_transaction(context)
        tx.update(goal_id, status=ObjectStatus.ACTIVE,
                  payload_merge={"state": GoalState.DELEGATED.value, "delegate": agent, "owner": goal.owner})
        tx.commit()  # ownership retained (ExL2); only execution is delegated
        return self.get_goal(goal_id)

    # --- completion / abandonment (ExL19/ExL20) -------------------------- #

    def verify_completion(self, goal: Goal, statement: str, confidence: float, threshold: float) -> bool:
        """Declare success only on an *evaluated* condition (ExL20)."""
        return (
            goal.success_condition is not None
            and statement == goal.success_condition
            and confidence >= threshold
        )

    # --- bounded working set (ExL15) ------------------------------------- #

    def enforce_working_set(self, context: Any) -> list[str]:
        """Keep the active set bounded; suspend the lowest-priority overflow (never drop)."""
        active = self.active_goals()
        suspended: list[str] = []
        overflow = active[self._config.max_active_goals:]
        for g in overflow:
            self.transition(context, g.goal_id, GoalState.SUSPENDED)
            suspended.append(g.goal_id)
        return suspended

    # --- internals ------------------------------------------------------- #

    def _to_goal(self, obj: Any) -> Goal:
        p = obj.payload
        return Goal(
            goal_id=obj.handle, title=p.get("title", ""), tier=GoalTier(p.get("tier", "tactical")),
            state=GoalState(p.get("state", "active")), priority=obj.salience, owner=p.get("owner", ""),
            parent=p.get("parent"), dependencies=tuple(p.get("dependencies", ())),
            success_condition=p.get("success_condition"), deadline_seq=p.get("deadline_seq"),
            budget=p.get("budget", 0.0), provenance=obj.provenance,
        )
