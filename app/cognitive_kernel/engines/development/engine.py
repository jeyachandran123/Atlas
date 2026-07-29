"""The Development Engine — the authority for long-term capability evolution (Phase 9).

Development studies **long-term aggregate** evidence (DeL12), certifies **per-capability**
maturity (DeL9), detects architectural limitations and gaps, and produces **evidence-
backed, versioned evolution proposals** and roadmaps (proposals only). It never performs
cognition, learning, prediction, governance, or attention; it never modifies canonical
state or any engine; it is **bounded** (it improves the *use* of faculties within fixed
architectural limits — DeL13) and **realized by Learning** (DeL10). It writes no canonical
state, imports no sibling engine, and every artifact is immutable and auditable (DeL11).
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
from .contracts import (
    Capability,
    CapabilityAssessment,
    DevelopmentArtifact,
    DevelopmentConfig,
    DevelopmentHealthReport,
    DevelopmentMetricsSnapshot,
    DevelopmentRoadmap,
    EvolutionProposal,
    MaturityLevel,
    ReviewTier,
)
from .errors import DevelopmentSecurityError, ProposalNotFoundError, UnknownDevelopmentOperationError
from .evidence import DevelopmentEvidenceAggregator
from .limitations import ArchitecturalLimitationDetector, GapAnalyzer
from .maturity import CapabilityMaturityModel
from .policy import DevelopmentPolicyManager
from .ports import NullReviewPort, RuntimeReviewPort
from .proposals import EvolutionProposalGenerator, RoadmapGenerator
from .recovery import DevelopmentRecovery
from .reports import build_trace, digest, overall_confidence, summarize
from .state_io import canonical_object_count
from .trends import LongTermTrendAnalyzer


class DevelopmentEngine(CognitiveEngine):
    ENGINE_NAME = "development"

    def __init__(
        self,
        services: KernelServices,
        state_manager: CognitiveStateManager,
        config: DevelopmentConfig | None = None,
        *,
        review_port: Any | None = None,
    ) -> None:
        self._services = services
        self._state = state_manager
        self._config = config or DevelopmentConfig()
        self._aggregator = DevelopmentEvidenceAggregator(services, state_manager)
        self._cmm = CapabilityMaturityModel(self._config)
        self._trends = LongTermTrendAnalyzer(self._config)
        self._limits = ArchitecturalLimitationDetector(self._config)
        self._gaps = GapAnalyzer(self._config)
        self._policy = DevelopmentPolicyManager(self._config)
        self._proposals = EvolutionProposalGenerator(self._config, self._policy)
        self._roadmap_gen = RoadmapGenerator(self._config)
        self._review = review_port or NullReviewPort()
        self._recovery = DevelopmentRecovery(services)
        self._lock = threading.RLock()
        self._started = False
        self._history: deque = deque(maxlen=self._config.history_limit)
        self._versions: dict[str, int] = {}
        self._certifications: dict[Capability, CapabilityAssessment] = {}
        self._repository: dict[str, DevelopmentArtifact] = {}
        self._artifact_order: deque = deque(maxlen=self._config.artifact_limit)
        self._roadmap_version = 0
        self._last_artifact: DevelopmentArtifact | None = None
        self._regressing = False
        # metrics
        self._cycles = self._assessment_count = self._trend_count = self._limitation_count = 0
        self._gap_count = self._proposal_count = self._submitted = self._roadmap_count = self._events = 0
        self._canonical_writes = 0  # invariant: remains 0 (DeL13)

    # --- kernel lifecycle ------------------------------------------------ #

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.ENGINE_NAME, version="1.0", provides=("development",),
            depends_on=("learning", "metacognition", "executive", "prediction", "reasoning"),
            constitutional_scope=tuple(f"DeL{i}" for i in range(1, 17)),
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
        if isinstance(self._review, NullReviewPort):
            self._review = RuntimeReviewPort(runtime)  # review routed via the Executive (runtime)
        kernel.register_engine(self.metadata, lambda services: self)
        runtime.register_engine(self.ENGINE_NAME, self)
        self._services.health.register_probe("development", self._health_probe)
        self.start()

    # --- runtime ExecutableEngine ---------------------------------------- #

    def execute(self, operation: str, payload: Mapping[str, Any], context: ExecutionContext) -> Any:
        if operation == "develop":
            art = self.develop(context)
            return {"artifact_id": art.artifact_id, "assessments": len(art.assessments),
                    "limitations": len(art.limitations), "gaps": len(art.gaps),
                    "proposals": len(art.proposals), "roadmap_items": len(art.roadmap.items),
                    "confidence": art.confidence}
        if operation == "submit_for_review":
            return {"submitted": self.submit_for_review(context)}
        if operation == "assess":
            a = self.assess_capability(Capability(payload.get("capability", "reasoning")))
            return {"capability": a.capability.value, "maturity": a.maturity.name, "score": a.score}
        raise UnknownDevelopmentOperationError(f"Unknown development operation: {operation!r}")

    # --- the development pipeline ---------------------------------------- #

    def develop(self, context: ExecutionContext) -> DevelopmentArtifact:
        with self._lock:
            session_id = "dev-" + uuid.uuid4().hex
            seq = self._services.clock.current()
            # 1. Aggregate long-term evidence (DeL12).
            window = self._aggregator.aggregate()
            self._events += window.horizon
            # 2. Per-capability maturity, with gain-slow / lose-fast reconciliation (DeL6/DeL9/DeL11).
            assessments = [self._reconcile(a) for a in self._cmm.assess_all(window, self._versions)]
            for a in assessments:
                self._certifications[a.capability] = a
                self._versions[a.capability.value] = a.version
            self._history.append({"scores": {a.capability.value: a.score for a in assessments}, "seq": seq})
            # 3. Trends; regression is a fail-safe signal (DeL14).
            trends = self._trends.analyze(list(self._history))
            self._regressing = self._trends.regressing(trends)
            # 4. Limitations and 5. gaps (within fixed architectural bounds — DeL13).
            limitations = self._limits.detect(window, assessments, trends)
            gaps = self._gaps.analyze(assessments)
            # 6. Evolution proposals (proposals only; constitution-touching ones blocked).
            proposals = self._proposals.generate(limitations, gaps, versions=self._versions, seq=seq)
            # 7. Roadmap (versioned).
            self._roadmap_version += 1
            roadmap = self._roadmap_gen.build(gaps, proposals, version=self._roadmap_version, seq=seq)
            # 8. Immutable development artifact (auditable — DeL11).
            trace = build_trace(window, assessments, trends, limitations, gaps, proposals, roadmap)
            artifact = DevelopmentArtifact(
                artifact_id="art-" + uuid.uuid4().hex, session_id=session_id, window_id=window.window_id,
                seq=seq, assessments=tuple(assessments), trends=tuple(trends), limitations=tuple(limitations),
                gaps=tuple(gaps), proposals=tuple(proposals), roadmap=roadmap,
                summary=summarize(assessments, limitations, proposals),
                confidence=overall_confidence(assessments), digest=digest(trace),
            )
            self._store(artifact)
            self._last_artifact = artifact
            self._cycles += 1
            self._assessment_count += len(assessments)
            self._trend_count += len(trends)
            self._limitation_count += len(limitations)
            self._gap_count += len(gaps)
            self._proposal_count += len(proposals)
            self._roadmap_count += 1
            # 9. Publish audit events (auditable — DeL11).
            self._emit("development.cycle", {
                "session": session_id, "assessments": len(assessments), "limitations": len(limitations),
                "proposals": len(proposals), "roadmap_version": roadmap.version, "confidence": artifact.confidence,
            }, context)
            if self._regressing:  # fail-safe: recommend escalation (DeL14) — a signal, not an action
                self._emit("development.regression", {
                    "declining": [t.metric for t in trends if t.direction.value == "declining"],
                }, context, priority=EventPriority.HIGH)
            return artifact

    def _reconcile(self, raw: CapabilityAssessment) -> CapabilityAssessment:
        """Gain slow (+1 level max), lose fast (adopt a lower level immediately) — DeL6."""
        prior = self._certifications.get(raw.capability)
        if prior is not None and raw.maturity > prior.maturity:
            capped = MaturityLevel(min(int(raw.maturity), int(prior.maturity) + 1))
            return dataclasses.replace(raw, maturity=capped)
        return raw

    # --- review submission (proposals only — DeL3/DeL8) ------------------ #

    def submit_for_review(self, context) -> int:
        """Submit the last artifact's non-forbidden proposals for review — never applies them."""
        if self._last_artifact is None:
            return 0
        submitted = 0
        for p in self._last_artifact.proposals:
            if p.review_tier is ReviewTier.FORBIDDEN:
                continue
            if self._review.submit(p, context):
                submitted += 1
                self._emit("development.proposal_submitted", {
                    "proposal": p.proposal_id, "tier": p.review_tier.value, "kind": p.kind.value,
                }, context, priority=EventPriority.HIGH)
        with self._lock:
            self._submitted += submitted
        return submitted

    # --- consumption & export hooks (items 26/27/28/35) ------------------ #

    def assess_capability(self, capability: Capability) -> CapabilityAssessment:
        window = self._aggregator.aggregate()  # peek; does not advance certification versions
        return self._cmm.assess(capability, window, version=self._versions.get(capability.value, 0) + 1)

    def roadmap(self) -> DevelopmentRoadmap | None:
        return self._last_artifact.roadmap if self._last_artifact else None

    def development_recommendations(self) -> list[dict]:
        """Export evolution proposals for Executive/human/Learning consumption (item 26)."""
        if self._last_artifact is None:
            return []
        return [{"proposal_id": p.proposal_id, "kind": p.kind.value, "capability": p.capability.value,
                 "title": p.title, "review_tier": p.review_tier.value, "rationale": p.rationale}
                for p in self._last_artifact.proposals]

    def maturity_tracking(self) -> dict:
        """Per-capability maturity + certification version (items 13/14/15; DeL9/DeL11)."""
        return {cap.value: {"maturity": a.maturity.name, "score": a.score, "version": a.version}
                for cap, a in self._certifications.items()}

    def future_capability_planning(self) -> list[dict]:
        """Long-horizon roadmap items (item 35) — recommendations for a future version."""
        rm = self.roadmap()
        if rm is None:
            return []
        return [{"capability": i.capability.value, "from": i.from_level.name, "to": i.to_level.name,
                 "horizon": i.horizon, "proposals": list(i.proposals)} for i in rm.items if i.horizon == "long"]

    def learning_evidence(self) -> dict:
        w = self._aggregator.aggregate()
        return {"learning_committed": w.rate("learning.committed"), "learning_cycles": w.rate("learning.cycles"),
                "learned_beliefs": w.state_facts.get("learned_beliefs", 0.0)}

    def meta_trends(self) -> dict:
        w = self._aggregator.aggregate()
        return {"reflections": w.rate("meta.reflections"), "compliance": w.rate("meta.compliance")}

    def artifact(self, artifact_id: str) -> DevelopmentArtifact:
        art = self._repository.get(artifact_id)
        if art is None:
            raise ProposalNotFoundError(artifact_id)
        return art

    def artifacts(self) -> list[DevelopmentArtifact]:
        return [self._repository[a] for a in self._artifact_order if a in self._repository]

    def inspect(self) -> dict:
        return {"metrics": self.metrics(), "regressing": self._regressing,
                "maturity": self.maturity_tracking(), "canonical_writes": self._canonical_writes}

    # --- development hook (gated) ---------------------------------------- #

    def set_config(self, config: DevelopmentConfig, context) -> None:
        scopes = getattr(getattr(context, "security", None), "scopes", frozenset())
        if self._config.admin_scope not in scopes:
            raise DevelopmentSecurityError("Development policy evolution requires admin authority.")
        with self._lock:
            self._config = config
            self._cmm = CapabilityMaturityModel(config)
            self._policy = DevelopmentPolicyManager(config)
            self._proposals = EvolutionProposalGenerator(config, self._policy)
        self._emit("development.config_changed", {"target_maturity": config.target_maturity.name}, context)

    # --- checkpoint / recovery (items 22/23) ----------------------------- #

    def checkpoint(self) -> str:
        with self._lock:
            return self._recovery.checkpoint(self._services.clock.current(), list(self._history),
                                             dict(self._versions))

    def recover(self, checkpoint_id: str | None = None) -> dict:
        with self._lock:
            summary = self._recovery.recover(checkpoint_id)
            if summary["restored"]:
                self._history.clear()
                self._history.extend(summary["history"])
                self._versions = dict(summary.get("versions", {}))
            self._emit("development.recovered", {"restored": summary["restored"]}, None)
            return summary

    def canonical_writes(self) -> int:
        return self._canonical_writes  # always 0 (DeL13)

    def canonical_watermark(self) -> int:
        return canonical_object_count(self._state)

    # --- metrics / health ------------------------------------------------ #

    def metrics(self) -> DevelopmentMetricsSnapshot:
        with self._lock:
            return DevelopmentMetricsSnapshot(
                cycles=self._cycles, assessments=self._assessment_count, trends_detected=self._trend_count,
                limitations_detected=self._limitation_count, gaps_detected=self._gap_count,
                proposals_generated=self._proposal_count, proposals_submitted=self._submitted,
                roadmaps=self._roadmap_count, artifacts=len(self._repository), events_observed=self._events,
                canonical_writes=self._canonical_writes,
            )

    def development_health(self) -> DevelopmentHealthReport:
        return DevelopmentHealthReport(
            healthy=self._started and self._canonical_writes == 0, detail="active" if self._started else "stopped",
            cycles=self._cycles, canonical_writes=self._canonical_writes, regressing=self._regressing,
        )

    def _health_probe(self) -> HealthReport:
        h = self.development_health()
        return HealthReport(
            component="development",
            status=HealthStatus.HEALTHY if h.healthy else (HealthStatus.DEGRADED if not self._started else HealthStatus.UNHEALTHY),
            detail=h.detail,
            metrics={"cycles": float(h.cycles), "canonical_writes": float(h.canonical_writes)},
        )

    def _store(self, artifact: DevelopmentArtifact) -> None:
        if len(self._artifact_order) == self._artifact_order.maxlen and self._artifact_order:
            evicted = self._artifact_order[0]
            if list(self._artifact_order).count(evicted) == 1:
                self._repository.pop(evicted, None)
        self._artifact_order.append(artifact.artifact_id)
        self._repository[artifact.artifact_id] = artifact

    def _emit(self, event_type: str, payload: Mapping[str, Any], context, *,
              priority: EventPriority = EventPriority.NORMAL) -> None:
        cid = getattr(context, "correlation_id", "development") if context is not None else "development"
        event = CognitiveEvent(
            event_id=uuid.uuid4().hex, type=event_type, sequence=self._services.clock.tick(),
            source="development", correlation_id=cid, payload=dict(payload), priority=priority,
        )
        self._services.events.publish(event)
