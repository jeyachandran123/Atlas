"""Kernel health monitor — infrastructure for observing subsystem health.

Aggregates health probes registered by kernel subsystems and (future) engines.
It performs no cognition; it only collects reports and computes an overall
status (worst-of). Designed to feed future dashboards.
"""

from __future__ import annotations

import threading
from typing import Mapping

from .contracts import HealthMonitor, HealthProbe, HealthReport, HealthStatus

_SEVERITY = {
    HealthStatus.HEALTHY: 0,
    HealthStatus.UNKNOWN: 1,
    HealthStatus.DEGRADED: 2,
    HealthStatus.UNHEALTHY: 3,
}


class KernelHealthMonitor(HealthMonitor):
    def __init__(self) -> None:
        self._probes: dict[str, HealthProbe] = {}
        self._lock = threading.Lock()

    def register_probe(self, name: str, probe: HealthProbe) -> None:
        with self._lock:
            self._probes[name] = probe

    def report(self) -> Mapping[str, HealthReport]:
        with self._lock:
            probes = dict(self._probes)
        out: dict[str, HealthReport] = {}
        for name, probe in probes.items():
            try:
                out[name] = probe()
            except Exception as exc:  # a failing probe is itself unhealthy
                out[name] = HealthReport(
                    component=name, status=HealthStatus.UNHEALTHY, detail=f"probe error: {exc!r}"
                )
        return out

    def overall(self) -> HealthStatus:
        reports = self.report()
        if not reports:
            return HealthStatus.UNKNOWN
        worst = max(reports.values(), key=lambda r: _SEVERITY[r.status])
        return worst.status
