"""Dedicated pattern detectors (Phase 7; MeL26 — one detector per pathology).

Failure, drift, bias, contradiction, fatigue, miscalibration, and inefficiency each
have a specific, inspectable detector that emits confidence-qualified
:class:`Finding`s citing grounded evidence (MeL14/MeL15). Pure functions over the
observation window and the reflection history; they detect — they never correct.
"""

from __future__ import annotations

import uuid
from statistics import mean
from typing import Sequence

from .contracts import Finding, FindingKind, HealthLevel, MetaConfig, ObservationWindow

_DRIFT_BASELINE = 5  # reflections used to form the drift baseline


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _finding(kind, subject, severity, detail, evidence, confidence=1.0) -> Finding:
    return Finding("find-" + uuid.uuid4().hex, kind, subject, _clamp(severity), _clamp(confidence),
                   detail, tuple(evidence))


def detect_failures(assessments, cfg: MetaConfig) -> list[Finding]:
    findings = []
    for a in assessments:
        if a.level is HealthLevel.UNHEALTHY:
            findings.append(_finding(FindingKind.FAILURE, a.subject, 1 - a.score,
                                     f"{a.subject} is unhealthy (score {a.score:.3f})",
                                     tuple(a.findings) or (f"score={a.score:.3f}",), a.confidence))
    return findings


def detect_drift(history: Sequence[dict], current: dict, cfg: MetaConfig) -> list[Finding]:
    findings = []
    if len(history) < 2:
        return findings
    for key in ("reasoning_confidence", "prediction_calibration", "escalation_rate", "failure_rate"):
        cur = current.get(key)
        prior = [h[key] for h in history[-_DRIFT_BASELINE:] if key in h and h[key] is not None]
        if cur is None or len(prior) < 2:
            continue
        base = mean(prior)
        if abs(cur - base) >= cfg.drift_delta:
            direction = "down" if cur < base else "up"
            findings.append(_finding(FindingKind.DRIFT, key, min(1.0, abs(cur - base)),
                                     f"{key} drift {direction}: {base:.3f} -> {cur:.3f}",
                                     (f"baseline={base:.3f}", f"current={cur:.3f}")))
    return findings


def detect_bias(w: ObservationWindow, cfg: MetaConfig) -> list[Finding]:
    findings = []
    p_conf = w.mean("prediction.confidence", 0.0)
    surprise = w.mean("prediction.surprise", 0.0)
    reconciled = len(w.samples.get("prediction.surprise", ()))
    if reconciled and p_conf > 0.7 and surprise > cfg.miscalibration_max:
        findings.append(_finding(FindingKind.BIAS, "prediction", surprise,
                                 "overconfidence bias: high confidence with high realized surprise",
                                 (f"confidence={p_conf:.3f}", f"surprise={surprise:.3f}")))
    return findings


def detect_contradiction_patterns(w: ObservationWindow, cfg: MetaConfig) -> list[Finding]:
    contradictions = w.count("reasoning.contradiction")
    episodes = w.count("reasoning.concluded") + w.count("reasoning.escalated")
    rate = contradictions / max(1, episodes)
    if contradictions > 0 and rate > cfg.contradiction_rate_max:
        return [_finding(FindingKind.CONTRADICTION, "reasoning", rate,
                         f"contradiction pattern: {contradictions} across {episodes} episodes",
                         (f"rate={rate:.3f}",))]
    return []


def detect_fatigue(w: ObservationWindow, cfg: MetaConfig) -> list[Finding]:
    findings = []
    for comp in ("attention", "reasoning"):
        f = w.metric(f"{comp}.fatigue", 0.0)
        if f > cfg.fatigue_max:
            findings.append(_finding(FindingKind.FATIGUE, comp, f,
                                     f"{comp} fatigue {f:.3f} exceeds {cfg.fatigue_max}", (f"fatigue={f:.3f}",)))
    return findings


def analyze_calibration(w: ObservationWindow, cfg: MetaConfig) -> list[Finding]:
    surprise = w.mean("prediction.surprise", 0.0)
    reconciled = len(w.samples.get("prediction.surprise", ()))
    if reconciled and surprise > cfg.miscalibration_max:
        return [_finding(FindingKind.MISCALIBRATION, "prediction", surprise,
                         f"confidence miscalibration: mean surprise {surprise:.3f} > {cfg.miscalibration_max}",
                         (f"reconciled={reconciled}", f"surprise={surprise:.3f}"))]
    return []


def analyze_resource_utilization(w: ObservationWindow, cfg: MetaConfig) -> list[Finding]:
    findings = []
    committed = w.metric("executive.committed_budget", 0.0)
    if committed > 1.0:
        findings.append(_finding(FindingKind.INEFFICIENCY, "executive", committed - 1.0,
                                 f"executive budget over-commit: {committed:.2f}", (f"committed={committed:.2f}",)))
    failure_rate = w.metric("failure_rate", 0.0)
    if failure_rate > cfg.failure_rate_max:
        findings.append(_finding(FindingKind.INEFFICIENCY, "runtime", failure_rate,
                                 f"runtime inefficiency: failure rate {failure_rate:.3f}",
                                 (f"failure_rate={failure_rate:.3f}",)))
    return findings
