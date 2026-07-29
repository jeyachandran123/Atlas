"""The Learning Engine — the exclusive authority for durable cognitive change (Phase 8).

Learning transforms *validated, multi-episode experience* into safe, versioned,
reversible, provenance-bearing knowledge revisions (LeL1). It never learns from a
single event, a hallucination, or a hypothetical prediction; it aggregates evidence,
validates it (defaulting to NO CHANGE — LeL9), obtains impact-scaled authorization
(LeL33), and then commits **only through the State Manager** (versioned + rollback).
It performs no reasoning, prediction, attention, executive governance, or
meta-governance; it imports no sibling engine; it produces immutable, auditable
learning records — including rejections (LeL20).
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
from .aggregator import EvidenceAggregator
from .calibration import CalibrationLearner
from .contracts import (
    CandidateState,
    Impact,
    LearningCandidate,
    LearningConfig,
    LearningHealthReport,
    LearningKind,
    LearningMetricsSnapshot,
    LearningRecord,
    LearningReport,
    ValidationResult,
    Verdict,
)
from .errors import LearningSecurityError, RollbackError, UnknownLearningOperationError
from .experience import ExperienceCollector
from .policy import LearningPolicyManager
from .ports import NullAuthorizationPort, RuntimeAuthorizationPort
from .recovery import LearningRecovery
from .reports import build_report, build_trace, digest, improvement_tracking
from .revision import KnowledgeRevisionManager
from .state_io import canonical_object_count, verify_integrity
from .validation import ValidationPipeline


class LearningEngine(CognitiveEngine):
    ENGINE_NAME = "learning"

    def __init__(
        self,
        services: KernelServices,
        state_manager: CognitiveStateManager,
        config: LearningConfig | None = None,
        *,
        authorization_port: Any | None = None,
    ) -> None:
        self._services = services
        self._state = state_manager
        self._config = config or LearningConfig()
        self._collector = ExperienceCollector(services, state_manager)
        self._aggregator = EvidenceAggregator()
        self._validator = ValidationPipeline(state_manager, self._config)
        self._policy = LearningPolicyManager(self._config)
        self._revision = KnowledgeRevisionManager(state_manager, self._config)
        self._calibration = CalibrationLearner(self._config)
        self._auth = authorization_port or NullAuthorizationPort()
        self._recovery = LearningRecovery(services)
        self._lock = threading.RLock()
        self._started = False
        self._cursor = 0
        self._history: deque = deque(maxlen=self._config.history_limit)
        self._records: dict[str, LearningRecord] = {}
        self._record_order: deque = deque(maxlen=self._config.history_limit)
        self._reversible: dict[str, tuple[str, Any]] = {}  # record_id -> ("belief"|"calibration", data)
        # metrics
        self._cycles = self._examined = self._committed = self._deferred = self._rejected = 0
        self._rolled_back = self._revision_count = self._calibration_count = self._experiences = 0

    # --- kernel lifecycle ------------------------------------------------ #

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.ENGINE_NAME, version="1.0", provides=("learning",),
            depends_on=("reasoning", "prediction", "executive", "metacognition"),
            constitutional_scope=tuple(f"LeL{i}" for i in range(1, 42)),
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
        if isinstance(self._auth, NullAuthorizationPort):
            self._auth = RuntimeAuthorizationPort(runtime)  # authorization via the Executive (runtime)
        kernel.register_engine(self.metadata, lambda services: self)
        runtime.register_engine(self.ENGINE_NAME, self)
        self._services.health.register_probe("learning", self._health_probe)
        self.start()

    # --- runtime ExecutableEngine ---------------------------------------- #

    def execute(self, operation: str, payload: Mapping[str, Any], context: ExecutionContext) -> Any:
        if operation == "learn":
            report = self.learn(context)
            return {"examined": report.examined, "committed": report.committed,
                    "deferred": report.deferred, "rejected": report.rejected}
        if operation == "rollback":
            return {"rolled_back": self.rollback(payload["record_id"], context)}
        if operation == "verify_integrity":
            ok, issues = self.verify_knowledge_integrity()
            return {"ok": ok, "issues": list(issues)}
        raise UnknownLearningOperationError(f"Unknown learning operation: {operation!r}")

    # --- the learning pipeline ------------------------------------------- #

    def learn(self, context: ExecutionContext) -> LearningReport:
        with self._lock:
            seq = self._services.clock.current()
            self._cycles += 1
            collected = self._collector.collect(since=self._cursor)
            self._cursor = self._services.ledger.head()
            self._experiences += len(collected.candidates) + len(collected.calibrations)

            records: list[LearningRecord] = []
            # 1. Calibration learning from realized (reconciled) outcomes (LeL26).
            cal = self._calibration.learn(collected.calibrations, seq=seq)
            if cal is not None:
                records.append(self._calibration_record(cal, seq))
                self._calibration_count += 1

            # 2. Belief / generalization candidates — validated, gated, committed.
            candidates = self._aggregator.aggregate(collected.candidates, seq=seq)
            committed_this_cycle = 0
            for cand in candidates:
                cand = dataclasses.replace(cand, impact=self._policy.classify_impact(cand))
                if committed_this_cycle >= self._config.commit_budget:  # bounded (LeL37)
                    break
                record = self._process(cand, context, seq)
                records.append(record)
                if record.committed:
                    committed_this_cycle += 1
            self._examined += len(candidates)

            report = build_report(records, seq=seq)
            self._committed += report.committed
            self._deferred += report.deferred
            self._rejected += report.rejected
            self._emit("learning.cycle", {
                "examined": report.examined, "committed": report.committed,
                "deferred": report.deferred, "rejected": report.rejected,
            }, context)
            return report

    def _process(self, cand: LearningCandidate, context, seq: int) -> LearningRecord:
        record_id = "rec-" + uuid.uuid4().hex
        # 0. Absolute constitutional constraint — the constitution can never be learned (LeL5).
        forbidden, reason = self._policy.forbidden(cand)
        if forbidden:
            v = ValidationResult(Verdict.INCONSISTENT, cand.aggregate_confidence, False,
                                 len(cand.evidence), len(cand.episodes), (reason,))
            self._consume_sources(cand, context)
            return self._record(record_id, cand, v, None, None, committed=False, authorized_by="", seq=seq)

        # 1. Validation — the burden of proof (LeL9). Default: no change.
        validation = self._validator.validate(cand)
        if validation.verdict is not Verdict.PASS:
            # Insufficient-evidence candidates stay PROPOSED to accumulate more episodes (LeL7);
            # other failures are terminal for this claim and are consumed.
            if validation.verdict is not Verdict.INSUFFICIENT_EVIDENCE:
                self._consume_sources(cand, context)
            return self._record(record_id, cand, validation, None, None, committed=False, authorized_by="", seq=seq)

        # 2. Impact-scaled authorization (LeL33): LOW automatic; MODERATE/HIGH gated.
        authorization = None
        authorized_by = "automatic"
        if self._policy.requires_authorization(cand.impact):
            authorization = self._auth.authorize(cand, context)
            if authorization.escalated:  # human review gate — deferred, not committed (LeL17)
                deferred = dataclasses.replace(validation, verdict=Verdict.NEEDS_AUTHORIZATION)
                self._consume_sources(cand, context)  # handed to human review; not re-processed
                return self._record(record_id, cand, deferred, authorization, None, committed=False,
                                    authorized_by="human", seq=seq)
            if not authorization.approved:
                declined = dataclasses.replace(validation, verdict=Verdict.NEEDS_AUTHORIZATION)
                self._consume_sources(cand, context)
                return self._record(record_id, cand, declined, authorization, None, committed=False,
                                    authorized_by=authorization.authority, seq=seq)
            authorized_by = authorization.authority

        # 3. Knowledge revision — durable, versioned, reversible, with provenance (LeL13/LeL21/LeL24).
        revision = self._revision.revise(cand, record_id=record_id, context=context, seq=seq)
        self._revision_count += 1
        self._reversible[record_id] = ("belief", revision)
        record = self._record(record_id, cand, validation, authorization, revision, committed=True,
                              authorized_by=authorized_by, seq=seq)
        self._emit("learning.committed", {
            "record": record_id, "target": revision.target_handle, "statement": cand.statement,
            "confidence": cand.aggregate_confidence, "reversible": True,
        }, context, priority=EventPriority.HIGH)
        return record

    # --- rollback (items 29; LeL13/LeL35) -------------------------------- #

    def rollback(self, record_id: str, context) -> bool:
        with self._lock:
            entry = self._reversible.get(record_id)
            if entry is None:
                raise RollbackError(f"no reversible learning record: {record_id}")
            kind, data = entry
            if kind == "belief":
                self._revision.rollback(data, context)
            else:  # calibration
                self._calibration.rollback(float(data))
            self._rolled_back += 1
        self._emit("learning.rolled_back", {"record": record_id, "kind": kind}, context,
                   priority=EventPriority.HIGH)
        return True

    # --- reports & exports (items 33/36/38/39) --------------------------- #

    def learning_report(self):
        return build_report(list(self._records.values()), seq=self._services.clock.current())

    def development_evidence_export(self) -> dict:
        """Long-term improvement evidence for Development (item 33/38) — read-only."""
        return improvement_tracking(list(self._history))

    def verify_knowledge_integrity(self) -> tuple[bool, tuple[str, ...]]:
        return verify_integrity(self._state)

    def calibration(self) -> float:
        return self._calibration.value()

    def record(self, record_id: str) -> LearningRecord:
        return self._records[record_id]

    def records(self) -> list[LearningRecord]:
        return [self._records[r] for r in self._record_order if r in self._records]

    def inspect(self) -> dict:
        return {"metrics": self.metrics(), "calibration": self._calibration.value(),
                "records": len(self._records), "reversible": len(self._reversible)}

    def set_config(self, config: LearningConfig, context) -> None:
        scopes = getattr(getattr(context, "security", None), "scopes", frozenset())
        if self._config.admin_scope not in scopes:
            raise LearningSecurityError("Learning meta-policy evolution requires admin authority (LeL38).")
        with self._lock:
            self._config = config
            self._validator = ValidationPipeline(self._state, config)
            self._policy = LearningPolicyManager(config)
            self._revision = KnowledgeRevisionManager(self._state, config)
        self._emit("learning.config_changed", {"min_episodes": config.min_episodes}, context)

    # --- checkpoint / recovery (items 27/28) ----------------------------- #

    def checkpoint(self) -> str:
        with self._lock:
            return self._recovery.checkpoint(self._services.clock.current(), list(self._history),
                                             self._calibration.to_payload())

    def recover(self, checkpoint_id: str | None = None) -> dict:
        with self._lock:
            summary = self._recovery.recover(checkpoint_id)
            if summary["restored"]:
                self._history.clear()
                self._history.extend(summary["history"])
                if summary.get("calibration"):
                    self._calibration.load_payload(summary["calibration"])
            self._emit("learning.recovered", {"restored": summary["restored"]}, None)
            return summary

    def canonical_watermark(self) -> int:
        return canonical_object_count(self._state)

    # --- metrics / health ------------------------------------------------ #

    def metrics(self) -> LearningMetricsSnapshot:
        with self._lock:
            return LearningMetricsSnapshot(
                cycles=self._cycles, examined=self._examined, committed=self._committed,
                deferred=self._deferred, rejected=self._rejected, rolled_back=self._rolled_back,
                revisions=self._revision_count, calibrations=self._calibration_count,
                experiences_collected=self._experiences,
                false_learning_rate=round(self._rejected / max(1, self._examined), 6),
            )

    def learning_health(self) -> LearningHealthReport:
        ok, _ = verify_integrity(self._state)
        return LearningHealthReport(
            healthy=self._started and ok, detail="active" if self._started else "stopped",
            committed=self._committed, rejected=self._rejected,
            false_learning_rate=round(self._rejected / max(1, self._examined), 6), integrity_ok=ok,
        )

    # --- internals ------------------------------------------------------- #

    def _consume_sources(self, cand: LearningCandidate, context) -> None:
        """Archive the R9 candidate objects for a terminal (non-committed) verdict so
        they are not re-examined — never deleted (LeL27). Provenance stays intact."""
        from ...state import ObjectStatus

        handles = [h for h in cand.source_handles
                   if self._state.exists(h) and self._state.get(h).status is ObjectStatus.PROPOSED]
        if not handles:
            return
        tx = self._state.begin_transaction(context)
        for h in handles:
            tx.update(h, status=ObjectStatus.ARCHIVED, payload_merge={"learning_outcome": "processed"})
        tx.commit()

    def _calibration_record(self, cal: dict, seq: int) -> LearningRecord:
        record_id = "rec-" + uuid.uuid4().hex
        self._reversible[record_id] = ("calibration", cal["from"])
        cand = LearningCandidate(
            candidate_id="cal-" + uuid.uuid4().hex, kind=LearningKind.CALIBRATION, statement="prediction_calibration",
            negated=False, target_handle=None, evidence=(), episodes=tuple(cal["episodes"]),
            source_handles=(), support=cal["to"], oppose=0.0, aggregate_confidence=cal["to"],
            impact=Impact.LOW, state=CandidateState.COMMITTED, created_seq=seq,
        )
        validation = ValidationResult(Verdict.PASS, cal["to"], True, cal["samples"], len(cal["episodes"]),
                                      (f"recalibrated {cal['from']:.3f} -> {cal['to']:.3f} from realized outcomes",))
        return self._record(record_id, cand, validation, None, None, committed=True, authorized_by="automatic",
                            seq=seq, calibration=cal)

    def _record(self, record_id, cand, validation, authorization, revision, *, committed, authorized_by,
                seq, calibration=None) -> LearningRecord:
        trace = build_trace(cand, validation, authorization, revision)
        provenance = (revision.provenance if revision is not None
                      else tuple(f"episode:{e}" for e in cand.episodes))
        record = LearningRecord(
            record_id=record_id, candidate_id=cand.candidate_id, kind=cand.kind, verdict=validation.verdict,
            committed=committed, revision=revision, confidence=cand.aggregate_confidence, impact=cand.impact,
            evidence=cand.evidence, episodes=cand.episodes, authorized_by=authorized_by, provenance=provenance,
            reversible=bool(committed), trace=trace, digest=digest(trace), seq=seq,
        )
        self._store(record)
        return record

    def _store(self, record: LearningRecord) -> None:
        if len(self._record_order) == self._record_order.maxlen and self._record_order:
            evicted = self._record_order[0]
            if list(self._record_order).count(evicted) == 1:
                self._records.pop(evicted, None)
        self._record_order.append(record.record_id)
        self._records[record.record_id] = record
        self._history.append({"record_id": record.record_id, "kind": record.kind.value,
                              "committed": record.committed, "confidence": record.confidence,
                              "impact": record.impact.value, "verdict": record.verdict.value, "seq": record.seq})

    def _health_probe(self) -> HealthReport:
        h = self.learning_health()
        return HealthReport(
            component="learning",
            status=HealthStatus.HEALTHY if h.healthy else (HealthStatus.DEGRADED if not self._started else HealthStatus.UNHEALTHY),
            detail=h.detail,
            metrics={"committed": float(h.committed), "false_learning_rate": h.false_learning_rate},
        )

    def _emit(self, event_type: str, payload: Mapping[str, Any], context, *,
              priority: EventPriority = EventPriority.NORMAL) -> None:
        cid = getattr(context, "correlation_id", "learning") if context is not None else "learning"
        event = CognitiveEvent(
            event_id=uuid.uuid4().hex, type=event_type, sequence=self._services.clock.tick(),
            source="learning", correlation_id=cid, payload=dict(payload), priority=priority,
        )
        self._services.events.publish(event)
