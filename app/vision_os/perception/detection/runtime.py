"""The Detection Runtime — the seam consumer.

Single responsibility: *own the detection layer's lifecycle and resume the
admitted-frame path. Detect nothing yourself.*

This is the only Flow 2 module the Flow 1 Runtime ever holds, and it holds it as
an ``AdmittedFrameConsumer`` protocol — so Flow 1 never learns that detection
exists, let alone which detector is bound.

Detections are published to the **Event Bus**, not handed to a named successor.
Flow 3 subscribes; Flow 2 does not know it will. That is what keeps the layers
uncoupled as later flows arrive.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ...core.model.detection import Detection
from ...core.model.health import ComponentHealth, HealthState
from ...core.model.ids import FrameRef, ModuleId
from ...core.model.timebase import Duration
from ...core.ports.clock import Clock
from ...core.ports.scheduling import Fidelity
from ...kernel.events import EventBus
from ...kernel.health import HealthMonitor
from ...kernel.metrics import MetricName, MetricsEngine
from .engine import DetectionEngine, DetectionOutcome

DETECTION_RUNTIME_ID = ModuleId("detection_runtime")

#: How often the runtime re-reports engine health.
_DEFAULT_REPORT_INTERVAL = Duration.from_millis(1_000)

DetectionSink = Callable[[Sequence[Detection]], None]
"""An optional in-process tap on the detection stream.

The Event Bus is the contract; this exists for a co-located consumer that wants
the objects themselves rather than a reference, and is never required.
"""


@dataclass(slots=True)
class DetectionRuntimeStats:
    frames_consumed: int = 0
    frames_detected: int = 0
    frames_failed: int = 0
    detections_emitted: int = 0

    @property
    def failure_rate(self) -> float:
        return self.frames_failed / self.frames_consumed if self.frames_consumed else 0.0


class DetectionRuntime:
    """Implements ``AdmittedFrameConsumer``; owns detection lifecycle."""

    def __init__(
        self,
        *,
        clock: Clock,
        bus: EventBus,
        metrics: MetricsEngine,
        health: HealthMonitor,
        engine: DetectionEngine,
        sink: DetectionSink | None = None,
        report_interval: Duration = _DEFAULT_REPORT_INTERVAL,
    ) -> None:
        self._clock = clock
        self._bus = bus
        self._metrics = metrics
        self._health = health
        self._engine = engine
        self._sink = sink
        self._report_interval = report_interval
        self._stats = DetectionRuntimeStats()
        self._started = False
        self._last_report_ns = 0

    # --- lifecycle -------------------------------------------------------------- #

    async def start(self) -> None:
        """Warm the detector and report readiness.

        Warmup happens here rather than lazily on the first frame, so a cold
        first inference never masquerades as a performance regression.
        """
        started = self._clock.monotonic().ns
        await self._engine.warm()
        warmup_ms = (self._clock.monotonic().ns - started) / 1_000_000
        self._metrics.histogram(MetricName.DETECTOR_WARMUP_MS).record(warmup_ms)
        self._started = True
        self._report_health(HealthState.HEALTHY, "warm")

    async def stop(self) -> None:
        self._started = False
        self._report_health(HealthState.DRAINING, "stopped")

    # --- the seam ---------------------------------------------------------------- #

    async def on_admitted(self, frame_ref: FrameRef, fidelity: Fidelity) -> None:
        """Resume the pipeline after admission.

        **Never raises.** A detection failure may not terminate a source actor or
        the Vision Runtime, so everything is absorbed, counted, and published
        (invariant V9).
        """
        if not self._started:
            return
        self._stats.frames_consumed += 1
        try:
            outcome = await self._engine.detect(frame_ref, fidelity)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the seam is a firewall
            self._stats.frames_failed += 1
            self._metrics.counter(
                MetricName.DETECTION_FAILURES,
                camera_id=str(frame_ref.camera_id),
                reason="runtime_guard",
            ).increment()
            self._report_health(
                HealthState.DEGRADED, f"unhandled {type(exc).__name__}: {exc}"
            )
            return

        self._publish(outcome)

    def _publish(self, outcome: DetectionOutcome) -> None:
        if outcome.failed:
            self._stats.frames_failed += 1
        else:
            self._stats.frames_detected += 1
            self._stats.detections_emitted += outcome.count

        # The engine already published DetectionCompleted / DetectionFailed on the
        # bus. An in-process sink is an optional convenience for a co-located
        # consumer and never a substitute for the bus.
        if self._sink is not None and outcome.detections:
            try:
                self._sink(outcome.detections)
            except Exception:  # noqa: BLE001, S110 - a bad sink must not break detection
                pass

        self._maybe_report()

    # --- health ------------------------------------------------------------------- #

    def _maybe_report(self) -> None:
        now = self._clock.monotonic().ns
        if now - self._last_report_ns < self._report_interval.ns:
            return
        self._last_report_ns = now
        health = self._engine.health()
        self._report_health(health.state, health.detail)
        self._metrics.gauge(MetricName.DETECTION_IN_FLIGHT).set(
            float(self._stats.frames_consumed - self._stats.frames_detected
                  - self._stats.frames_failed)
        )

    def _report_health(self, state: HealthState, detail: str) -> None:
        self._health.report(
            ComponentHealth(
                component_id=DETECTION_RUNTIME_ID,
                state=state,
                reported_at=self._clock.now(),
                detail=detail,
                metrics={
                    "frames_consumed": float(self._stats.frames_consumed),
                    "failure_rate": self._stats.failure_rate,
                },
            )
        )

    @property
    def stats(self) -> DetectionRuntimeStats:
        return self._stats

    @property
    def started(self) -> bool:
        return self._started

    def health(self) -> ComponentHealth:
        return self._engine.health()
