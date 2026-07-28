"""The Attention Engine — the gatekeeper of consciousness.

The first decision-making cognitive engine. It evaluates candidates by a
multi-factor salience vector, runs a biased competition, selects the winning
focus coalition, inhibits the losers, and activates Working Memory — deciding
what becomes conscious. It performs NO reasoning, NO executive decision, NO
prediction, NO learning. It reads/writes attention state (R3) only through the
State Manager, activates WM only through WM's public contract, executes through
the Runtime, and communicates through the Event Bus.
"""

from __future__ import annotations

import dataclasses
import threading
import uuid
from collections import deque
from typing import Any, Mapping, Sequence

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
from ...state import CognitiveStateManager, ObjectStatus, ObjectType, Region
from .competition import compete, is_interrupt
from .contracts import (
    AttendResult,
    AttentionConfig,
    AttentionHealthReport,
    AttentionMetricsSnapshot,
    Candidate,
    SalienceVector,
    ScoredCandidate,
)
from .dynamics import FatigueModel, FocusHistory
from .errors import AttentionSecurityError, UnknownAttentionOperationError
from .port import AttentionWMPort
from .salience import SalienceEngine
from .state_io import read_state, write_state


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


class AttentionEngine(CognitiveEngine):
    ENGINE_NAME = "attention"

    def __init__(
        self,
        services: KernelServices,
        state_manager: CognitiveStateManager,
        wm_port: AttentionWMPort,
        config: AttentionConfig | None = None,
    ) -> None:
        self._services = services
        self._state = state_manager
        self._wm = wm_port
        self._config = config or AttentionConfig()
        self._salience = SalienceEngine(self._config)
        self._history = FocusHistory(self._config.novelty_window)
        self._fatigue = FatigueModel()
        self._lock = threading.RLock()
        self._started = False
        # ephemeral dynamics (reconstructable)
        self._just_defocused: set[str] = set()
        self._prev_low: set[str] = set()
        self._executive_bias: dict[str, float] = {}
        self._prediction_surprise: dict[str, float] = {}
        self._feedback_log: deque = deque(maxlen=256)
        # metrics
        self._cycles = self._evaluated = self._ignitions = self._empty_ignitions = 0
        self._switches = self._interrupts = self._inhibitions = self._distractions = 0

    # --- kernel lifecycle ------------------------------------------------ #

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(name=self.ENGINE_NAME, version="1.0", provides=("attention",))

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
        kernel.register_engine(self.metadata, lambda services: self)
        runtime.register_engine(self.ENGINE_NAME, self)
        self._services.health.register_probe("attention", self._health_probe)
        self.start()

    # --- runtime ExecutableEngine ---------------------------------------- #

    def execute(self, operation: str, payload: Mapping[str, Any], context: ExecutionContext) -> Any:
        if operation == "attend":
            candidates = [
                Candidate(
                    target=c["target"],
                    vector=SalienceVector(**c.get("vector", {})),
                    source=c.get("source", "perception"),
                )
                for c in payload.get("candidates", [])
            ]
            result = self.attend(candidates, context)
            return {"ignited": result.ignited, "coalition": list(result.coalition)}
        if operation == "set_executive_bias":
            self.set_executive_bias(payload["target"], payload["delta"], context)
            return True
        if operation == "set_prediction_surprise":
            self.set_prediction_surprise(payload["target"], payload["surprise"], context)
            return True
        if operation == "feedback":
            self.feedback(payload["target"], payload["outcome"], context)
            return True
        raise UnknownAttentionOperationError(f"Unknown attention operation: {operation!r}")

    # --- the attention pipeline ------------------------------------------ #

    def attend(self, candidates: Sequence[Candidate], context: ExecutionContext, *, workspace: str | None = None) -> AttendResult:
        with self._lock:
            cfg = self._config
            now = self._services.clock.current()

            # Perception / candidate generation: only real cognitive objects compete.
            valid = [c for c in candidates if self._state.exists(c.target)]

            # Current conscious set (WM public read) — for incumbency/hysteresis.
            current: dict[str, str] = {slot.target: slot.handle for slot in self._wm.contents(workspace)}

            # Salience evaluation (bottom-up + top-down + biases + hysteresis + IOR).
            scored: list[ScoredCandidate] = []
            for c in valid:
                ev = self._enrich(c)
                comp, bd = self._salience.score(ev)
                comp = self._adjust(c.target, comp, bd, current, cfg)
                scored.append(ScoredCandidate(c.target, ev, comp, dict(bd), c.source))
            self._evaluated += len(scored)

            # Competition + winner selection (fatigue-adjusted threshold).
            winners, inhibited = compete(scored, cfg, fatigue=self._fatigue.value)
            coalition = [w.target for w in winners]
            score_of = {s.target: s.composite for s in scored}
            ignited_any = bool(coalition)
            if not ignited_any:
                self._empty_ignitions += 1  # AL11 — rest, do not fabricate focus

            # Inhibition BEFORE replacement (AL7): evict incumbents that lost.
            evicted: list[str] = []
            for tgt, ref in current.items():
                if tgt not in coalition:
                    self._wm.evict(ref, context)
                    evicted.append(tgt)

            # Sustain surviving incumbents; ignite new winners into WM (AL16 gate).
            sustained: list[str] = []
            newly: list[str] = []
            for tgt in coalition:
                if tgt in current:
                    self._wm.refresh(current[tgt], context)
                    sustained.append(tgt)
                else:
                    self._wm.ignite(tgt, context, activation=score_of[tgt], salience=score_of[tgt])
                    newly.append(tgt)

            # Global Workspace broadcast confers consciousness (CL15).
            if coalition:
                self._wm.broadcast(context, workspace)

            # Dynamics bookkeeping.
            interrupts = [w for w in winners if is_interrupt(w, cfg)]
            self._just_defocused = set(current) - set(coalition)
            self._history.record(coalition)
            self._switches += len(newly)
            self._interrupts += len(interrupts)
            self._inhibitions += len(inhibited)
            self._detect_distraction(scored, cfg)
            if coalition:
                self._fatigue.effort(len(coalition), cfg)
            else:
                self._fatigue.recover(cfg)

            # Cognitive State update (R3) — atomic, versioned, ledger-recorded.
            self._write_r3(context, coalition, score_of, inhibited, now)

            # Attention events (AL3 auditable).
            self._emit("attention.evaluated", {"candidates": len(scored)}, context)
            if ignited_any:
                self._ignitions += 1
                self._emit(
                    "attention.ignition",
                    {"coalition": coalition, "newly": newly, "evicted": evicted,
                     "interrupts": [w.target for w in interrupts]},
                    context, priority=EventPriority.HIGH,
                )
            else:
                self._emit("attention.rest", {"reason": "no candidate crossed ignition threshold"}, context)
            if inhibited:
                self._emit("attention.inhibited", {"targets": inhibited}, context)

            self._cycles += 1
            return AttendResult(
                ignited=ignited_any, coalition=tuple(coalition), newly_ignited=tuple(newly),
                sustained=tuple(sustained), evicted=tuple(evicted), inhibited=tuple(inhibited),
                salience_map=score_of, seq=now,
            )

    # --- enrichment / adjustment ----------------------------------------- #

    def _enrich(self, candidate: Candidate) -> SalienceVector:
        v = candidate.vector
        novelty = v.novelty if v.novelty > 0 else self._history.novelty(candidate.target)
        goal_relevance = v.goal_relevance if v.goal_relevance > 0 else self._structural_goal_relevance(candidate.target)
        surprise = max(v.surprise, self._prediction_surprise.get(candidate.target, 0.0))
        return dataclasses.replace(v, novelty=novelty, goal_relevance=goal_relevance, surprise=surprise)

    def _adjust(self, target: str, comp: float, bd: Mapping[str, float], current: Mapping[str, str], cfg: AttentionConfig) -> float:
        comp += self._executive_bias.get(target, 0.0)          # executive bias (AL8)
        if target in current:
            comp += cfg.hysteresis_margin                      # incumbency (AL13 sticky focus)
        if target in self._just_defocused:
            comp -= cfg.hysteresis_margin                      # inhibition of return
        comp = _clamp(comp)
        return max(comp, bd.get("safety_gate", 0.0))           # safety floor (AL8 safety-bounded)

    def _structural_goal_relevance(self, target: str) -> float:
        goals = self._state.query(region=Region.R2_INTENTIONAL, type=ObjectType.GOAL, status=ObjectStatus.ACTIVE)
        goal_handles = {g.handle for g in goals}
        if self._state.exists(target):
            for e in self._state.get(target).relationships:
                if e.target in goal_handles:
                    return 0.8
        for g in goals:
            for e in g.relationships:
                if e.target == target:
                    return 0.6
        return 0.0

    def _detect_distraction(self, scored: list[ScoredCandidate], cfg: AttentionConfig) -> None:
        low = {s.target for s in scored if s.composite < cfg.elimination_floor}
        self._distractions += len(low & self._prev_low)  # low-value candidates that keep appearing
        self._prev_low = low

    def _write_r3(self, context, coalition: list[str], score_of: Mapping[str, float], inhibited: list[str], now: int) -> None:
        write_state(
            self._state, context,
            focus={"coalition": list(coalition), "seq": now},
            salience={"map": {t: round(s, 4) for t, s in score_of.items()}, "seq": now},
            inhibition={"inhibited": list(inhibited), "reason": "lost_competition", "seq": now},
        )

    # --- hooks (bias / inspection / feedback / adaptation) --------------- #

    def set_executive_bias(self, target: str, delta: float, context) -> None:
        with self._lock:
            self._executive_bias[target] = delta
        self._emit("attention.executive_bias", {"target": target, "delta": delta}, context)

    def clear_executive_bias(self, target: str) -> None:
        with self._lock:
            self._executive_bias.pop(target, None)

    def set_prediction_surprise(self, target: str, surprise: float, context) -> None:
        with self._lock:
            self._prediction_surprise[target] = surprise
        self._emit("attention.prediction_bias", {"target": target, "surprise": surprise}, context)

    def feedback(self, target: str, outcome: str, context) -> None:
        with self._lock:
            self._feedback_log.append((target, outcome, self._services.clock.current()))
        self._emit("attention.feedback", {"target": target, "outcome": outcome}, context)

    def inspect(self) -> dict:
        state = read_state(self._state)
        focus = state.get(ObjectType.ATTENTION_FOCUS)
        salience = state.get(ObjectType.SALIENCE)
        return {
            "coalition": list(focus.payload.get("coalition", [])) if focus else [],
            "salience_map": dict(salience.payload.get("map", {})) if salience else {},
            "fatigue": self._fatigue.value,
            "metrics": self.metrics(),
        }

    def set_config(self, config: AttentionConfig, context) -> None:
        # Development/Executive adaptation hook — gated (AL17: weights are config).
        if "state:admin" not in context.security.scopes:
            raise AttentionSecurityError("Attention adaptation requires admin authority.")
        with self._lock:
            self._config = config
            self._salience.set_config(config)
        self._emit("attention.config_changed", {"ignition_threshold": config.ignition_threshold}, context)

    # --- recovery / metrics / health ------------------------------------ #

    def reconstruct(self) -> int:
        """Rebuild ephemeral dynamics from the durable R3 attention record."""
        with self._lock:
            state = read_state(self._state)
            focus = state.get(ObjectType.ATTENTION_FOCUS)
            coalition = list(focus.payload.get("coalition", [])) if focus else []
            self._history.clear()
            self._history.record(coalition)
            return len(coalition)

    def metrics(self) -> AttentionMetricsSnapshot:
        with self._lock:
            return AttentionMetricsSnapshot(
                cycles=self._cycles, evaluated=self._evaluated, ignitions=self._ignitions,
                empty_ignitions=self._empty_ignitions, switches=self._switches,
                interrupts=self._interrupts, inhibitions=self._inhibitions,
                distractions=self._distractions, fatigue=round(self._fatigue.value, 4),
            )

    def attention_health(self) -> AttentionHealthReport:
        state = read_state(self._state)
        focus = state.get(ObjectType.ATTENTION_FOCUS)
        size = len(focus.payload.get("coalition", [])) if focus else 0
        return AttentionHealthReport(
            healthy=self._started and self._fatigue.value < 0.95,
            detail="active" if self._started else "stopped",
            fatigue=round(self._fatigue.value, 4), last_coalition_size=size,
        )

    def _health_probe(self) -> HealthReport:
        h = self.attention_health()
        return HealthReport(
            component="attention",
            status=HealthStatus.HEALTHY if h.healthy else (HealthStatus.DEGRADED if not self._started else HealthStatus.UNHEALTHY),
            detail=h.detail, metrics={"fatigue": h.fatigue, "coalition": float(h.last_coalition_size)},
        )

    def _emit(self, event_type: str, payload: Mapping[str, Any], context, *, priority: EventPriority = EventPriority.NORMAL) -> None:
        cid = context.correlation_id if context is not None else "attention"
        event = CognitiveEvent(
            event_id=uuid.uuid4().hex, type=event_type, sequence=self._services.clock.tick(),
            source="attention", correlation_id=cid, payload=payload, priority=priority,
        )
        self._services.events.publish(event)
