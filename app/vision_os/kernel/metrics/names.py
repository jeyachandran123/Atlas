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

    # --- detection (Flow 2) ------------------------------------------------- #
    DETECTION_FPS: Final = "vision_os.detection.fps"
    DETECTION_INFERENCE_MS: Final = "vision_os.detection.inference_ms"
    DETECTION_TOTAL_MS: Final = "vision_os.detection.total_ms"
    DETECTION_QUEUE_MS: Final = "vision_os.detection.queue_ms"
    DETECTIONS_EMITTED: Final = "vision_os.detection.emitted"
    DETECTION_FRAMES_PROCESSED: Final = "vision_os.detection.frames_processed"
    DETECTION_FRAMES_DROPPED: Final = "vision_os.detection.frames_dropped"
    DETECTION_FAILURES: Final = "vision_os.detection.failures"
    DETECTION_TIMEOUTS: Final = "vision_os.detection.timeouts"
    DETECTION_QUEUE_DEPTH: Final = "vision_os.detection.queue_depth"
    DETECTION_BATCH_SIZE: Final = "vision_os.detection.batch_size"
    DETECTION_BATCH_EFFICIENCY: Final = "vision_os.detection.batch_efficiency"
    DETECTION_IN_FLIGHT: Final = "vision_os.detection.in_flight"
    DETECTORS_ACTIVE: Final = "vision_os.detection.detectors_active"
    DETECTOR_WARMUP_MS: Final = "vision_os.detection.warmup_ms"

    DETECTIONS_REJECTED: Final = "vision_os.detection.rejected"
    """Detections the platform refused, by ``reason``.

    Deliberately **not** a "false detection" counter. Whether a detection is
    false is a judgment requiring ground truth the platform does not have;
    claiming otherwise would violate the Semantic Ceiling (invariant V1). What
    the platform *can* count is what it rejected and why: below threshold, out of
    normalized range, unmapped label, contract violation.
    """

    # --- tracking (M6, Flow 3) ---------------------------------------------- #
    TRACKS_ACTIVE: Final = "vision_os.tracking.active"
    TRACKS_CREATED: Final = "vision_os.tracking.created"
    TRACKS_TERMINATED: Final = "vision_os.tracking.terminated"
    """Labelled by ``break_reason``. The label is what makes a regression
    attributable: a rise concentrated in ``detector_miss`` points at the
    detector, not the tracker."""

    TRACKS_RECOVERED: Final = "vision_os.tracking.recovered"
    TRACKS_COASTING: Final = "vision_os.tracking.coasting"
    TRACK_LIFETIME_FRAMES: Final = "vision_os.tracking.lifetime_frames"
    TRACK_LIFETIME_MS: Final = "vision_os.tracking.lifetime_ms"
    TRACK_HIT_RATIO: Final = "vision_os.tracking.hit_ratio"
    """Measured frames over total frames, per terminated track. The
    fragmentation signal: 14_TESTING section 7.2 names fragmentation as the
    primary cause of downstream object-count errors."""

    TRACKING_FPS: Final = "vision_os.tracking.fps"
    TRACKING_LATENCY_MS: Final = "vision_os.tracking.latency_ms"
    ASSOCIATION_MS: Final = "vision_os.tracking.association_ms"
    ASSOCIATION_FAILURES: Final = "vision_os.tracking.association_failures"
    """Associations *refused* for ambiguity, not associations that were wrong.
    The platform cannot know an association was wrong without ground truth; it
    can know it declined to assert one (invariant V1)."""

    TRACKING_FRAMES_PROCESSED: Final = "vision_os.tracking.frames_processed"
    TRACKING_FAILURES: Final = "vision_os.tracking.failures"
    TRACKING_OUT_OF_ORDER: Final = "vision_os.tracking.out_of_order_frames"
    """A pipeline bug, alarmed rather than absorbed (port obligation T1)."""

    TRACKER_EPOCH_RESETS: Final = "vision_os.tracking.epoch_resets"
    TRACKER_CAPACITY_REFUSALS: Final = "vision_os.tracking.capacity_refusals"
    TRACK_TABLE_SATURATION: Final = "vision_os.tracking.table_saturation"
    TRACKING_STATE_BYTES: Final = "vision_os.tracking.state_bytes"
    TRACKERS_ACTIVE: Final = "vision_os.tracking.trackers_active"
    TRACKER_FALLBACKS: Final = "vision_os.tracking.fallbacks"
    """Times the platform dropped to ``tracker.iou`` because the configured
    tracker failed. Degradation is visible, never silent (invariant V9)."""

    # --- object registry (M7, Flow 4) ---------------------------------------- #
    OBJECTS_ACTIVE: Final = "vision_os.registry.active"
    """Objects believed present — provisional, active or occluded."""

    OBJECTS_TOTAL: Final = "vision_os.registry.total"
    """Every object held, terminal ones included. The memory-shaped number."""

    OBJECTS_CREATED: Final = "vision_os.registry.created"
    OBJECTS_CONFIRMED: Final = "vision_os.registry.confirmed"
    OBJECTS_EXPIRED: Final = "vision_os.registry.expired"
    OBJECTS_MERGED: Final = "vision_os.registry.merged"
    OBJECTS_SPLIT: Final = "vision_os.registry.split"
    OBJECTS_SHED: Final = "vision_os.registry.shed"
    """Provisional objects evicted under population pressure. Confirmed objects
    are never shed: withdrawing an assertion to save memory would make the
    platform's claims a function of its load."""

    OBJECT_LIFETIME_MS: Final = "vision_os.registry.lifetime_ms"
    OBJECT_STALENESS_MS: Final = "vision_os.registry.staleness_ms"
    """Time since the last **measured** sighting, per object. The object-level
    expression of V8."""

    IDENTITY_ASSERTIONS: Final = "vision_os.registry.identity_assertions"
    IDENTITY_AMBIGUITIES: Final = "vision_os.registry.identity_ambiguities"
    """Re-entries where candidates were too close to separate, so a new object was
    minted and the alternatives published.

    Deliberately **not** an "identity error" counter: whether a binding was wrong
    needs ground truth the platform does not have. What it can count is where it
    declined to decide (invariant V1)."""

    IDENTITY_REBINDS: Final = "vision_os.registry.rebinds"
    EPOCH_REBINDS: Final = "vision_os.registry.epoch_rebinds"
    """Re-bindings across a tracker epoch, carrying reduced confidence."""

    REGION_TRANSITIONS: Final = "vision_os.registry.region_transitions"
    REGION_OCCUPANCY: Final = "vision_os.registry.region_occupancy"
    REGION_DWELL_MS: Final = "vision_os.registry.region_dwell_ms"

    ATTRIBUTES_APPLIED: Final = "vision_os.registry.attributes_applied"
    ATTRIBUTES_REJECTED: Final = "vision_os.registry.attributes_rejected"
    """Attributes refused by the neutrality gate, labelled by reason. The V1
    enforcement point inside M7 (02_VOM section 9.1)."""

    ATTRIBUTES_STALE: Final = "vision_os.registry.attributes_stale"

    REGISTRY_FRAMES_PROCESSED: Final = "vision_os.registry.frames_processed"
    REGISTRY_LATENCY_MS: Final = "vision_os.registry.latency_ms"
    REGISTRY_FAILURES: Final = "vision_os.registry.failures"
    REGISTRY_SATURATION: Final = "vision_os.registry.saturation"
    REGISTRY_CAPACITY_REFUSALS: Final = "vision_os.registry.capacity_refusals"
    REGISTRY_PARTITIONS: Final = "vision_os.registry.partitions"

    OBJECT_STORE_WRITES: Final = "vision_os.registry.store_writes"
    OBJECT_STORE_FAILURES: Final = "vision_os.registry.store_failures"
    OBJECT_STORE_LATENCY_MS: Final = "vision_os.registry.store_latency_ms"
    OBJECTS_RELOADED: Final = "vision_os.registry.reloaded"
    """Objects recovered from durable state after a restart. 07_STATE section
    9.3: object identity survives, tracks do not."""

    # --- crop manager (M8, Flow 5) ------------------------------------------- #
    CROPS_REQUESTED: Final = "vision_os.cropping.requested"
    """Candidates that fired a trigger. Labelled by ``reason``, so the mix of the
    nine trigger reasons is visible — a deployment where everything is
    ``periodic_refresh`` is paying a cadence tax rather than reacting to change."""

    CROPS_PRODUCED: Final = "vision_os.cropping.produced"
    CROPS_SKIPPED: Final = "vision_os.cropping.skipped"
    """Labelled by ``reason``. The V8 counter: a consumer must be able to tell
    'nothing was there' from 'we could not afford to look'."""

    CROPS_GATE_REJECTED: Final = "vision_os.cropping.gate_rejected"
    """Labelled by ``reason``. Turns *"the VLM never answers for far-away
    people"* into a statistic with a name (02_VOM section 10.7)."""

    CROPS_DEDUPLICATED: Final = "vision_os.cropping.deduplicated"
    CROP_EXTRACTION_MS: Final = "vision_os.cropping.extraction_ms"
    CROP_EXTRACTION_FAILURES: Final = "vision_os.cropping.extraction_failures"
    CROP_SCALE_PIXELS: Final = "vision_os.cropping.scale_pixels"
    """Distribution of graded object height. The camera-placement diagnostic:
    a site whose objects cluster below the gate floor has a mounting problem, not
    a model problem."""

    CROP_QUALITY_GRADE: Final = "vision_os.cropping.quality_grade"
    """Labelled by ``overall``. The four-level verdict's distribution."""

    CROP_TRIGGER_LATENCY_MS: Final = "vision_os.cropping.trigger_latency_ms"
    CROP_CANDIDATES_EVALUATED: Final = "vision_os.cropping.candidates_evaluated"
    CROP_FRAME_UNAVAILABLE: Final = "vision_os.cropping.frame_unavailable"
    """Frames evicted before their crop could be taken. Diagnoses pin TTL and
    buffer depth rather than leaving a hole nobody can explain."""

    UNDERSTANDING_BUDGET_SPENT: Final = "vision_os.cropping.budget_spent"
    UNDERSTANDING_BUDGET_SHED: Final = "vision_os.cropping.budget_shed"
    UNDERSTANDING_BUDGET_PRESSURE: Final = "vision_os.cropping.budget_pressure"
    """Spend over ceiling. Above 1.0 the platform is thinning attributes, which
    consumers learn from coverage rather than from silence (V8)."""

    DEMANDS_ACTIVE: Final = "vision_os.cropping.demands_active"
    DEMANDS_REGISTERED: Final = "vision_os.cropping.demands_registered"
    DEMANDS_REVOKED: Final = "vision_os.cropping.demands_revoked"
    DEMANDS_UNSATISFIABLE: Final = "vision_os.cropping.demands_unsatisfiable"
    """Demands the platform accepted and cannot serve — the honest answer to a
    request for an attribute no bound model produces."""

    DEMAND_THROTTLED: Final = "vision_os.cropping.demands_throttled"
    CROP_CACHE_HITS: Final = "vision_os.cropping.cache_hits"
    CROP_CACHE_EVICTIONS: Final = "vision_os.cropping.cache_evictions"

    # --- models (M18, Flow 2) ------------------------------------------------ #
    MODELS_LOADED: Final = "vision_os.models.loaded"
    MODEL_EVICTIONS: Final = "vision_os.models.evictions"
    MODEL_LOAD_MS: Final = "vision_os.models.load_ms"
    MODEL_WARMUP_MS: Final = "vision_os.models.warmup_ms"
    MODEL_LOAD_FAILURES: Final = "vision_os.models.load_failures"
    ARTIFACT_INTEGRITY_FAILURES: Final = "vision_os.models.artifact_integrity_failures"
    DEVICE_UTILIZATION: Final = "vision_os.models.device_utilization"
    DEVICE_RESERVATION_DENIED: Final = "vision_os.models.device_reservation_denied"
    DEVICE_FALLBACKS: Final = "vision_os.models.device_fallbacks"

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
    PIPELINE_CONSUMER_FAILURES: Final = "vision_os.runtime.consumer_failures"
    """A downstream consumer raised at the admitted-frame seam.

    Should always be zero: the consumer contract forbids raising. A non-zero
    value means a later flow is leaking failures into acquisition, which the
    runtime absorbs but must not hide."""


ALL_METRIC_NAMES: Final[tuple[str, ...]] = tuple(
    value
    for key, value in vars(MetricName).items()
    if not key.startswith("_") and isinstance(value, str)
)
