"""The Reasoning Engine — the faculty that transforms conscious content into
justified conclusions (Phase 4). It is the Reasoning Controller of Ch2: it
sequences type-selection -> strategy -> hypothesis management -> substitutable
engine invocation -> calibrated confidence -> consistency -> convergence, obeys
the economy, records an auditable trace, and *proposes* products — committing
nothing (ReL9).

It performs NO attention, owns NO Working Memory, makes NO executive decision,
performs NO prediction, and performs NO learning. It reads conscious content only
through WM's public read contract, reads/writes Cognitive State only through the
State Manager, invokes only substitutable engines behind a port, executes through
the Runtime, and communicates through the Event Bus. It holds no durable state.
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
from ...state import CognitiveStateManager, ObjectStatus, ObjectType, Region
from .confidence import ConfidenceEstimator
from .consistency import AssumptionTracker, ConsistencyGuard
from .contracts import (
    Conclusion,
    EngineRequest,
    EpisodeState,
    ReasoningConfig,
    ReasoningHealthReport,
    ReasoningMetricsSnapshot,
    ReasoningRequest,
    ReasoningStrategy,
    ReasoningType,
    ReasoningResult,
    TerminationReason,
    UncertaintyKind,
)
from .dynamics import (
    ConvergenceMonitor,
    FatigueModel,
    ResourceGovernor,
    StrategySelector,
    TypeSelector,
)
from .errors import EpisodeNotFoundError, ReasoningSecurityError, UnknownReasoningOperationError
from .evidence import EvidenceCollector, EvidenceEvaluator
from .hypothesis import HypothesisGenerator
from .pool import EnginePool, NullPredictionPort, default_pool
from .port import ReasoningWMPort
from .space import WorkingReasoningSpace
from .state_io import read_episode, status_of, write_belief, write_episode, write_learning_candidate
from .trace import TraceBuilder


class ReasoningEngine(CognitiveEngine):
    ENGINE_NAME = "reasoning"

    def __init__(
        self,
        services: KernelServices,
        state_manager: CognitiveStateManager,
        wm_read: ReasoningWMPort,
        config: ReasoningConfig | None = None,
        *,
        pool: EnginePool | None = None,
        prediction_port: Any | None = None,
    ) -> None:
        self._services = services
        self._state = state_manager
        self._wm = wm_read
        self._config = config or ReasoningConfig()
        self._collector = EvidenceCollector(state_manager, wm_read)
        self._evaluator = EvidenceEvaluator()
        self._generator = HypothesisGenerator(self._config)
        self._estimator = ConfidenceEstimator(self._config)
        self._guard = ConsistencyGuard(self._config.hysteresis_margin)
        self._assumptions = AssumptionTracker()
        self._type_selector = TypeSelector()
        self._strategy_selector = StrategySelector(self._config)
        self._governor = ResourceGovernor(self._config)
        self._pool = pool or default_pool()
        self._prediction = prediction_port or NullPredictionPort()
        self._fatigue = FatigueModel()
        self._lock = threading.RLock()
        self._started = False
        # executive / development directives (inbound hooks)
        self._strategy_directive: ReasoningStrategy | None = None
        self._deliberation_directive: dict[str, int] = {}
        self._feedback_log: deque = deque(maxlen=256)
        # metrics
        self._episodes = self._steps = self._hyps = 0
        self._deductions = self._abductions = self._inductions = 0
        self._contradictions = self._conflicts_resolved = self._escalations = 0
        self._interrupts = self._resumptions = self._engine_invocations = 0

    # --- kernel lifecycle ------------------------------------------------ #

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.ENGINE_NAME, version="1.0", provides=("reasoning",),
            depends_on=("working_memory",),
            constitutional_scope=tuple(f"ReL{i}" for i in range(1, 15)),
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
        kernel.register_engine(self.metadata, lambda services: self)
        runtime.register_engine(self.ENGINE_NAME, self)
        self._services.health.register_probe("reasoning", self._health_probe)
        self.start()

    # --- runtime ExecutableEngine ---------------------------------------- #

    def execute(self, operation: str, payload: Mapping[str, Any], context: ExecutionContext) -> Any:
        if operation == "reason":
            request = self._request_from(payload)
            result = self.reason(request, context)
            return {
                "episode_id": result.episode_id,
                "concluded": result.concluded,
                "statement": result.conclusion.statement if result.conclusion else None,
                "negated": result.conclusion.negated if result.conclusion else None,
                "confidence": result.conclusion.confidence if result.conclusion else 0.0,
                "escalated": result.escalated,
                "termination": result.termination.value,
                "steps": len(result.steps),
            }
        if operation == "resume":
            result = self.resume(payload["episode_id"], context)
            return {"episode_id": result.episode_id, "concluded": result.concluded, "state": result.state.value}
        if operation == "set_strategy_directive":
            self.set_strategy_directive(
                ReasoningStrategy(payload["strategy"]) if payload.get("strategy") else None, context
            )
            return True
        if operation == "set_deliberation":
            self.set_deliberation_directive(context, max_steps=payload.get("max_steps"), depth=payload.get("depth"))
            return True
        raise UnknownReasoningOperationError(f"Unknown reasoning operation: {operation!r}")

    def _request_from(self, payload: Mapping[str, Any]) -> ReasoningRequest:
        return ReasoningRequest(
            goal=payload.get("goal", ""),
            question=payload.get("question", ""),
            question_negated=bool(payload.get("question_negated", False)),
            focus=tuple(payload.get("focus", ())),
            type_hint=ReasoningType(payload["type_hint"]) if payload.get("type_hint") else None,
            strategy_hint=ReasoningStrategy(payload["strategy_hint"]) if payload.get("strategy_hint") else None,
            stakes=float(payload.get("stakes", 0.0)),
            reversibility=float(payload.get("reversibility", 1.0)),
            workspace=payload.get("workspace"),
            max_steps=payload.get("max_steps"),
        )

    # --- the reasoning pipeline ------------------------------------------ #

    def reason(self, request: ReasoningRequest, context: ExecutionContext) -> ReasoningResult:
        request = self._apply_directives(request)
        episode_id = "rsn-" + uuid.uuid4().hex
        seq = self._services.clock.current()

        # 1-2. Collect conscious content; evaluate and weight the evidence.
        content = self._collector.collect(request.workspace, request.focus)
        weighted = self._weigh(content, request)

        # 3. Open the (transient, reasoning-local) Working Reasoning Space.
        space = WorkingReasoningSpace(episode_id, request.goal)
        space.seed(weighted)

        # 4. Select the reasoning type and strategy (explicit & recorded — ReL6).
        rtype = self._type_selector.select(request, content)
        strategy = self._strategy_selector.select(rtype, request)

        # 5. Generate and rank hypotheses.
        hyps = self._generator.generate(
            question=request.question, question_negated=request.question_negated,
            evidence=weighted, rules=content.rules, causes=content.causes, analogies=content.analogies,
        )
        hyps = self._generator.rank(hyps, weighted)
        for h in hyps:
            space.add_hypothesis(h)
        with self._lock:
            self._episodes += 1
            self._hyps += len(hyps)

        self._emit(
            "reasoning.initiated",
            {"episode": episode_id, "goal": request.goal, "type": rtype.value,
             "strategy": strategy.value, "hypotheses": len(hyps)},
            context,
        )
        return self._deliberate(
            episode_id=episode_id, request=request, content=content, weighted=weighted,
            space=space, rtype=rtype, strategy=strategy, context=context, seq=seq, resumed=False,
        )

    def resume(self, episode_id: str, context: ExecutionContext) -> ReasoningResult:
        obj = read_episode(self._state, episode_id)
        if obj is None or obj.payload.get("space") is None:
            raise EpisodeNotFoundError(f"No resumable reasoning episode: {episode_id}")
        space = WorkingReasoningSpace.from_payload(obj.payload["space"])
        request = ReasoningRequest(
            goal=obj.payload.get("goal", ""), question=obj.payload.get("question", ""),
            question_negated=bool(space.negations.get(obj.payload.get("question", ""), False) and False),
        )
        request = self._apply_directives(request)
        content = self._collector.collect(request.workspace, request.focus)
        weighted = self._weigh(content, request)
        space.seed(weighted)  # merge any fresh conscious content (§4.3 reconstruct from checkpoint + goal)
        rtype = ReasoningType(obj.payload.get("type", ReasoningType.ABDUCTIVE.value))
        strategy = ReasoningStrategy(obj.payload.get("strategy", ReasoningStrategy.LINEAR.value))
        with self._lock:
            self._resumptions += 1
        self._emit("reasoning.resumed", {"episode": episode_id}, context)
        return self._deliberate(
            episode_id=episode_id, request=request, content=content, weighted=weighted,
            space=space, rtype=rtype, strategy=strategy, context=context,
            seq=self._services.clock.current(), resumed=True,
        )

    def _deliberate(
        self, *, episode_id, request, content, weighted, space, rtype, strategy, context, seq, resumed
    ) -> ReasoningResult:
        cfg = self._config
        trace = TraceBuilder()
        monitor = ConvergenceMonitor()
        max_steps = self._governor.max_steps(request)
        max_depth = self._deliberation_directive.get("depth", cfg.max_depth)
        threshold = self._estimator.sufficient(request.stakes, request.reversibility)

        steps = 0
        engine_calls = 0
        deductions = abductions = inductions = 0
        contradictions: list = []
        unresolved = False
        interrupted = False
        fell_back = False
        term: TerminationReason | None = None

        while True:
            if context.cancellation.is_cancelled or context.budget.exhausted:
                interrupted = True
                break

            ereq = EngineRequest(
                rtype=rtype, goal=request.goal, question=request.question,
                question_negated=request.question_negated, facts=dict(space.facts),
                negations=dict(space.negations), evidence=tuple(weighted),
                hypotheses=tuple(space.hypotheses), rules=tuple(content.rules),
                causes=tuple(content.causes), analogies=tuple(content.analogies), max_depth=max_depth,
            )

            if strategy is ReasoningStrategy.ENSEMBLE:
                products = self._pool.ensemble(ereq, context, cfg.ensemble_size)
                engine_calls += len(products)
                product = self._reconcile(products)
            else:
                product = self._pool.propose(ereq, context)
                engine_calls += 1
            steps += 1
            with self._lock:
                self._fatigue.effort(cfg)

            if product is None:
                # Switch strategy/type on impasse (Ch5) before giving up.
                if rtype is not ReasoningType.PROBABILISTIC and not fell_back:
                    fell_back = True
                    rtype, strategy = ReasoningType.PROBABILISTIC, ReasoningStrategy.SEARCH
                    self._emit("reasoning.strategy_switched", {"episode": episode_id, "to": "probabilistic"}, context)
                    continue
                monitor.update(space.top_confidence())
                term = TerminationReason.IMPASSE
                break

            verified = True
            if strategy is ReasoningStrategy.VERIFY_THEN_TRUST and product.engine != "symbolic":
                verified = self._pool.verify(product.statement, product.negated, ereq, context)

            conf = self._estimator.calibrate(product.engine, product.confidence)
            if not verified:
                conf = round(conf * 0.5, 6)

            if product.steps:  # a multi-step / recursive derivation (deduction)
                for s in product.steps:
                    trace.record(
                        rtype=s.rtype, strategy=strategy, engine=s.engine, premises=s.premises,
                        product=s.product, confidence=s.confidence, rationale=s.rationale, depth=s.depth,
                    )
            else:
                trace.record(
                    rtype=rtype, strategy=strategy, engine=product.engine, premises=product.premises,
                    product=("¬" if product.negated else "") + product.statement,
                    confidence=conf, rationale=product.justification,
                )

            if product.engine == "symbolic" and rtype is ReasoningType.DEDUCTIVE:
                deductions += 1
            elif rtype is ReasoningType.INDUCTIVE:
                inductions += 1
            else:
                abductions += 1

            space.assert_fact(product.statement, product.negated, conf)
            space.upsert_hypothesis(
                statement=product.statement, negated=product.negated, confidence=conf,
                hid=product.hypothesis_id, derivation=rtype.value, supports=product.premises,
            )

            contradictions = self._guard.detect(weighted, space.facts, space.negations)
            for c in contradictions:
                if not c.resolved:
                    unresolved = True
                self._emit(
                    "reasoning.contradiction",
                    {"episode": episode_id, "statement": c.statement, "resolved": c.resolved, "method": c.method},
                    context,
                )

            monitor.update(space.top_confidence())
            stop, term = self._governor.stop(
                monitor=monitor, steps=steps, max_steps=max_steps, threshold=threshold,
                budget_exhausted=context.budget.exhausted, has_candidates=bool(space.hypotheses),
            )
            if stop:
                break

        space.steps = list(trace.steps())
        with self._lock:
            self._steps += steps
            self._engine_invocations += engine_calls
            self._deductions += deductions
            self._abductions += abductions
            self._inductions += inductions
            self._contradictions += len(contradictions)
            self._conflicts_resolved += sum(1 for c in contradictions if c.resolved)

        if interrupted:
            return self._finish_interrupted(episode_id, request, rtype, strategy, space, trace, context, seq)

        return self._conclude(
            episode_id=episode_id, request=request, rtype=rtype, strategy=strategy, space=space,
            trace=trace, weighted=weighted, monitor=monitor, threshold=threshold,
            contradictions=contradictions, unresolved=unresolved, term=term, context=context, seq=seq,
        )

    # --- conclusion / termination ---------------------------------------- #

    def _conclude(
        self, *, episode_id, request, rtype, strategy, space, trace, weighted, monitor, threshold,
        contradictions, unresolved, term, context, seq,
    ) -> ReasoningResult:
        cfg = self._config
        top = space.top_hypothesis()
        runner = space.runner_up()

        if top is None:
            conclusion = None
            concluded = False
        else:
            uncertainty = self._estimator.classify(
                top.confidence, runner.confidence if runner else 0.0,
                threshold=threshold, evidence_count=len(weighted),
            )
            concluded = top.confidence >= threshold and not unresolved
            used = {p for s in trace.steps() for p in s.premises}
            used.add(top.statement)
            evidence_handles = {e.handle for e in weighted}
            supporting_set = {h for h in top.supports if h in evidence_handles}   # abductive/analogical
            supporting_set |= {
                e.handle for e in weighted if e.statement in used and e.negated == top.negated
            }  # deductive leaf premises / direct support
            supporting = tuple(sorted(supporting_set))
            assumptions = self._assumptions.used_by(supporting, weighted)
            conclusion = Conclusion(
                statement=top.statement, negated=top.negated, confidence=top.confidence,
                uncertainty=UncertaintyKind.NONE if concluded else uncertainty,
                hypothesis_id=top.hid, supporting_evidence=supporting,
                contradictions=tuple(sorted(c.statement for c in contradictions)),
                assumptions=assumptions, justification="",
            )

        escalated = unresolved or ((not concluded) and request.stakes >= cfg.escalation_stakes)

        if concluded:
            state, termination = EpisodeState.TERMINATED_SUCCESS, term or TerminationReason.CONVERGED
        elif escalated:
            state, termination = EpisodeState.TERMINATED_ESCALATE, (
                TerminationReason.IMPASSE if unresolved else (term or TerminationReason.IMPASSE)
            )
            with self._lock:
                self._escalations += 1
        else:
            state, termination = EpisodeState.TERMINATED_BUDGET, term or TerminationReason.BUDGET_EXHAUSTED

        if conclusion is not None:
            conclusion = dataclasses.replace(conclusion, justification=trace.explain(conclusion))

        products, learning = self._write_products(
            episode_id, request, rtype, strategy, space, trace, conclusion, state, termination,
            concluded, escalated, context, seq,
        )

        if concluded and conclusion is not None:
            self._emit(
                "reasoning.concluded",
                {"episode": episode_id, "statement": conclusion.statement,
                 "confidence": conclusion.confidence, "products": list(products)},
                context, priority=EventPriority.HIGH,
            )
        elif escalated:
            self._emit(
                "reasoning.escalated",
                {"episode": episode_id,
                 "reason": "unresolved_contradiction" if unresolved else "low_confidence_high_stakes",
                 "confidence": conclusion.confidence if conclusion else 0.0},
                context, priority=EventPriority.HIGH,
            )
        else:
            self._emit("reasoning.terminated", {"episode": episode_id, "termination": termination.value}, context)

        return ReasoningResult(
            episode_id=episode_id, concluded=concluded, conclusion=conclusion,
            hypotheses=tuple(space.hypotheses), steps=trace.steps(), state=state,
            termination=termination, escalated=escalated, products=tuple(products),
            learning_candidates=tuple(learning), seq=seq,
        )

    def _write_products(
        self, episode_id, request, rtype, strategy, space, trace, conclusion, state, termination,
        concluded, escalated, context, seq,
    ) -> tuple[list[str], list[str]]:
        cfg = self._config
        episode_payload = {
            "goal": request.goal, "question": request.question, "type": rtype.value,
            "strategy": strategy.value, "state": state.value, "termination": termination.value,
            "steps": len(trace.steps()), "concluded": concluded, "escalated": escalated,
            "confidence": conclusion.confidence if conclusion else 0.0,
            "conclusion": conclusion.statement if conclusion else None,
            "trace_digest": trace.digest(), "space": space.to_payload(), "seq": seq,
        }
        write_episode(self._state, context, episode_id=episode_id, payload=episode_payload)

        products: list[str] = []
        learning: list[str] = []
        if concluded and conclusion is not None:
            products.append(
                write_belief(
                    self._state, context, statement=conclusion.statement, negated=conclusion.negated,
                    confidence=conclusion.confidence, evidence_handles=conclusion.supporting_evidence,
                    episode_id=episode_id, status=status_of(cfg.belief_status),
                )
            )
            if rtype is ReasoningType.INDUCTIVE:
                learning.append(
                    write_learning_candidate(
                        self._state, context,
                        payload={"generalization": conclusion.statement, "confidence": conclusion.confidence,
                                 "episode": episode_id},
                        episode_id=episode_id, status=status_of("proposed"),
                    )
                )
        return products, learning

    def _finish_interrupted(self, episode_id, request, rtype, strategy, space, trace, context, seq) -> ReasoningResult:
        with self._lock:
            self._interrupts += 1
        payload = {
            "goal": request.goal, "question": request.question, "type": rtype.value,
            "strategy": strategy.value, "state": EpisodeState.INTERRUPTED.value,
            "termination": TerminationReason.INTERRUPTED.value, "steps": len(trace.steps()),
            "concluded": False, "escalated": False, "confidence": space.top_confidence(),
            "conclusion": None, "trace_digest": trace.digest(), "space": space.to_payload(), "seq": seq,
        }
        write_episode(self._state, context, episode_id=episode_id, payload=payload)
        self._emit("reasoning.interrupted", {"episode": episode_id, "steps": len(trace.steps())}, context)
        return ReasoningResult(
            episode_id=episode_id, concluded=False, conclusion=None, hypotheses=tuple(space.hypotheses),
            steps=trace.steps(), state=EpisodeState.INTERRUPTED, termination=TerminationReason.INTERRUPTED,
            escalated=False, products=(), learning_candidates=(), seq=seq,
        )

    # --- helpers --------------------------------------------------------- #

    def _weigh(self, content, request: ReasoningRequest):
        relevant: set[str] = set()
        for r in content.rules:
            relevant.update(r.antecedents)
            relevant.add(r.consequent)
        for c in content.causes:
            relevant.add(c.cause)
            relevant.add(c.effect)
        if request.question:
            relevant.add(request.question)
        return self._evaluator.weigh(
            content.evidence, question=request.question, relevant_statements=frozenset(relevant)
        )

    def _reconcile(self, products):
        if not products:
            return None
        return max(products, key=lambda p: (self._estimator.calibrate(p.engine, p.confidence), p.statement))

    def _apply_directives(self, request: ReasoningRequest) -> ReasoningRequest:
        with self._lock:
            strat = self._strategy_directive
            delib = dict(self._deliberation_directive)
        if strat is not None and request.strategy_hint is None:
            request = dataclasses.replace(request, strategy_hint=strat)
        if "max_steps" in delib and request.max_steps is None:
            request = dataclasses.replace(request, max_steps=delib["max_steps"])
        return request

    # --- hooks (executive / prediction / meta / learning / development) --- #

    def set_strategy_directive(self, strategy: ReasoningStrategy | None, context) -> None:
        """Executive/Meta-Reasoning hook: bias strategy selection (item 33)."""
        with self._lock:
            self._strategy_directive = strategy
        self._emit("reasoning.strategy_directive", {"strategy": strategy.value if strategy else None}, context)

    def set_deliberation_directive(self, context, *, max_steps: int | None = None, depth: int | None = None) -> None:
        """Executive/Meta-Reasoning hook: govern deliberation depth/budget (item 33)."""
        with self._lock:
            if max_steps is not None:
                self._deliberation_directive["max_steps"] = int(max_steps)
            if depth is not None:
                self._deliberation_directive["depth"] = int(depth)
        self._emit("reasoning.deliberation_directive", {"max_steps": max_steps, "depth": depth}, context)

    def request_prediction(self, scenario: Mapping[str, Any], context) -> Mapping[str, Any] | None:
        """Prediction hook (item 34): request a forecast/simulation. Reasoning never
        predicts; it consumes the result if a Prediction engine is wired, else None."""
        if not self._prediction.available():
            self._emit("reasoning.prediction_unavailable", {"scenario": dict(scenario)}, context)
            return None
        result = self._prediction.request(scenario, context)
        self._emit("reasoning.prediction_requested", {"scenario": dict(scenario)}, context)
        return result

    def set_prediction_port(self, port: Any) -> None:
        with self._lock:
            self._prediction = port

    def inspect(self, episode_id: str | None = None) -> dict:
        """Meta-cognitive inspection hook (item 35): a read-only view."""
        view = {
            "metrics": self.metrics(),
            "fatigue": round(self._fatigue.value, 4),
            "engines": self._pool.names(),
            "prediction_available": self._prediction.available(),
        }
        if episode_id is not None:
            obj = read_episode(self._state, episode_id)
            view["episode"] = dict(obj.payload) if obj is not None else None
        return view

    def learning_candidates(self, episode_id: str | None = None) -> list[Any]:
        """Learning-candidate hook (item 36): the PROPOSED R9 proposals (never committed)."""
        cands = self._state.query(
            region=Region.R9_METACOGNITIVE, type=ObjectType.LEARNING_CANDIDATE, status=ObjectStatus.PROPOSED
        )
        if episode_id is not None:
            cands = [c for c in cands if c.payload.get("episode") == episode_id]
        return list(cands)

    def feedback(self, target: str, outcome: str, context) -> None:
        """Learning feedback hook: record a signal (reasoning records; it never learns)."""
        with self._lock:
            self._feedback_log.append((target, outcome, self._services.clock.current()))
        self._emit("reasoning.feedback", {"target": target, "outcome": outcome}, context)

    def set_config(self, config: ReasoningConfig, context) -> None:
        """Development adaptation hook (item 37) — gated on admin authority."""
        if "state:admin" not in context.security.scopes:
            raise ReasoningSecurityError("Reasoning adaptation requires admin authority.")
        with self._lock:
            self._config = config
            self._generator = HypothesisGenerator(config)
            self._estimator = ConfidenceEstimator(config)
            self._guard = ConsistencyGuard(config.hysteresis_margin)
            self._strategy_selector = StrategySelector(config)
            self._governor = ResourceGovernor(config)
        self._emit("reasoning.config_changed", {"confidence_sufficient": config.confidence_sufficient}, context)

    # --- recovery / metrics / health ------------------------------------- #

    def reconstruct(self, episode_id: str) -> int:
        """Rebuild the transient Working Reasoning Space from the durable R6 record (ReL8)."""
        obj = read_episode(self._state, episode_id)
        if obj is None or obj.payload.get("space") is None:
            raise EpisodeNotFoundError(f"No reasoning episode to reconstruct: {episode_id}")
        space = WorkingReasoningSpace.from_payload(obj.payload["space"])
        return len(space.steps)

    def metrics(self) -> ReasoningMetricsSnapshot:
        with self._lock:
            return ReasoningMetricsSnapshot(
                episodes=self._episodes, steps=self._steps, hypotheses_generated=self._hyps,
                deductions=self._deductions, abductions=self._abductions, inductions=self._inductions,
                contradictions=self._contradictions, conflicts_resolved=self._conflicts_resolved,
                escalations=self._escalations, interrupts=self._interrupts, resumptions=self._resumptions,
                engine_invocations=self._engine_invocations, fatigue=round(self._fatigue.value, 4),
            )

    def reasoning_health(self) -> ReasoningHealthReport:
        return ReasoningHealthReport(
            healthy=self._started and self._pool.count() > 0 and self._fatigue.value < 0.98,
            detail="active" if self._started else "stopped",
            fatigue=round(self._fatigue.value, 4), engines_available=self._pool.count(),
        )

    def _health_probe(self) -> HealthReport:
        h = self.reasoning_health()
        return HealthReport(
            component="reasoning",
            status=HealthStatus.HEALTHY if h.healthy else (HealthStatus.DEGRADED if not self._started else HealthStatus.UNHEALTHY),
            detail=h.detail,
            metrics={"fatigue": h.fatigue, "engines": float(h.engines_available)},
        )

    def _emit(self, event_type: str, payload: Mapping[str, Any], context, *, priority: EventPriority = EventPriority.NORMAL) -> None:
        cid = context.correlation_id if context is not None else "reasoning"
        event = CognitiveEvent(
            event_id=uuid.uuid4().hex, type=event_type, sequence=self._services.clock.tick(),
            source="reasoning", correlation_id=cid, payload=payload, priority=priority,
        )
        self._services.events.publish(event)
