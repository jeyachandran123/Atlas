"""Driver collection — read-only extraction of causal factors (PrL8/PrL11).

Reads canonical State objects (via the State Manager) and conscious references
(via the Working-Memory read port) **read-only**, parsing their payloads into the
causal drivers and cascade links a simulation runs over. Nothing is written; the
collector copies nothing durable — each :class:`Driver` keeps its source handle
(reference, not a copy — OL7). An empty driver set means an *ungrounded* forecast,
flagged low-confidence downstream (PrL11).
"""

from __future__ import annotations

from typing import Any, Sequence

from ...state import CognitiveStateManager
from .contracts import Driver


class CollectedContext:
    __slots__ = ("drivers", "cascade", "baseline", "references")

    def __init__(self, drivers, cascade, baseline, references) -> None:
        self.drivers: list[Driver] = drivers
        self.cascade: list[tuple[str, str, float]] = cascade  # (cause, effect, strength)
        self.baseline: float = baseline
        self.references: list[str] = references


def _f(payload: Any, key: str, default: float) -> float:
    try:
        return float(payload.get(key, default))
    except (TypeError, ValueError):
        return default


class DriverCollector:
    def __init__(self, state: CognitiveStateManager) -> None:
        self._state = state  # read-only usage only

    def collect(self, handles: Sequence[str], *, target: str, baseline: float) -> CollectedContext:
        drivers: list[Driver] = []
        cascade: list[tuple[str, str, float]] = []
        references: list[str] = []
        base = baseline
        seen: set[str] = set()
        for h in sorted({*handles}):
            if not self._state.exists(h):
                continue
            obj = self._state.get(h)  # READ-ONLY — never mutated
            references.append(h)
            payload = obj.payload
            if "baseline" in payload:
                base = _f(payload, "baseline", base)
            causal = payload.get("causes")
            if isinstance(causal, dict) and "cause" in causal and "effect" in causal:
                cause, effect = str(causal["cause"]), str(causal["effect"])
                strength = _f(causal, "strength", 1.0)
                cascade.append((cause, effect, strength))
                if effect == target and (cause, effect) not in seen:
                    seen.add((cause, effect))
                    drivers.append(Driver(
                        name=cause, probability=strength,
                        impact=_f(causal, "impact", strength), source=h,
                        note=f"causes {effect}",
                    ))
            drv = payload.get("driver")
            if isinstance(drv, dict) and "name" in drv:
                key = (str(drv["name"]), "__explicit__")
                if key not in seen:
                    seen.add(key)
                    drivers.append(Driver(
                        name=str(drv["name"]), probability=_f(drv, "probability", 0.5),
                        impact=_f(drv, "impact", 1.0), source=h, note=str(drv.get("note", "")),
                    ))
        drivers.sort(key=lambda d: (-abs(d.impact), d.name))
        cascade.sort(key=lambda c: (c[0], c[1]))
        return CollectedContext(drivers, cascade, base, references)
