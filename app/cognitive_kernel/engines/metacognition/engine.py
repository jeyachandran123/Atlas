"""The Meta-Cognition Engine — the independent oversight faculty (Phase 7, Tier 3).

It evaluates the *quality* of cognition and never performs it (MeL1/MeL4). It
observes cognitive activity through the Ledger, Health Monitor, and Runtime
telemetry (grounded in traces, not introspection — MeL16), assesses every faculty,
detects failures/drift/bias/contradiction/fatigue/miscalibration, monitors
constitutional compliance (always-on — MeL29), generates transparent, immutable
reflection artifacts (MeL19/MeL21), and **recommends** interventions routed to the
Executive through the Runtime (MeL2/MeL6) — reversible and audited (MeL20). It
writes **no canonical state** (MeL9/MeL13), imports no sibling engine, and is
additive: remove it and reliability degrades but authority is untouched (MeL35).
"""

from __future__ import annotations

import dataclasses
import threading
import uuid
from collections import deque
from typing import Any, Mapping

from ...contracts import (
    CognitiveEngine,
    CognitiveEvent,
    EngineMetadata,
    EventPriority,
    ExecutionContext,
    HealthReport,
    HealthStatus,
    KernelServices,
)
from ...state import CognitiveStateManager
from . import assessors, detectors
from .compliance import ConstitutionalComplianceMonitor
from .contracts import (
    Assessment,
    ConstitutionalAuditReport,
    InterventionRecommendation,
    MetaConfig,
    MetaHealthReport,
    MetaMetricsSnapshot,
    ReflectionArtifact,
)
from .errors import MetaSecurityError, ReflectionNotFoundError, UnknownMetaOperationError
from .observation import ObservationManager
from .ports import NullInterventionPort, RuntimeInterventionPort
from .recommend import InterventionRecommendationEngine
from .recovery import MetaRecovery
from .reports import (
    build_governance_report,
    build_trace,
    digest,
    overall_confidence,
    summarize,
)
from .state_io import canonical_object_count


class MetaCognitionEngine(CognitiveEngine):
    ENGINE_NAME = "metacognition"

    def __init__(
        self,
        services: KernelServices,
        state_manager: CognitiveStateManager,
        config: MetaConfig | None = None,
        *,
        intervention_port: Any | None = None,
    ) -> None:
        self._services = services
        self._state = state_manager
        self._config = config or MetaConfig()
        self._observer = ObservationManager(services, state_manager)
        self._compliance = ConstitutionalComplianceMonitor(self._config)
        self._recommender = InterventionRecommendationEngine(self._config)
        self._intervention = intervention_port or NullInterventionPort()
        self._recovery = MetaRecovery(services)
        self._lock = threading.RLock()
        self._started = False
        self._cursor = 0
        self._history: deque = deque(maxlen=self._config.history_limit)
        self._repository: dict[str, ReflectionArtifact] = {}
        self._artifact_order: deque = deque(maxlen=self._config.artifact_limit)
        self._last_assessments: dict[str, Assessment] = {}
        self._last_audit: ConstitutionalAuditReport | None = None
        # metrics
        self._reflections = self._assessment_count = self._finding_count = self._rec_count = 0
        self._interventions_requested = self._audit_count = self._violation_count = 0
        self._events_observed = 0
        self._canonical_writes = 0  # invariant: remains 0 (MeL9/MeL13)

    # --- kernel lifecycle ------------------------------------------------ #

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.ENGINE_NAME, version="1.0", provides=("metacognition",),
            depends_on=("working_memory", "attention", "reasoning", "executive", "prediction"),
            constitutional_scope=tuple(f"MeL{i}" for i in range(1, 36)),
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
        self._observer.bind_runtime(runtime)  # runtime telemetry (metrics) only
        if isinstance(self._intervention, NullInterventionPort):
            self._intervention = RuntimeInterventionPort(runtime)
        kernel.register_engine(self.metadata, lambda services: self)
        runtime.register_engine(self.ENGINE_NAME, self)
        self._services.health.register_probe("metacognition", self._health_probe)
        self.start()

    # --- runtime ExecutableEngine ---------------------------------------- #

    def execute(self, operation: str, payload: Mapping[str, Any], context: ExecutionContext) -> Any:
        if operation == "reflect":
            art = self.reflect(context)
            return {"artifact_id": art.artifact_id, "assessments": len(art.assessments),
                    "findings": len(art.findings), "recommendations": len(art.recommendations),
                    "compliant": art.audit.compliant, "confidence": art.confidence}
        if operation == "audit":
            r = self.constitutional_audit(context)
            return {"compliant": r.compliant, "violations": len(r.violations), "checked": len(r.checked)}
        if operation == "assess":
            a = self.oversee(payload.get("subject", "cognitive_health"))
            return {"subject": a.subject, "grade": a.grade.value, "score": a.score, "level": a.level.value}
        raise UnknownMetaOperationError(f"Unknown meta operation: {operation!r}")

    # --- the meta-cognitive pipeline ------------------------------------- #

    def reflect(self, context: ExecutionContext) -> ReflectionArtifact:
        with self._lock:
            session_id = "refl-" + uuid.uuid4().hex
            seq = self._services.clock.current()
            # 1. Observe (grounded in traces — MeL16).
            window = self._observer.observe(since=self._cursor)
            self._cursor = window.until_seq
            self._events_observed += window.total_events
            # 2-3. Evaluate every faculty.
            assessments = [
                assessors.assess_health(window, self._config),
                assessors.assess_performance(window, self._config),
                assessors.assess_executive(window, self._config),
                assessors.assess_reasoning(window, self._config),
                assessors.assess_prediction(window, self._config),
                assessors.assess_attention(window, self._config),
                assessors.assess_working_memory(window, self._config),
                assessors.assess_runtime(window, self._config),
            ]
            by_subject = {a.subject: a for a in assessments}
            self._last_assessments = by_subject
            current = self._current_metrics(by_subject)
            # 4. Detect patterns (each pathology a dedicated detector — MeL26).
            findings = (
                detectors.detect_failures(assessments, self._config)
                + detectors.detect_bias(window, self._config)
                + detectors.detect_contradiction_patterns(window, self._config)
                + detectors.detect_fatigue(window, self._config)
                + detectors.analyze_calibration(window, self._config)
                + detectors.analyze_resource_utilization(window, self._config)
                + detectors.detect_drift(list(self._history), current, self._config)
            )
            # 5. Constitutional compliance (always-on — MeL29).
            audit = self._compliance.audit(window, seq=seq)
            self._last_audit = audit
            findings = findings + list(audit.violations)
            # 6. Recommend (safe side, Executive-routed — MeL6/MeL2).
            recommendations = self._recommender.recommend(findings, assessments, seq=seq)
            # 7-8. Optionally submit intervention requests through the Runtime.
            if self._config.auto_request:
                submitted = []
                for r in recommendations:
                    ok = self._intervention.submit(r, context)
                    if ok:
                        self._interventions_requested += 1
                    submitted.append(dataclasses.replace(r, requested=ok))
                recommendations = submitted
            # 9. Record the immutable reflection artifact (in-engine + ledger; no canonical write).
            trace = build_trace(window, assessments, findings, recommendations, audit)
            artifact = ReflectionArtifact(
                artifact_id="art-" + uuid.uuid4().hex, session_id=session_id, window_id=window.window_id,
                seq=seq, assessments=tuple(assessments), findings=tuple(findings),
                recommendations=tuple(recommendations), audit=audit, trace=trace,
                summary=summarize(assessments, findings, audit),
                confidence=overall_confidence(assessments), digest=digest(trace),
            )
            self._store(artifact)
            self._history.append(current)
            self._reflections += 1
            self._assessment_count += len(assessments)
            self._finding_count += len(findings)
            self._rec_count += len(recommendations)
            self._audit_count += 1
            self._violation_count += len(audit.violations)
            # 10. Publish audit events (observable/auditable — MeL19).
            self._emit("metacognition.reflection", {
                "session": session_id, "assessments": len(assessments), "findings": len(findings),
                "recommendations": len(recommendations), "compliant": audit.compliant,
                "confidence": artifact.confidence, "hypothetical_judgment": True,
            }, context)
            self._emit("metacognition.audit", {
                "compliant": audit.compliant, "violations": len(audit.violations),
                "checked": len(audit.checked),
            }, context, priority=EventPriority.HIGH)
            for f in findings:
                if f.severity >= 0.7:
                    self._emit("metacognition.finding", {
                        "kind": f.kind.value, "subject": f.subject, "severity": f.severity,
                        "detail": f.detail,
                    }, context, priority=EventPriority.HIGH)
            return artifact

    # --- oversight hooks (items 33-37) — peek without advancing the cursor - #

    def oversee(self, subject: str) -> Assessment:
        window = self._observer.observe(since=self._cursor)  # peek (no cursor advance)
        fn = {
            "reasoning": assessors.assess_reasoning, "prediction": assessors.assess_prediction,
            "attention": assessors.assess_attention, "working_memory": assessors.assess_working_memory,
            "executive": assessors.assess_executive, "runtime": assessors.assess_runtime,
            "cognitive_health": assessors.assess_health, "cognitive_performance": assessors.assess_performance,
        }.get(subject, assessors.assess_health)
        return fn(window, self._config)

    def oversee_executive(self) -> Assessment:
        return self.oversee("executive")

    def oversee_reasoning(self) -> Assessment:
        return self.oversee("reasoning")

    def oversee_prediction(self) -> Assessment:
        return self.oversee("prediction")

    def oversee_attention(self) -> Assessment:
        return self.oversee("attention")

    def oversee_working_memory(self) -> Assessment:
        return self.oversee("working_memory")

    # --- reports & proposal hooks (items 38-41) -------------------------- #

    def constitutional_audit(self, context: ExecutionContext | None = None) -> ConstitutionalAuditReport:
        window = self._observer.observe(since=self._cursor)
        report = self._compliance.audit(window, seq=self._services.clock.current())
        self._emit("metacognition.audit", {"compliant": report.compliant,
                                           "violations": len(report.violations)}, context,
                   priority=EventPriority.HIGH)
        return report

    def governance_report(self):
        window = self._observer.observe(since=self._cursor)
        exec_assessment = assessors.assess_executive(window, self._config)
        findings = detectors.analyze_resource_utilization(window, self._config)
        recs = self._recommender.recommend(findings, [exec_assessment], seq=self._services.clock.current())
        return build_governance_report(exec_assessment, findings, recs, seq=self._services.clock.current())

    def learning_recommendations(self) -> list[dict]:
        """Proposals for Learning (item 38) — never commits (MeL9/MeL33: high-impact needs review)."""
        if not self._last_assessments:
            return []
        proposals = []
        for art in list(self._repository.values())[-1:]:
            for f in art.findings:
                if f.kind.value in ("miscalibration", "bias"):
                    proposals.append({"target": "prediction_calibration", "evidence": f.detail,
                                      "requires_human_review": True})
                if f.kind.value == "drift":
                    proposals.append({"target": f.subject, "evidence": f.detail, "requires_human_review": True})
        return proposals

    def development_evidence(self) -> dict:
        """Long-horizon trend evidence for Development (item 39) — read-only observation."""
        keys = ("reasoning_confidence", "prediction_calibration", "escalation_rate", "failure_rate")
        trends = {}
        for k in keys:
            vals = [h[k] for h in self._history if h.get(k) is not None]
            if vals:
                trends[k] = {"n": len(vals), "first": round(vals[0], 4), "last": round(vals[-1], 4),
                             "mean": round(sum(vals) / len(vals), 4)}
        return {"reflections": self._reflections, "trends": trends}

    # --- explicit intervention request (through the Runtime, MeL2) ------- #

    def request_intervention(self, recommendation: InterventionRecommendation, context) -> bool:
        ok = self._intervention.submit(recommendation, context)
        with self._lock:
            if ok:
                self._interventions_requested += 1
        self._emit("metacognition.intervention", {
            "kind": recommendation.kind.value, "target": recommendation.target_engine,
            "op": recommendation.target_op, "reversible": recommendation.reversible, "requested": ok,
        }, context, priority=EventPriority.HIGH)
        return ok

    # --- artifact repository (item 42) ----------------------------------- #

    def artifact(self, artifact_id: str) -> ReflectionArtifact:
        art = self._repository.get(artifact_id)
        if art is None:
            raise ReflectionNotFoundError(artifact_id)
        return art

    def artifacts(self) -> list[ReflectionArtifact]:
        return [self._repository[a] for a in self._artifact_order if a in self._repository]

    def inspect(self) -> dict:
        return {
            "metrics": self.metrics(), "reflections": self._reflections,
            "last_compliant": self._last_audit.compliant if self._last_audit else None,
            "artifacts": len(self._repository), "canonical_writes": self._canonical_writes,
        }

    # --- development hook (gated) ---------------------------------------- #

    def set_config(self, config: MetaConfig, context) -> None:
        """Gated evolution of meta's own policy (MeL34 — never self-modification)."""
        scopes = getattr(getattr(context, "security", None), "scopes", frozenset())
        if self._config.admin_scope not in scopes:
            raise MetaSecurityError("Meta policy evolution requires admin authority (MeL34).")
        with self._lock:
            self._config = config
            self._compliance = ConstitutionalComplianceMonitor(config)
            self._recommender = InterventionRecommendationEngine(config)
        self._emit("metacognition.config_changed", {"auto_request": config.auto_request}, context)

    # --- checkpoint / recovery (items 31, 32) ---------------------------- #

    def checkpoint(self) -> str:
        with self._lock:
            return self._recovery.checkpoint(self._services.clock.current(), list(self._history))

    def recover(self, checkpoint_id: str | None = None) -> dict:
        with self._lock:
            summary = self._recovery.recover(checkpoint_id)
            if summary["restored"]:
                self._history.clear()
                self._history.extend(summary["history"])
            self._emit("metacognition.recovered", {"restored": summary["restored"]}, None)
            return summary

    def canonical_writes(self) -> int:
        return self._canonical_writes  # always 0 (MeL9/MeL13)

    def canonical_watermark(self) -> int:
        return canonical_object_count(self._state)

    # --- metrics / health ------------------------------------------------ #

    def metrics(self) -> MetaMetricsSnapshot:
        with self._lock:
            return MetaMetricsSnapshot(
                reflections=self._reflections, assessments=self._assessment_count,
                findings=self._finding_count, recommendations=self._rec_count,
                interventions_requested=self._interventions_requested, audits=self._audit_count,
                violations_found=self._violation_count, artifacts=len(self._repository),
                events_observed=self._events_observed, canonical_writes=self._canonical_writes,
            )

    def meta_health(self) -> MetaHealthReport:
        return MetaHealthReport(
            healthy=self._started and self._canonical_writes == 0,
            detail="active" if self._started else "stopped", reflections=self._reflections,
            last_compliant=self._last_audit.compliant if self._last_audit else True,
            canonical_writes=self._canonical_writes,
        )

    # --- internals ------------------------------------------------------- #

    def _store(self, artifact: ReflectionArtifact) -> None:
        if len(self._artifact_order) == self._artifact_order.maxlen and self._artifact_order:
            evicted = self._artifact_order[0]
            if evicted not in list(self._artifact_order)[1:]:
                self._repository.pop(evicted, None)
        self._artifact_order.append(artifact.artifact_id)
        self._repository[artifact.artifact_id] = artifact

    @staticmethod
    def _current_metrics(by_subject: dict[str, Assessment]) -> dict:
        r = by_subject.get("reasoning")
        p = by_subject.get("prediction")
        e = by_subject.get("executive")
        run = by_subject.get("runtime")
        esc_rate = 0.0
        if e is not None:
            decisions = e.metrics.get("decisions", 0)
            esc_rate = e.metrics.get("escalations", 0) / decisions if decisions else 0.0
        return {
            "reasoning_confidence": r.metrics.get("mean_confidence") if r else None,
            "prediction_calibration": p.metrics.get("calibration") if p else None,
            "escalation_rate": round(esc_rate, 6),
            "failure_rate": run.metrics.get("failure_rate") if run else None,
        }

    def _health_probe(self) -> HealthReport:
        h = self.meta_health()
        return HealthReport(
            component="metacognition",
            status=HealthStatus.HEALTHY if h.healthy else (HealthStatus.DEGRADED if not self._started else HealthStatus.UNHEALTHY),
            detail=h.detail,
            metrics={"reflections": float(h.reflections), "canonical_writes": float(h.canonical_writes)},
        )

    def _emit(self, event_type: str, payload: Mapping[str, Any], context, *,
              priority: EventPriority = EventPriority.NORMAL) -> None:
        cid = getattr(context, "correlation_id", "metacognition") if context is not None else "metacognition"
        event = CognitiveEvent(
            event_id=uuid.uuid4().hex, type=event_type, sequence=self._services.clock.tick(),
            source="metacognition", correlation_id=cid, payload=dict(payload), priority=priority,
        )
        self._services.events.publish(event)
