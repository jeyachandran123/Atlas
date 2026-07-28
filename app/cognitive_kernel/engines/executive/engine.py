"""The Executive Engine — the governance authority of the Cognitive OS (Phase 5).

The Executive Controller: the seat of executive authority (ExL1) that runs the
coarse governance cycle. It governs by **policy, allocation, and exception**
(subsidiarity) — it never perceives, attends, reasons, predicts, or learns; it
*coordinates* those faculties through runtime-routed control ports (ExL8), *uses*
reasoning's output to decide (ExL10), owns the goal portfolio (ExL2), allocates the
finite cognitive budget (ExL4), resolves conflicts by the fixed ladder (ExL23),
enforces constitutional policy (ExL7/ExL12), and records every act immutably
(ExL3/ExL5) — a decomposed, bounded, safety-subordinate mechanism, not a homunculus.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Mapping

from ...contracts import (
    CognitiveEngine,
    EngineMetadata,
    EventPriority,
    ExecutionContext,
    HealthReport,
    HealthStatus,
    KernelServices,
)
from ...state import CognitiveStateManager
from .audit import ExecutiveAuditLayer
from .conflict import ConflictResolver
from .contracts import (
    ConflictType,
    DecisionKind,
    DecisionOutcome,
    Directive,
    ExecutiveConfig,
    ExecutiveHealthReport,
    ExecutiveMetricsSnapshot,
    ExecutiveMode,
    GovernanceDashboard,
    GovernanceOutcome,
    Goal,
    GoalState,
    GoalTier,
    Priority,
    ReasoningProposal,
    ResourceKind,
)
from .decision import DecisionArbiter
from .errors import UnknownExecutiveOperationError
from .goals import GoalGovernor
from .policy import PolicyManager
from .ports import NullPredictionRiskPort, RuntimeAttentionPort, RuntimeReasoningPort
from .priority import PriorityManager
from .recovery import ExecutiveRecovery
from .resources import ResourceGovernor
from .security import ExecutiveSecurity
from .state_io import decision_trail, write_decision
from .strategy import StrategyGovernor
import dataclasses


class ExecutiveEngine(CognitiveEngine):
    ENGINE_NAME = "executive"

    def __init__(
        self,
        services: KernelServices,
        state_manager: CognitiveStateManager,
        config: ExecutiveConfig | None = None,
        *,
        reasoning_port: Any | None = None,
        attention_port: Any | None = None,
        prediction_port: Any | None = None,
    ) -> None:
        self._services = services
        self._state = state_manager
        self._config = config or ExecutiveConfig()
        self._security = ExecutiveSecurity(self._config)
        self._policy = PolicyManager(self._config)
        self._goals = GoalGovernor(state_manager, self._config, services.clock)
        self._priority = PriorityManager(self._config)
        self._resources = ResourceGovernor(self._config)
        self._conflict = ConflictResolver(self._config)
        self._arbiter = DecisionArbiter(self._config)
        self._reasoning_port = reasoning_port
        self._attention_port = attention_port
        self._prediction = prediction_port or NullPredictionRiskPort()
        self._strategy = self._build_strategy()
        self._audit = ExecutiveAuditLayer(services)
        self._recovery = ExecutiveRecovery(services, self._policy, self._resources)
        self._lock = threading.RLock()
        self._started = False
        self._mode = ExecutiveMode.SUSTAINED
        self._paused: set[str] = set()
        # metrics
        self._passes = self._decisions = self._approvals = self._rejections = self._escalations = 0
        self._goals_created = self._goals_completed = self._goals_abandoned = 0
        self._conflicts_resolved = self._allocations = self._policy_enactments = self._interventions = 0

    def _build_strategy(self) -> StrategyGovernor | None:
        if self._reasoning_port is not None and self._attention_port is not None:
            return StrategyGovernor(self._config, self._reasoning_port, self._attention_port)
        return None

    # --- kernel lifecycle ------------------------------------------------ #

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.ENGINE_NAME, version="1.0", provides=("executive",),
            depends_on=("working_memory", "attention", "reasoning"),
            constitutional_scope=tuple(f"ExL{i}" for i in range(1, 31)),
        )

    def initialize(self, services: KernelServices) -> None:
        self._services = services

    def start(self) -> None:
        with self._lock:
            self._started = True

    def stop(self) -> None:
        with self._lock:
            self._started = False

    def health(self) -> HealthReport:
        return self._health_probe()

    def register(self, kernel, runtime) -> None:
        # Wire the control ports from the runtime (coordination by name, never by import).
        if self._reasoning_port is None:
            self._reasoning_port = RuntimeReasoningPort(runtime)
        if self._attention_port is None:
            self._attention_port = RuntimeAttentionPort(runtime)
        self._strategy = self._build_strategy()
        kernel.register_engine(self.metadata, lambda services: self)
        runtime.register_engine(self.ENGINE_NAME, self)
        self._services.health.register_probe("executive", self._health_probe)
        self.start()

    # --- runtime ExecutableEngine ---------------------------------------- #

    def execute(self, operation: str, payload: Mapping[str, Any], context: ExecutionContext) -> Any:
        p = payload
        if operation == "govern":
            outcome = self.govern(self._proposal_from(p), context)
            return {
                "decision": outcome.decision.kind.value, "outcome": outcome.decision.outcome.value,
                "authorized": outcome.authorized, "confidence": outcome.decision.confidence,
                "threshold": outcome.decision.threshold, "goal_id": outcome.goal_id,
            }
        if operation == "create_goal":
            g = self.create_goal(
                context, title=p["title"], owner=p["owner"],
                tier=GoalTier(p.get("tier", "tactical")), priority=float(p.get("priority", 0.5)),
                parent=p.get("parent"), dependencies=tuple(p.get("dependencies", ())),
                success_condition=p.get("success_condition"),
            )
            return {"goal_id": g.goal_id, "state": g.state.value}
        if operation == "allocate":
            r = self.allocate(context, ResourceKind(p["resource"]), p["matter_id"], float(p["share"]),
                              priority=float(p.get("priority", 0.5)))
            return {"granted": r.granted, "share": r.share, "committed": r.committed_total}
        if operation == "escalate":
            d = self.escalate(context, p["subject"], p.get("reason", ""))
            return {"decision": d.kind.value, "outcome": d.outcome.value}
        if operation == "pause":
            return {"paused": self.pause(context, p["matter_id"])}
        if operation == "resume":
            return {"resumed": self.resume(context, p["matter_id"])}
        raise UnknownExecutiveOperationError(f"Unknown executive operation: {operation!r}")

    def _proposal_from(self, p: Mapping[str, Any]) -> ReasoningProposal:
        return ReasoningProposal(
            proposal_id=p.get("proposal_id", "prop-" + uuid.uuid4().hex),
            statement=p.get("statement", ""), confidence=float(p.get("confidence", 0.0)),
            kind=p.get("kind", "belief"), goal_id=p.get("goal_id"), action=p.get("action"),
            stakes=float(p.get("stakes", 0.0)), reversibility=float(p.get("reversibility", 1.0)),
            safety_relevant=bool(p.get("safety_relevant", False)),
            identity_relevant=bool(p.get("identity_relevant", False)),
            evidence=tuple(p.get("evidence", ())), source=p.get("source", "reasoning"),
        )

    # --- the governance cycle (the pipeline) ----------------------------- #

    def govern(self, proposal: ReasoningProposal, context: ExecutionContext) -> GovernanceOutcome:
        with self._lock:
            seq = self._services.clock.current()
            self._mode = ExecutiveMode.REACTIVE  # recruited by the proposal (conflict monitoring)
            self._passes += 1

            # 1. Policy Evaluation (constitutional enforcement first — ExL7/ExL37).
            policy_decision = self._policy.evaluate(proposal)
            # 2. Goal Evaluation.
            goal = (
                self._goals.get_goal(proposal.goal_id)
                if proposal.goal_id and self._state.exists(proposal.goal_id) else None
            )
            # 3. Priority Assessment.
            priority_score = goal.priority if goal else 0.5
            # 4. Risk Assessment Request (if required).
            risk = None
            if proposal.stakes >= self._config.escalation_stakes or proposal.reversibility < 0.5:
                risk = self.request_risk(proposal, context)
            # 5. Executive Decision (grounded in reasoning's confidence + risk-scaled threshold).
            decision = self._arbiter.decide(
                proposal, policy_decision, priority=priority_score, risk=risk,
                authority=self._authority(context), seq=seq,
            )
            # 6. Action Authorization.
            authorized = decision.outcome is DecisionOutcome.APPROVED
            # 7. Cognitive State Update — persist the immutable decision (ExL3/ExL26).
            handle = write_decision(self._state, context, decision)
            decision = dataclasses.replace(decision, handle=handle)
            # 8. Runtime Coordination — directives via ports (ExL8).
            directives = self._coordinate(proposal, authorized, context)
            # goal side-effects (completion declared on evaluated conditions — ExL20).
            goal_id = self._apply_goal_effects(proposal, decision, goal, authorized, context, seq)
            self._tally_decision(decision)
            # 9/10. Events + Audit Trail.
            self._audit.record(
                "decision",
                {"decision_id": decision.decision_id, "kind": decision.kind.value,
                 "outcome": decision.outcome.value, "subject": decision.subject,
                 "authorized": authorized, "confidence": decision.confidence,
                 "threshold": decision.threshold, "handle": handle},
                context, priority=EventPriority.HIGH,
            )
            return GovernanceOutcome(decision, authorized, tuple(directives), goal_id, seq)

    def _coordinate(self, proposal: ReasoningProposal, authorized: bool, context) -> list[Directive]:
        directives: list[Directive] = []
        if not authorized or self._strategy is None:
            return directives
        if not (proposal.kind in ("action", "plan", "strategy") or proposal.goal_id):
            return directives
        # Best-effort coordination: if a faculty is not reachable, the executive still
        # governs (subsidiarity) and records the gap — it never crashes on a faculty (ExL8).
        try:
            if proposal.goal_id:
                directives.append(self._strategy.guide_attention(context, proposal.goal_id, 0.3))
            directives.append(
                self._strategy.govern_reasoning(
                    context, proposal.proposal_id, stakes=proposal.stakes,
                    correctness_critical=proposal.reversibility < 0.5,
                )
            )
        except Exception as exc:  # faculty unavailable -> degrade gracefully
            self._audit.record("coordination_unavailable", {"reason": str(exc)}, context)
        return directives

    def _apply_goal_effects(self, proposal, decision, goal, authorized, context, seq) -> str | None:
        if goal is None or not authorized:
            return goal.goal_id if goal else None
        if self._goals.verify_completion(goal, proposal.statement, proposal.confidence, decision.threshold):
            self._goals.transition(context, goal.goal_id, GoalState.COMPLETED)
            self._persist_ruling(context, DecisionKind.COMPLETE, DecisionOutcome.APPROVED, goal.goal_id,
                                 "success condition met and verified (ExL20)", seq)
            self._goals_completed += 1
        return goal.goal_id

    # --- goal governance (items 2-10, 38) -------------------------------- #

    def create_goal(self, context, *, title, owner, tier=GoalTier.TACTICAL, priority=0.5,
                    parent=None, dependencies=(), success_condition=None) -> Goal:
        with self._lock:
            goal = self._goals.create_goal(
                context, title=title, owner=owner, tier=tier, priority=priority, parent=parent,
                dependencies=dependencies, success_condition=success_condition,
            )
            suspended = self._goals.enforce_working_set(context)  # bounded working set (ExL15)
            self._goals_created += 1
            self._audit.record("goal_created", {"goal_id": goal.goal_id, "owner": owner, "tier": tier.value,
                                                "suspended_overflow": suspended}, context)
            return goal

    def abandon_goal(self, context, goal_id: str, reason: str):
        with self._lock:
            seq = self._services.clock.current()
            goal = self._goals.transition(context, goal_id, GoalState.ABANDONED)
            self._goals_abandoned += 1
            ruling = self._persist_ruling(context, DecisionKind.ABANDON, DecisionOutcome.APPROVED, goal_id,
                                          f"abandoned (audited, resurrectable): {reason}", seq)  # ExL19
            self._audit.record("goal_abandoned", {"goal_id": goal_id, "reason": reason,
                                                  "decision": ruling.decision_id}, context)
            return goal

    def delegate_goal(self, context, goal_id: str, agent: str):
        with self._lock:
            seq = self._services.clock.current()
            goal = self._goals.delegate(context, goal_id, agent)  # ownership retained (ExL2)
            self._persist_ruling(context, DecisionKind.DELEGATE, DecisionOutcome.APPROVED, goal_id,
                                 f"execution delegated to {agent}; ownership retained", seq)
            self._audit.record("goal_delegated", {"goal_id": goal_id, "agent": agent}, context)
            return goal

    def verify_goal_completion(self, context, goal_id: str, statement: str, confidence: float) -> bool:
        with self._lock:
            goal = self._goals.get_goal(goal_id)
            threshold = self._arbiter.threshold(0.0, 1.0)
            if self._goals.verify_completion(goal, statement, confidence, threshold):
                seq = self._services.clock.current()
                self._goals.transition(context, goal_id, GoalState.COMPLETED)
                self._persist_ruling(context, DecisionKind.COMPLETE, DecisionOutcome.APPROVED, goal_id,
                                     "success condition verified", seq)
                self._goals_completed += 1
                self._audit.record("goal_completed", {"goal_id": goal_id}, context)
                return True
            return False

    def assess_priority(self, context, goal_id: str, *, signals: Mapping[str, float] | None = None,
                        aging: float = 0.0) -> Priority:
        with self._lock:
            goal = self._goals.get_goal(goal_id)
            pr = self._priority.score(goal, signals=signals, aging=aging)
            self._goals.set_priority(context, goal_id, pr.score)
            return pr

    def priority_order(self) -> tuple[str, ...]:
        goals = self._goals.active_goals()
        return tuple(g.goal_id for g in goals)  # active_goals is already priority-sorted

    def portfolio_review(self, context) -> dict:
        """Periodic review against goal neglect (ExL21): re-prioritise, age the neglected."""
        with self._lock:
            self._mode = ExecutiveMode.SUSTAINED
            active = self._goals.active_goals()
            for g in active:
                self.assess_priority(context, g.goal_id, aging=self._config.aging_rate)
            self._audit.record("portfolio_review", {"active": len(active)}, context)
            return {"active": len(active), "order": self.priority_order()}

    # --- resource governance (items 18, 19, 24) -------------------------- #

    def allocate(self, context, resource: ResourceKind, matter_id: str, share: float, *, priority=0.5):
        with self._lock:
            result = self._resources.allocate(resource, matter_id, share, priority=priority)
            self._allocations += 1
            self._audit.record("allocation", {"resource": resource.value, "matter": matter_id,
                                              "share": share, "granted": result.granted,
                                              "committed": result.committed_total}, context)
            return result

    def guide_wm_capacity(self, context, matter_id: str, slots: float):
        with self._lock:
            result = self._resources.wm_capacity_guidance(matter_id, slots)
            self._audit.record("wm_capacity_guidance", {"matter": matter_id, "slots": slots,
                                                        "granted": result.granted}, context)
            return result

    def repair_priority_inversion(self, context, resource: ResourceKind, blocked_priority: float):
        with self._lock:
            holder = self._resources.detect_priority_inversion(resource, blocked_priority)
            if holder is None:
                return None
            self._resources.apply_priority_inheritance(resource, holder, blocked_priority)  # ExL18
            self._interventions += 1
            self._audit.record("priority_inheritance", {"resource": resource.value, "holder": holder,
                                                        "inherited_priority": blocked_priority}, context)
            return holder

    # --- conflict management (items 8, 10) ------------------------------- #

    def resolve_conflict(self, context, ctype: ConflictType, parties, **kw):
        with self._lock:
            seq = self._services.clock.current()
            conflict = self._conflict.resolve(ctype, parties, **kw)
            if conflict.resolved:
                self._conflicts_resolved += 1
            outcome = DecisionOutcome.ESCALATED if conflict.escalated else DecisionOutcome.APPROVED
            self._persist_ruling(context, DecisionKind.ESCALATE if conflict.escalated else DecisionKind.CONTINUE,
                                 outcome, conflict.conflict_id,
                                 f"conflict resolved by {conflict.basis.value}: {conflict.detail}", seq)
            self._audit.record("conflict", {"conflict_id": conflict.conflict_id, "type": ctype.value,
                                            "basis": conflict.basis.value, "winner": conflict.winner,
                                            "escalated": conflict.escalated}, context,
                               priority=EventPriority.HIGH)
            return conflict

    # --- interventions: interrupt / pause / resume / escalate (25-28) ---- #

    def pause(self, context, matter_id: str) -> bool:
        with self._lock:
            seq = self._services.clock.current()
            self._paused.add(matter_id)
            if self._state.exists(matter_id):
                self._goals.transition(context, matter_id, GoalState.SUSPENDED)
            self._persist_ruling(context, DecisionKind.PAUSE, DecisionOutcome.APPROVED, matter_id,
                                 "paused at a boundary", seq)
            self._interventions += 1
            self._audit.record("pause", {"matter": matter_id}, context)
            return True

    def resume(self, context, matter_id: str) -> bool:
        with self._lock:
            seq = self._services.clock.current()
            self._paused.discard(matter_id)
            if self._state.exists(matter_id):
                self._goals.transition(context, matter_id, GoalState.ACTIVE)
            self._persist_ruling(context, DecisionKind.RESUME, DecisionOutcome.APPROVED, matter_id,
                                 "resumed", seq)
            self._audit.record("resume", {"matter": matter_id}, context)
            return True

    def interrupt(self, context, matter_id: str, by_matter_id: str) -> bool:
        with self._lock:
            self.pause(context, matter_id)  # preempt the lower-priority matter
            self._interventions += 1
            self._audit.record("interrupt", {"matter": matter_id, "by": by_matter_id}, context,
                               priority=EventPriority.HIGH)
            return True

    def escalate(self, context, subject: str, reason: str):
        with self._lock:
            seq = self._services.clock.current()
            ruling = self._persist_ruling(context, DecisionKind.ESCALATE, DecisionOutcome.ESCALATED, subject,
                                          f"escalated to human (P10/ExL14): {reason}", seq)
            self._escalations += 1
            self._audit.record("escalation", {"subject": subject, "reason": reason,
                                              "decision": ruling.decision_id}, context,
                               priority=EventPriority.HIGH)
            return ruling

    # --- policy governance (items 12, 37) -------------------------------- #

    def enact_policy(self, context, policy):
        self._security.require_authority("enact_policy", context)  # gated (ExL29)
        with self._lock:
            seq = self._services.clock.current()
            enacted = self._policy.enact(policy, seq)
            self._policy_enactments += 1
            self._persist_ruling(context, DecisionKind.ENACT_POLICY, DecisionOutcome.APPROVED, enacted.policy_id,
                                 f"policy '{enacted.name}' v{enacted.version} enacted", seq)
            self._audit.record("policy_enacted", {"policy_id": enacted.policy_id, "family": enacted.family.value,
                                                  "name": enacted.name, "version": enacted.version}, context)
            return enacted

    def evaluate_policy(self, proposal: ReasoningProposal):
        return self._policy.evaluate(proposal)

    def request_risk(self, proposal: ReasoningProposal, context) -> Mapping[str, Any] | None:
        """Request risk evaluation / prediction (items 20, 21). Executive never predicts."""
        if not self._prediction.available():
            self._audit.record("risk_unavailable", {"subject": proposal.proposal_id}, context)
            return None
        result = self._prediction.request(
            {"statement": proposal.statement, "stakes": proposal.stakes,
             "reversibility": proposal.reversibility}, context,
        )
        self._audit.record("risk_requested", {"subject": proposal.proposal_id}, context)
        return result

    # --- observability: metrics / health / dashboard (30, 32, 33, 40) ---- #

    def metrics(self) -> ExecutiveMetricsSnapshot:
        with self._lock:
            return ExecutiveMetricsSnapshot(
                governance_passes=self._passes, decisions=self._decisions, approvals=self._approvals,
                rejections=self._rejections, escalations=self._escalations, goals_created=self._goals_created,
                goals_completed=self._goals_completed, goals_abandoned=self._goals_abandoned,
                conflicts_resolved=self._conflicts_resolved, allocations=self._allocations,
                policy_enactments=self._policy_enactments, interventions=self._interventions,
                active_goals=len(self._goals.active_goals()), committed_budget=self._resources.committed(),
            )

    def dashboard(self) -> GovernanceDashboard:
        with self._lock:
            active = tuple(self._goals.active_goals())
            recent = tuple(o.payload["decision_id"] for o in decision_trail(self._state)[-8:])
            return GovernanceDashboard(
                active_goals=active, priority_order=tuple(g.goal_id for g in active),
                allocations=self._resources.allocations(), policies=self._policy.policies(),
                open_conflicts=(), recent_decisions=recent, mode=self._mode,
                committed_budget=self._resources.committed(), metrics=self.metrics(),
            )

    def audit_trail(self, *, subject: str | None = None):
        return decision_trail(self._state, subject=subject)

    def inspect(self) -> dict:
        return {
            "mode": self._mode.value, "metrics": self.metrics(),
            "active_goals": [g.goal_id for g in self._goals.active_goals()],
            "committed_budget": self._resources.committed(),
            "policies": [p.name for p in self._policy.policies()],
            "prediction_available": self._prediction.available(),
        }

    def executive_health(self) -> ExecutiveHealthReport:
        committed = self._resources.committed()
        budget_ok = committed <= self._config.total_budget + 1e-9
        return ExecutiveHealthReport(
            healthy=self._started and budget_ok, detail="active" if self._started else "stopped",
            mode=self._mode, active_goals=len(self._goals.active_goals()),
            committed_budget=committed, budget_ok=budget_ok,
        )

    # --- checkpoint / recovery (34, 35) ---------------------------------- #

    def checkpoint(self) -> str:
        with self._lock:
            return self._recovery.checkpoint(self._services.clock.current())

    def recover(self, checkpoint_id: str | None = None) -> dict:
        with self._lock:
            summary = self._recovery.recover(checkpoint_id)
            self._audit.record("recovered", summary, None)
            return summary

    # --- development hook (gated) ---------------------------------------- #

    def set_config(self, config: ExecutiveConfig, context) -> None:
        self._security.require_authority("set_config", context)
        with self._lock:
            self._config = config
            self._security = ExecutiveSecurity(config)
            self._priority = PriorityManager(config)
            self._arbiter = DecisionArbiter(config)
            self._conflict = ConflictResolver(config)
        self._audit.record("config_changed", {"autonomy_threshold": config.autonomy_threshold}, context)

    # --- internals ------------------------------------------------------- #

    def _persist_ruling(self, context, kind: DecisionKind, outcome: DecisionOutcome, subject: str,
                        rationale: str, seq: int):
        ruling = self._arbiter.ruling(kind, outcome, subject, rationale,
                                      authority=self._authority(context), seq=seq)
        handle = write_decision(self._state, context, ruling)
        self._decisions += 1
        return dataclasses.replace(ruling, handle=handle)

    def _tally_decision(self, decision) -> None:
        self._decisions += 1
        if decision.outcome is DecisionOutcome.APPROVED:
            self._approvals += 1
        elif decision.outcome is DecisionOutcome.REJECTED:
            self._rejections += 1
        elif decision.outcome is DecisionOutcome.ESCALATED:
            self._escalations += 1

    @staticmethod
    def _authority(context) -> str:
        sec = getattr(context, "security", None)
        return getattr(sec, "principal", "executive") if sec is not None else "executive"

    def _health_probe(self) -> HealthReport:
        h = self.executive_health()
        return HealthReport(
            component="executive",
            status=HealthStatus.HEALTHY if h.healthy else (HealthStatus.DEGRADED if not self._started else HealthStatus.UNHEALTHY),
            detail=h.detail,
            metrics={"active_goals": float(h.active_goals), "committed_budget": h.committed_budget},
        )
