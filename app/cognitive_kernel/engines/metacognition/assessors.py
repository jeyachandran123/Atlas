"""Per-faculty assessors (Phase 7 Ch5-8) — pure, deterministic evaluations.

Each assessor reads only the :class:`ObservationWindow` and returns a confidence-
qualified :class:`Assessment` (MeL17/MeL18): a score, a grade, a health level, the
reliability of the judgment (grounded in how much evidence was observed), and the
findings. These functions *evaluate* faculties; they never perform their work
(MeL1/MeL4). Deterministic given the same window.
"""

from __future__ import annotations

from .contracts import Assessment, AssessmentKind, Grade, HealthLevel, MetaConfig, ObservationWindow


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _grade(score: float) -> Grade:
    if score >= 0.85:
        return Grade.EXCELLENT
    if score >= 0.70:
        return Grade.GOOD
    if score >= 0.50:
        return Grade.FAIR
    if score >= 0.30:
        return Grade.POOR
    return Grade.CRITICAL


def _level(score: float) -> HealthLevel:
    if score >= 0.70:
        return HealthLevel.HEALTHY
    if score >= 0.40:
        return HealthLevel.DEGRADED
    return HealthLevel.UNHEALTHY


def _confidence(evidence: int, cfg: MetaConfig) -> float:
    return round(min(1.0, evidence / cfg.min_evidence), 6) if cfg.min_evidence > 0 else 1.0


def _mk(kind, subject, score, conf, findings, metrics, rationale) -> Assessment:
    score = _clamp(score)
    return Assessment(kind, subject, round(score, 6), _grade(score), _level(score),
                      round(_clamp(conf), 6), tuple(findings), dict(metrics), rationale)


def assess_reasoning(w: ObservationWindow, cfg: MetaConfig) -> Assessment:
    concluded = w.count("reasoning.concluded")
    escalated = w.count("reasoning.escalated")
    contradictions = w.count("reasoning.contradiction")
    total = concluded + escalated
    mean_conf = w.mean("reasoning.confidence", 0.0)
    esc_rate = escalated / total if total else 0.0
    con_rate = contradictions / max(1, total)
    score = (0.5 * mean_conf + 0.3 * (1 - esc_rate) + 0.2 * (1 - con_rate)) if total else 0.5
    findings = []
    if total and esc_rate > cfg.escalation_rate_max:
        findings.append("excessive escalation")
    if con_rate > cfg.contradiction_rate_max:
        findings.append("contradiction storm")
    if mean_conf and mean_conf < cfg.low_confidence:
        findings.append("low reasoning confidence")
    return _mk(AssessmentKind.REASONING, "reasoning", score, _confidence(total, cfg), findings,
               {"concluded": concluded, "escalations": escalated, "contradictions": contradictions,
                "mean_confidence": mean_conf, "escalation_rate": round(esc_rate, 4)},
               "reasoning quality from conclusions, escalations, contradictions, and calibrated confidence")


def assess_prediction(w: ObservationWindow, cfg: MetaConfig) -> Assessment:
    forecasts = w.count("prediction.forecast")
    reconciled = len(w.samples.get("prediction.surprise", ()))
    mean_surprise = w.mean("prediction.surprise", 0.0)
    canonical_writes = w.metric("prediction.canonical_writes", 0.0)
    calibration = _clamp(1 - mean_surprise)
    score = calibration if reconciled else (0.7 if forecasts else 0.5)
    findings = []
    if reconciled and mean_surprise > cfg.miscalibration_max:
        findings.append("prediction miscalibration")
    if canonical_writes > 0:
        findings.append("prediction modified canonical state (PrL8)")
    return _mk(AssessmentKind.PREDICTION, "prediction", score, _confidence(forecasts + reconciled, cfg),
               findings, {"forecasts": forecasts, "reconciled": reconciled, "mean_surprise": mean_surprise,
                          "calibration": round(calibration, 4), "canonical_writes": canonical_writes},
               "prediction calibration from reconciled forecast surprise (MeL23/MeL24)")


def assess_attention(w: ObservationWindow, cfg: MetaConfig) -> Assessment:
    ignitions = w.count("attention.ignition")
    rests = w.count("attention.rest")
    inhibited = w.count("attention.inhibited")
    fatigue = w.metric("attention.fatigue", 0.0)
    total = ignitions + rests
    focus_share = ignitions / max(1, total)
    score = 0.6 * (1 - fatigue) + 0.4 * focus_share
    findings = []
    if fatigue > cfg.fatigue_max:
        findings.append("attention fatigue high")
    return _mk(AssessmentKind.ATTENTION, "attention", score, _confidence(total, cfg), findings,
               {"ignitions": ignitions, "rests": rests, "inhibited": inhibited, "fatigue": fatigue},
               "attention effectiveness from ignition/rest balance and fatigue")


def assess_working_memory(w: ObservationWindow, cfg: MetaConfig) -> Assessment:
    loads = w.count("working_memory.loaded")
    evictions = w.count("working_memory.evicted")
    focus_used = w.metric("working_memory.focus_used", 0.0)
    churn = evictions / max(1, loads)
    score = 0.7 * (1 - min(1.0, churn)) + 0.3
    findings = []
    if churn > 1.0:
        findings.append("working-memory thrash (evictions exceed loads)")
    return _mk(AssessmentKind.WORKING_MEMORY, "working_memory", score, _confidence(loads + evictions, cfg),
               findings, {"loads": loads, "evictions": evictions, "focus_used": focus_used,
                          "churn": round(churn, 4)},
               "working-memory utilization from load/eviction churn and focus occupancy")


def assess_executive(w: ObservationWindow, cfg: MetaConfig) -> Assessment:
    decisions = w.count("executive.decision")
    escalations = len(w.samples.get("executive.escalated", ()))
    approvals = len(w.samples.get("executive.approved", ()))
    conflicts = w.count("executive.conflict")
    committed = w.metric("executive.committed_budget", 0.0)
    esc_rate = escalations / max(1, decisions)
    score = 0.5 * (1 - esc_rate) + 0.3 * (approvals / max(1, decisions)) + 0.2 * (1.0 if committed <= 1.0 else 0.0)
    findings = []
    if decisions and esc_rate > cfg.escalation_rate_max:
        findings.append("excessive executive escalation")
    if committed > 1.0:
        findings.append("executive budget over-commit (ExL4)")
    return _mk(AssessmentKind.EXECUTIVE, "executive", score, _confidence(decisions, cfg), findings,
               {"decisions": decisions, "escalations": escalations, "approvals": approvals,
                "conflicts": conflicts, "committed_budget": committed},
               "executive governance quality from decision mix and budget discipline (audited, MeL2)")


def assess_runtime(w: ObservationWindow, cfg: MetaConfig) -> Assessment:
    failure_rate = w.metric("failure_rate", 0.0)
    throughput = w.metric("throughput", 0.0)
    completed = w.metric("completed", 0.0)
    score = 1 - failure_rate
    findings = []
    if failure_rate > cfg.failure_rate_max:
        findings.append("runtime failure rate elevated")
    return _mk(AssessmentKind.RUNTIME, "runtime", score, _confidence(int(completed), cfg), findings,
               {"failure_rate": failure_rate, "throughput": throughput, "completed": completed},
               "runtime execution health from failure rate and throughput")


def assess_health(w: ObservationWindow, cfg: MetaConfig) -> Assessment:
    statuses = list(w.health_status.values())
    n = max(1, len(statuses))
    unhealthy = sum(1 for s in statuses if s == "unhealthy")
    degraded = sum(1 for s in statuses if s == "degraded")
    score = 1 - (unhealthy * 1.0 + degraded * 0.5) / n
    findings = [f"{name} is {s}" for name, s in w.health_status.items() if s in ("unhealthy", "degraded")]
    return _mk(AssessmentKind.HEALTH, "cognitive_health", score, min(1.0, len(statuses) / 3), findings,
               {"components": n, "unhealthy": unhealthy, "degraded": degraded},
               "overall cognitive health from component health probes (MeL25)")


def assess_performance(w: ObservationWindow, cfg: MetaConfig) -> Assessment:
    failure_rate = w.metric("failure_rate", 0.0)
    volume = w.total_events
    score = _clamp(0.6 * (1 - failure_rate) + 0.4 * min(1.0, volume / (cfg.min_evidence * 4)))
    return _mk(AssessmentKind.PERFORMANCE, "cognitive_performance", score, _confidence(volume, cfg), [],
               {"events": volume, "failure_rate": failure_rate},
               "aggregate cognitive performance from activity volume and failure rate")
