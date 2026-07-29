"""The Prediction Engine — the faculty that imagines possible futures (Phase 6).

The Simulation Controller: it constructs **isolated, in-memory, reference-only**
simulation branches, generates bounded multi-scenario futures, runs the forward
model, estimates risk and opportunity asymmetrically, types uncertainty, and
returns horizon-decayed, confidence-calibrated **hypothetical** forecasts to the
Executive — and then destroys the branch (or archives it for audit). It **never
modifies canonical Cognitive State** (PrL8), never becomes belief (PrL9), never
reasons, attends, learns, or decides (PrL20). It reads State read-only through the
State Manager, consumes conscious content only through Working Memory, responds to
Executive requests, and communicates only through the Runtime and the Event Bus —
importing no sibling engine.
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
from .branch import SimulationManager
from .contracts import (
    BranchKind,
    Driver,
    Forecast,
    PredictionConfig,
    PredictionHealthReport,
    PredictionMetricsSnapshot,
    PredictionRequest,
    RiskForecast,
)
from .drivers import DriverCollector
from .errors import PredictionSecurityError, UnknownPredictionOperationError
from .forecast import ForecastManager
from .ports import NullReasoningFeedbackPort, NullWMReadPort, RuntimeWMReadPort
from .recovery import PredictionRecovery
from .scenarios import compare_scenarios
from .state_io import canonical_object_count, region_counts


class PredictionEngine(CognitiveEngine):
    ENGINE_NAME = "prediction"

    def __init__(
        self,
        services: KernelServices,
        state_manager: CognitiveStateManager,
        config: PredictionConfig | None = None,
        *,
        wm_read: Any | None = None,
        reasoning_feedback: Any | None = None,
    ) -> None:
        self._services = services
        self._state = state_manager
        self._config = config or PredictionConfig()
        self._drivers = DriverCollector(state_manager)
        self._forecaster = ForecastManager(self._config)
        self._sim = SimulationManager(self._config, services.clock)
        self._wm = wm_read or NullWMReadPort()
        self._reasoning_feedback = reasoning_feedback or NullReasoningFeedbackPort()
        self._recovery = PredictionRecovery(services)
        self._lock = threading.RLock()
        self._started = False
        self._history: deque = deque(maxlen=self._config.history_limit)
        self._retained: dict[str, Forecast] = {}
        # metrics
        self._forecasts = self._risk_assessments = self._counterfactuals = 0
        self._scenarios_generated = self._samples_run = 0
        self._canonical_writes = 0  # invariant: remains 0 (PrL8, by construction)

    # --- kernel lifecycle ------------------------------------------------ #

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.ENGINE_NAME, version="1.0", provides=("prediction",),
            depends_on=("working_memory",),
            constitutional_scope=tuple(f"PrL{i}" for i in range(1, 23)),
        )

    def initialize(self, services: KernelServices) -> None:
        self._services = services

    def start(self) -> None:
        with self._lock:
            self._started = True

    def stop(self) -> None:
        with self._lock:
            self._sim.cleanup_all()  # destroy any open branches (item 36)
            self._started = False

    def health(self) -> HealthReport:
        return self._health_probe()

    def register(self, kernel, runtime) -> None:
        if isinstance(self._wm, NullWMReadPort):
            self._wm = RuntimeWMReadPort(runtime, self._state)  # WM reads by name (runtime)
        kernel.register_engine(self.metadata, lambda services: self)
        runtime.register_engine(self.ENGINE_NAME, self)
        self._services.health.register_probe("prediction", self._health_probe)
        self.start()

    # --- runtime ExecutableEngine ---------------------------------------- #

    def execute(self, operation: str, payload: Mapping[str, Any], context: ExecutionContext) -> Any:
        if operation == "forecast":
            f = self.forecast(self._request_from(payload), context)
            return self._forecast_dto(f)
        if operation == "assess_risk":
            r = self.assess_risk(self._request_from(payload), context)
            return {"risk": r.risk, "severity": r.severity, "probability": r.probability,
                    "confidence": r.confidence, "uncertainty": r.uncertainty,
                    "top_drivers": list(r.top_drivers), "hypothetical": r.hypothetical}
        if operation == "counterfactual":
            f = self.counterfactual(self._request_from(payload), context)
            return self._forecast_dto(f)
        raise UnknownPredictionOperationError(f"Unknown prediction operation: {operation!r}")

    def _request_from(self, p: Mapping[str, Any]) -> PredictionRequest:
        drivers = tuple(
            Driver(name=d["name"], probability=float(d.get("probability", 0.5)),
                   impact=float(d.get("impact", 1.0)), source=d.get("source", ""), note=d.get("note", ""))
            for d in p.get("drivers", [])
        )
        return PredictionRequest(
            request_id=p.get("request_id", "pred-" + uuid.uuid4().hex),
            target=p.get("target", "outcome"), horizon=int(p.get("horizon", 1)),
            baseline=float(p.get("baseline", 0.0)), drivers=drivers,
            num_scenarios=int(p.get("num_scenarios", self._config.default_scenarios)),
            num_samples=int(p.get("num_samples", 0)), interventions=dict(p.get("interventions", {})),
            seed=p.get("seed"), stakes=float(p.get("stakes", 0.0)),
            threshold=float(p.get("threshold", 0.5)), retain=bool(p.get("retain", False)),
            use_working_memory=bool(p.get("use_working_memory", False)),
            context_handles=tuple(p.get("context_handles", ())),
            kind=BranchKind(p.get("kind", "prediction")), source=p.get("source", "executive"),
        )

    def _forecast_dto(self, f: Forecast) -> dict:
        return {
            "request_id": f.request_id, "target": f.target, "outcome_probability": f.outcome_probability,
            "expected_value": f.expected_value, "risk": f.risk, "opportunity": f.opportunity,
            "uncertainty": f.uncertainty, "uncertainty_kind": f.uncertainty_kind.value,
            "confidence": f.confidence, "horizon": f.horizon, "grounded": f.grounded,
            "hypothetical": f.hypothetical, "scenarios": len(f.scenarios), "branch_id": f.branch_id,
        }

    # --- the simulation pipeline ----------------------------------------- #

    def forecast(self, request: PredictionRequest, context: ExecutionContext) -> Forecast:
        """Executive Forecast API (item 30). Imagines possible futures; commits nothing."""
        with self._lock:
            f = self._produce(request, context)
            self._forecasts += 1
            self._emit("prediction.forecast", {
                "request_id": f.request_id, "target": f.target, "p": f.outcome_probability,
                "confidence": f.confidence, "horizon": f.horizon, "hypothetical": True,
            }, context)
            return f

    def assess_risk(self, request: PredictionRequest, context: ExecutionContext) -> RiskForecast:
        """Executive Risk API (item 31). Asymmetric, tail-weighted risk (PrL17)."""
        with self._lock:
            f = self._produce(request, context)
            rf = self._forecaster.risk_only(f)
            self._risk_assessments += 1
            self._emit("prediction.risk", {
                "request_id": rf.request_id, "risk": rf.risk, "severity": rf.severity,
                "confidence": rf.confidence, "hypothetical": True,
            }, context, priority=EventPriority.HIGH)
            return rf

    def counterfactual(self, request: PredictionRequest, context: ExecutionContext) -> Forecast:
        """Counterfactual reasoning (items 15/16): a contrary-to-fact world (PrL10)."""
        cf = request if request.kind is BranchKind.COUNTERFACTUAL else \
            dataclasses.replace(request, kind=BranchKind.COUNTERFACTUAL)
        with self._lock:
            f = self._produce(cf, context)
            self._counterfactuals += 1
            self._emit("prediction.counterfactual", {
                "request_id": f.request_id, "interventions": dict(cf.interventions), "hypothetical": True,
            }, context)
            return f

    def compare(self, requests, context: ExecutionContext) -> dict:
        """Scenario/action comparison (item 22): forecast each and rank by desirability."""
        forecasts = [self.forecast(r, context) for r in requests]
        ranked = sorted(forecasts, key=lambda f: (-(f.outcome_probability * f.expected_value), f.request_id))
        return {"ranking": tuple(f.request_id for f in ranked),
                "forecasts": {f.request_id: self._forecast_dto(f) for f in forecasts}}

    def _produce(self, request: PredictionRequest, context) -> Forecast:
        """Branch → load context → simulate → evaluate → destroy/archive. Zero canonical writes."""
        seq = self._services.clock.current()
        # Load conscious context (WM, read-only) + explicit references.
        handles = list(request.context_handles)
        if request.use_working_memory:
            handles += self._wm.conscious_refs(context)
        ctx = self._drivers.collect(handles, target=request.target, baseline=request.baseline)
        # Isolated branch (no write path to reality — PrL8).
        branch = self._sim.create(request, ctx.references, ctx.drivers)
        # Forward model + evaluation.
        forecast = self._forecaster.run(request, ctx, seq=seq, branch_id=branch.branch_id)
        self._scenarios_generated += len(forecast.scenarios)
        self._samples_run += min(self._config.max_samples, request.num_samples or self._config.default_samples)
        self._sim.mark_evaluated(branch.branch_id)
        # Lifecycle: destroy (default) or archive for audit (item 36 / PrL13).
        if request.retain or self._config.retain_default:
            self._sim.archive(branch.branch_id)
            self._retained[branch.branch_id] = forecast
        else:
            self._sim.destroy(branch.branch_id)
        self._record_history(forecast)
        return forecast

    # --- reconciliation & hooks (PrL22, items 32-35) --------------------- #

    def reconcile(self, request_id: str, observed_outcome: float, context) -> float:
        """Reconcile a prediction against reality; the surprise drives attention/learning (PrL22)."""
        with self._lock:
            predicted = None
            for entry in self._history:
                if entry["request_id"] == request_id:
                    entry["observed"] = observed_outcome
                    predicted = entry["outcome_probability"]
                    entry["surprise"] = round(abs(observed_outcome - predicted), 6)
                    break
            surprise = 0.0 if predicted is None else round(abs(observed_outcome - predicted), 6)
        self._reasoning_feedback.note_outcome(request_id, observed_outcome, context)
        self._emit("prediction.reconciled", {
            "request_id": request_id, "observed": observed_outcome, "surprise": surprise,
        }, context, priority=EventPriority.HIGH)
        return surprise

    def learning_calibration_candidates(self) -> list[dict]:
        """Predicted-vs-observed pairs for Learning to calibrate on (item 34). Proposals only."""
        with self._lock:
            return [
                {"request_id": e["request_id"], "predicted": e["outcome_probability"],
                 "observed": e["observed"], "surprise": e.get("surprise")}
                for e in self._history if e.get("observed") is not None
            ]

    def inspect(self) -> dict:
        """Meta-cognitive inspection hook (item 33) — read-only."""
        with self._lock:
            return {
                "metrics": self.metrics(), "open_branches": self._sim.open_count(),
                "recent": [e["request_id"] for e in list(self._history)[-8:]],
                "canonical_writes": self._canonical_writes, "region_counts": region_counts(self._state),
            }

    def history(self) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self._history]

    def set_config(self, config: PredictionConfig, context) -> None:
        """Development evolution hook (item 35) — gated on admin authority."""
        scopes = getattr(getattr(context, "security", None), "scopes", frozenset())
        if self._config.admin_scope not in scopes:
            raise PredictionSecurityError("Prediction evolution requires admin authority.")
        with self._lock:
            self._config = config
            self._forecaster = ForecastManager(config)
            self._sim = SimulationManager(config, self._services.clock)
        self._emit("prediction.config_changed", {"calibration": config.calibration}, context)

    # --- checkpoint / recovery (items 28, 29) ---------------------------- #

    def checkpoint(self) -> str:
        with self._lock:
            return self._recovery.checkpoint(self._services.clock.current(), [dict(e) for e in self._history])

    def recover(self, checkpoint_id: str | None = None) -> dict:
        with self._lock:
            summary = self._recovery.recover(checkpoint_id)
            if summary["restored"]:
                self._history.clear()
                self._history.extend(summary["history"])
            self._emit("prediction.recovered", {"restored": summary["restored"]}, None)
            return summary

    def cleanup(self) -> int:
        """Destroy all open branches (item 36) — quarantine hygiene."""
        with self._lock:
            return self._sim.cleanup_all()

    # --- canonical-state protection (item 37) ---------------------------- #

    def canonical_writes(self) -> int:
        """Always 0 — Prediction has no write path to Cognitive State (PrL8)."""
        return self._canonical_writes

    def canonical_watermark(self) -> int:
        return canonical_object_count(self._state)

    # --- metrics / health ------------------------------------------------ #

    def metrics(self) -> PredictionMetricsSnapshot:
        created, destroyed, archived, open_ = self._sim.counts()
        return PredictionMetricsSnapshot(
            forecasts=self._forecasts, risk_assessments=self._risk_assessments,
            counterfactuals=self._counterfactuals, branches_created=created,
            branches_destroyed=destroyed, branches_archived=archived,
            scenarios_generated=self._scenarios_generated, samples_run=self._samples_run,
            canonical_writes=self._canonical_writes, open_branches=open_,
        )

    def prediction_health(self) -> PredictionHealthReport:
        open_ = self._sim.open_count()
        budget_ok = open_ <= self._config.max_open_branches
        return PredictionHealthReport(
            healthy=self._started and budget_ok and self._canonical_writes == 0,
            detail="active" if self._started else "stopped", open_branches=open_,
            budget_ok=budget_ok, canonical_writes=self._canonical_writes,
        )

    def _health_probe(self) -> HealthReport:
        h = self.prediction_health()
        return HealthReport(
            component="prediction",
            status=HealthStatus.HEALTHY if h.healthy else (HealthStatus.DEGRADED if not self._started else HealthStatus.UNHEALTHY),
            detail=h.detail,
            metrics={"open_branches": float(h.open_branches), "canonical_writes": float(h.canonical_writes)},
        )

    # --- internals ------------------------------------------------------- #

    def _record_history(self, forecast: Forecast) -> None:
        self._history.append({
            "request_id": forecast.request_id, "target": forecast.target,
            "outcome_probability": forecast.outcome_probability, "confidence": forecast.confidence,
            "horizon": forecast.horizon, "hypothetical": True, "observed": None, "surprise": None,
            "seq": forecast.seq,
        })

    def _emit(self, event_type: str, payload: Mapping[str, Any], context, *,
              priority: EventPriority = EventPriority.NORMAL) -> None:
        cid = getattr(context, "correlation_id", "prediction") if context is not None else "prediction"
        event = CognitiveEvent(
            event_id=uuid.uuid4().hex, type=event_type, sequence=self._services.clock.tick(),
            source="prediction", correlation_id=cid, payload=dict(payload), priority=priority,
        )
        self._services.events.publish(event)
