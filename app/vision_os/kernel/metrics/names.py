"""The core metric set (05_MODULES_PLATFORM_KERNEL M21).

Every module reports against a common shape. This is what allows one dashboard to
describe a platform whose internals will change completely over a decade.

Names are centralised so that a metric is renamed in one place rather than
drifting across call sites — a dashboard that silently stops matching is
indistinguishable from a platform that silently stopped working.

Confidence and class distributions are the **drift canaries**; they arrive with
Flow 2. Flow 1 defines the throughput, latency, saturation, error and coverage
families.
"""

from __future__ import annotations

from typing import Final


class MetricName:
    """Closed vocabulary of Flow 1 metric names."""

    # --- throughput ------------------------------------------------------- #
    FRAMES_RECEIVED: Final = "vision_os.frames.received"
    FRAMES_ADMITTED: Final = "vision_os.frames.admitted"
    FRAMES_DROPPED: Final = "vision_os.frames.dropped"
    PACKETS_RECEIVED: Final = "vision_os.packets.received"

    # --- latency (histograms, milliseconds) ------------------------------- #
    DECODE_DURATION_MS: Final = "vision_os.decode.duration_ms"
    MASK_DURATION_MS: Final = "vision_os.privacy.duration_ms"
    ADMISSION_DURATION_MS: Final = "vision_os.scheduler.decision_duration_ms"
    INGEST_LATENCY_MS: Final = "vision_os.frames.ingest_latency_ms"

    # --- saturation -------------------------------------------------------- #
    BUFFER_SLOTS_IN_USE: Final = "vision_os.buffer.slots_in_use"
    BUFFER_SLOTS_TOTAL: Final = "vision_os.buffer.slots_total"
    BUFFER_LEASES_ACTIVE: Final = "vision_os.buffer.leases_active"
    BUFFER_PINS_ACTIVE: Final = "vision_os.buffer.pins_active"
    SOURCE_IN_FLIGHT: Final = "vision_os.source.in_flight"
    BUDGET_PRESSURE: Final = "vision_os.scheduler.budget_pressure"

    # --- errors ------------------------------------------------------------ #
    DECODE_ERRORS: Final = "vision_os.decode.errors"
    CONNECT_FAILURES: Final = "vision_os.source.connect_failures"
    STREAM_STALLS: Final = "vision_os.source.stalls"
    RECONNECTS: Final = "vision_os.source.reconnects"
    MASK_FAILURES: Final = "vision_os.privacy.mask_failures"
    LEASE_LEAKS: Final = "vision_os.buffer.lease_leaks"
    FRAMES_EVICTED: Final = "vision_os.buffer.frames_evicted"
    POOL_EXHAUSTED: Final = "vision_os.buffer.pool_exhausted"

    # --- coverage (V8) ----------------------------------------------------- #
    EFFECTIVE_RATE: Final = "vision_os.coverage.effective_rate"
    OBSERVABLE: Final = "vision_os.coverage.observable"
    BLIND_TRANSITIONS: Final = "vision_os.coverage.blind_transitions"
    SILENT_FAILURE_SUSPECTED: Final = "vision_os.health.silent_failure_suspected"

    # --- kernel ------------------------------------------------------------ #
    EVENTS_PUBLISHED: Final = "vision_os.events.published"
    EVENTS_DROPPED: Final = "vision_os.events.dropped"
    CONFIG_RELOADS: Final = "vision_os.config.reloads"
    CONFIG_RELOAD_FAILURES: Final = "vision_os.config.reload_failures"
    PLUGINS_LOADED: Final = "vision_os.plugins.loaded"
    PLUGINS_REJECTED: Final = "vision_os.plugins.rejected"
    CONFORMANCE_FAILURES: Final = "vision_os.plugins.conformance_failures"
    PIPELINES_ATTACHED: Final = "vision_os.runtime.pipelines_attached"
    PIPELINE_RESTARTS: Final = "vision_os.runtime.pipeline_restarts"


ALL_METRIC_NAMES: Final[tuple[str, ...]] = tuple(
    value
    for key, value in vars(MetricName).items()
    if not key.startswith("_") and isinstance(value, str)
)
