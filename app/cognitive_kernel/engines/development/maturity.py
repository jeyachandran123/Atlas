"""The Capability Maturity Model (items 2/3/13/14) — per-capability certification (DeL9).

Assesses each capability's maturity from *long-term aggregate* evidence (DeL12).
Maturity is certified by verifiable outcomes, never self-declared (DeL2); a capability
cannot be certified high without enough evidence (DeL15). Assessments are pure and
deterministic; the "gain slow / lose fast" reconciliation (DeL6) is applied by the
engine against the prior certification version (DeL11).
"""

from __future__ import annotations

from .contracts import Capability, CapabilityAssessment, DevelopmentConfig, DevelopmentWindow, MaturityLevel


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _volume_factor(volume: float, min_horizon: int) -> float:
    return min(1.0, volume / max(1, min_horizon))


def _score(cap: Capability, w: DevelopmentWindow, cfg: DevelopmentConfig) -> tuple[float, int, dict[str, float]]:
    r = w.rate
    if cap is Capability.REASONING:
        vol = r("reasoning.volume")
        s = 0.6 * r("reasoning.success") + 0.4 * _volume_factor(vol, cfg.min_horizon)
        return s, int(vol), {"volume": vol, "success": r("reasoning.success")}
    if cap is Capability.PREDICTION:
        vol = r("prediction.volume")
        reconciled_ratio = r("prediction.reconciled") / max(1.0, vol)
        s = 0.5 * min(1.0, reconciled_ratio) + 0.5 * _volume_factor(vol, cfg.min_horizon)
        return s, int(vol), {"volume": vol, "reconciled": r("prediction.reconciled")}
    if cap is Capability.ATTENTION:
        vol = r("attention.volume")
        s = 0.5 * r("attention.ignition_rate") + 0.5 * _volume_factor(vol, cfg.min_horizon)
        return s, int(vol), {"volume": vol, "ignition_rate": r("attention.ignition_rate")}
    if cap is Capability.WORKING_MEMORY:
        loads = r("wm.loads")
        churn = r("wm.evictions") / max(1.0, loads)
        s = 0.6 * (1.0 - min(1.0, churn)) + 0.4 * _volume_factor(loads, cfg.min_horizon)
        return s, int(loads), {"loads": loads, "churn": round(churn, 4)}
    if cap is Capability.EXECUTIVE:
        vol = r("executive.decisions")
        esc = r("executive.escalations") / max(1.0, vol)
        s = 0.5 * (1.0 - min(1.0, esc)) + 0.5 * _volume_factor(vol, cfg.min_horizon)
        return s, int(vol), {"decisions": vol, "escalation_rate": round(esc, 4)}
    if cap is Capability.METACOGNITION:
        vol = r("meta.reflections")
        s = 0.6 * r("meta.compliance") + 0.4 * _volume_factor(vol, cfg.min_horizon)
        return s, int(vol), {"reflections": vol, "compliance": r("meta.compliance")}
    if cap is Capability.LEARNING:
        committed = r("learning.committed")
        cycles = r("learning.cycles")
        s = 0.5 * min(1.0, committed / max(1.0, cycles)) + 0.5 * _volume_factor(committed, cfg.min_horizon)
        return s, int(committed), {"committed": committed, "cycles": cycles}
    if cap is Capability.CALIBRATION:
        reconciled = r("prediction.reconciled")
        s = _volume_factor(reconciled, cfg.min_horizon)
        return s, int(reconciled), {"reconciled": reconciled}
    # SELF_IMPROVEMENT — an aggregate of learning + meta activity.
    agg = r("learning.committed") + r("meta.reflections")
    s = _volume_factor(agg, cfg.min_horizon * 2)
    return s, int(agg), {"learning": r("learning.committed"), "meta": r("meta.reflections")}


def _level(score: float, evidence: int, cfg: DevelopmentConfig) -> MaturityLevel:
    t = cfg.maturity_thresholds
    if evidence < cfg.min_evidence:
        # Cannot certify above DEVELOPING without enough evidence (DeL2/DeL15).
        return MaturityLevel.DEVELOPING if score >= t["developing"] else MaturityLevel.NASCENT
    if score >= t["optimizing"]:
        return MaturityLevel.OPTIMIZING
    if score >= t["mature"]:
        return MaturityLevel.MATURE
    if score >= t["proficient"]:
        return MaturityLevel.PROFICIENT
    if score >= t["developing"]:
        return MaturityLevel.DEVELOPING
    return MaturityLevel.NASCENT


class CapabilityMaturityModel:
    def __init__(self, config: DevelopmentConfig) -> None:
        self._config = config

    def assess(self, cap: Capability, window: DevelopmentWindow, *, version: int) -> CapabilityAssessment:
        score, evidence, metrics = _score(cap, window, self._config)
        score = _clamp(score)
        level = _level(score, evidence, self._config)
        confidence = round(min(1.0, evidence / self._config.min_evidence), 6)
        return CapabilityAssessment(
            capability=cap, maturity=level, score=round(score, 6), confidence=confidence,
            evidence_count=evidence, version=version, metrics=metrics,
            rationale=f"{cap.value} certified {level.name} from long-term aggregate evidence (DeL2/DeL12)",
        )

    def assess_all(self, window: DevelopmentWindow, versions: dict[str, int]) -> list[CapabilityAssessment]:
        return [self.assess(cap, window, version=versions.get(cap.value, 0) + 1) for cap in Capability]
