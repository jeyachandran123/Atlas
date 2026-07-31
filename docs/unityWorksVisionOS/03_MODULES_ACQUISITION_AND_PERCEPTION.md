# UnityWorks Vision OS (UWV)

## Phase 1 — Module Specifications I: Acquisition & Perception

| | |
|---|---|
| **Status** | Architecture Blueprint — Phase 1 (Design Only) |
| **Prerequisite** | `00`–`02` |
| **Covers** | Camera Manager · Video Source Manager · Frame Scheduler · Frame Buffer · Detection Engine · Tracking Engine · Object Registry · Crop Manager |

> **Notation.** API signatures are *contract notation*, not code — language-neutral shape and meaning.
> `→` denotes return, `⇢` denotes an asynchronous stream, `!` denotes a possible failure result.

**Every module below is specified against the same eleven-point template:** Purpose · Responsibilities ·
Public API · Inputs · Outputs · Dependencies · State Ownership · Thread Safety · Failure Handling ·
Performance · Extension Points.

---

## Table of Contents

- [M1 · Camera Manager](#m1--camera-manager)
- [M2 · Video Source Manager](#m2--video-source-manager)
- [M3 · Frame Scheduler](#m3--frame-scheduler)
- [M4 · Frame Buffer](#m4--frame-buffer)
- [M5 · Detection Engine](#m5--detection-engine)
- [M6 · Tracking Engine](#m6--tracking-engine)
- [M7 · Object Registry](#m7--object-registry)
- [M8 · Crop Manager](#m8--crop-manager)

---

# M1 · Camera Manager

### Purpose

Own the **identity, calibration, and operating profile** of every viewpoint — the durable answer to
"what is camera 7, where is it pointing, and how should it be processed." It is the platform's registry
of viewpoints, not its connection layer.

> **Single responsibility:** *Know what each camera is; never touch its bytes.*

### Responsibilities

1. Maintain the authoritative `Camera` record for every provisioned viewpoint (`02_VOM` §10.1).
2. Own **calibration**: intrinsics, extrinsics, homography, versioned as `CalibrationId`.
3. Resolve the **pipeline profile** for each camera (cadence, model selection, budget class).
4. Own **region definitions** per camera and their versioning.
5. Detect and flag **viewpoint change** — a camera that has been physically moved or refocused, whose
   calibration and history no longer describe the same view.
6. Publish camera lifecycle transitions as events.

**Explicitly not responsible for:** connecting, decoding, streaming, or any pixel access.

### Public API

```text
get(camera_id)                          → Camera !NotFound
list(scope: {tenant, site, status?})    → Camera[]
resolve_profile(camera_id)              → PipelineProfile
get_calibration(camera_id, at?: Time)   → Calibration !Uncalibrated
regions_of(camera_id)                   → Region[]
project_to_ground(camera_id, point, calibration_id) → (Point, Ellipse) !Uncalibrated
provision(spec)                         → Camera !ValidationError
recalibrate(camera_id, calibration)     → CalibrationId          # mints a new version
retire(camera_id, reason)               → void
report_viewpoint_drift(camera_id, evidence) → void
subscribe_changes()                     ⇢ CameraChanged
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| Configuration (camera declarations, profiles, regions) | `Camera` records |
| Calibration submissions (from a calibration tool, out of scope for Phase 1) | `Calibration` versions |
| Viewpoint drift evidence (from Health Monitor's scene-stability check) | `PipelineProfile` resolutions |
| Profile definitions | `CameraChanged`, `ViewpointDriftSuspected` events |

### Dependencies

Configuration Manager (declarations), Storage Interfaces (calibration persistence), Event Bus
(publication), Metrics Engine. **No dependency on any other L1–L7 module** — it is a leaf that others
read from.

### State Ownership

**Owns:** the camera registry, calibration version chain, region definitions, profile bindings.
**Does not own:** connection state (M2), stream health (Health Monitor), observations.

State is small (hundreds to low thousands of records), read-mostly, and durably persisted. It is the
platform's most stable state and is snapshot-versioned so that a historical observation can be
interpreted under the calibration in force when it was made (`02_VOM` §6.2 rule 4).

### Thread Safety

**Read-mostly with copy-on-write snapshots.** Readers take an immutable snapshot pointer; writers build
a new version and swap atomically. No reader ever blocks, and no reader ever sees a torn record — which
matters because this module is read on the hot path (every frame resolves a profile) while being
written rarely (a recalibration per month).

### Failure Handling

| Failure | Response |
|---|---|
| Camera declared but unreachable | Not this module's concern; record stays `provisioned`, M2 reports connection state |
| Calibration missing | `project_to_ground` returns `Uncalibrated`; pipeline continues in normalized space only, and observations simply omit ground fields (V9) |
| Calibration invalid (degenerate homography) | Rejected at submission; the previous version stays in force |
| Viewpoint drift suspected | Publishes an event, marks calibration `suspect`; ground projections continue but carry inflated uncertainty. **Does not** auto-invalidate — a false positive must not blind a site |
| Config declares an unknown profile | Provisioning fails fast at startup, not at first frame |

### Performance

`resolve_profile` and `get_calibration` are on the hot path and must be O(1) snapshot reads with no
allocation. Projection maths is a small matrix operation, cached per calibration version. Total memory
is negligible. The design constraint is not throughput but **snapshot cheapness** — at 100 cameras ×
30 fps, this module is consulted ~3000×/s and must never appear in a profile.

### Extension Points

- **Calibration methods** behind a port: manual homography, checkerboard, auto-calibration from
  observed pedestrian heights, SLAM-derived (drone).
- **Profile resolution strategy**: static config today; policy-driven (time-of-day, load-adaptive)
  later, without changing consumers.
- **Moving viewpoints** (drone, mobile, PTZ): calibration becomes time-varying. The API already takes
  `at?: Time` on `get_calibration` precisely so this arrives as an implementation change behind an
  unchanged contract.

---

# M2 · Video Source Manager

### Purpose

Turn a source specification into a **reliable, correctly-identified, correctly-timestamped, privacy-
masked stream of decoded frames** — and keep it that way across the network failures that define real
deployments.

> **Single responsibility:** *Produce trustworthy frames; interpret nothing.*

### Responsibilities

1. Manage connection lifecycle per source: connect, stream, detect stall, reconnect with backoff.
2. Decode via a decoder port (hardware or software), producing `Frame` objects.
3. **Assign `FrameRef`** — allocating a new `StreamEpoch` on every reconnect or reconfiguration
   (`02_VOM` §4.1). This is the module's most important correctness duty.
4. **Normalize time** — derive `t_capture` and `t_capture_unc` from source PTS, RTCP sender reports,
   and arrival time; classify `ClockQuality`.
5. **Apply privacy masking immediately post-decode**, before any other component can observe pixels;
   fail closed if masking fails.
6. Emit stream quality telemetry: packet loss, jitter, decode errors, bitrate.
7. Support `realtime`, `archival`, and `discrete` source semantics with the behavioural differences in
   `01_LAYERED` §5.3.

**Explicitly not responsible for:** deciding which frames get processed (M3), retaining frames (M4), or
anything about content.

### Public API

```text
open(camera_id)                      → SourceHandle !ConnectFailed
frames(handle)                       ⇢ Frame              # backpressure-aware stream
close(handle)                        → void
status(camera_id)                    → SourceStatus
seek(handle, position)               → void !NotSeekable   # archival only
stream_stats(camera_id)              → StreamStats
subscribe_events()                   ⇢ StreamConnected | StreamLost | EpochAdvanced
                                     | DecodeError | MaskFailure | ClockQualityChanged
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| `Camera` record + `SourceSpec` (M1) | `Frame` stream (data plane) |
| Credentials (resolved from secret store at connect time) | `FrameRef` assignment |
| Privacy policy (config) | Stream lifecycle events |
| Decoder capabilities (Plugin Manager) | Stream quality metrics |

### Dependencies

Camera Manager (M1), Frame Buffer (M4, for allocation), Source Adapter port, Decoder port, Secret
store, Configuration Manager, Event Bus, Metrics Engine, Clock (injected).

### State Ownership

**Owns:** per-source connection state, current `StreamEpoch`, `FrameSeq` counter, clock-offset
estimator state, reconnect backoff state, decoder session.

Connection state is **ephemeral and node-local** — it is not durable, because a restarted process
reconnects and advances the epoch anyway. The only thing that must survive restart is the *last used
epoch*, persisted cheaply so epochs remain monotonic across restarts. This is a small detail with
outsized consequences: without it, a restart can reuse an epoch and reintroduce the exact `FrameRef`
collision the epoch exists to prevent.

### Thread Safety

**One connection actor per source.** Each source is a single-threaded logical actor owning its socket,
decoder session, and counters — so no locks are needed on the hot path. Decode may be offloaded to a
hardware decoder or a decode thread pool, but *frame emission and sequence assignment remain in the
actor*, preserving strict ordering. The public API is safe to call from any thread; calls are marshalled
to the actor.

### Failure Handling

| Failure | Classification | Response |
|---|---|---|
| Connection refused / timeout | Transient | Exponential backoff with jitter, capped; camera status → `connecting`; `StreamLost` event; **coverage observation emitted** (V8) |
| Stream stalls (no frames, socket open) | Transient | Watchdog on inter-frame interval; force reconnect after threshold — the most common real-world RTSP failure and the one naive implementations miss entirely |
| Decode error on a frame | Transient | Drop frame, count, continue; mark next keyframe `recovered_from_error` |
| Sustained decode errors | Persistent | Try fallback decoder (hardware → software), then mark camera `degraded` |
| Credentials rejected | Persistent | Stop retrying after bounded attempts; alert; do not hammer the camera (which can lock accounts) |
| Codec unsupported | Persistent | Fail provisioning loudly at startup, not silently at runtime |
| **Privacy mask fails** | **Fatal for the frame** | **Drop the frame. Never emit unmasked pixels.** Camera → `degraded`; if sustained → `blind`. This is the one failure that fails closed rather than degrading |
| Clock quality degrades | Informational | Update `ClockQuality`, emit event; downstream fusion adapts (`02_VOM` §5.2) |
| Source is archival and reaches EOF | Normal | Close, emit completion, no reconnect |

**The invariant across all of these:** a failing camera *never* affects another camera. Actor isolation
makes this structural rather than aspirational.

### Performance

- **Zero-copy from decoder to buffer.** Decoded frames are written into buffer-pool memory; ideally the
  hardware decoder writes directly into a GPU-resident pool, so the frame never touches host memory.
- **Hardware decode by default** where available (NVDEC/QSV/VAAPI). At 100 cameras, software decode
  alone will saturate CPU before any inference runs — decode is the first bottleneck reached and the
  most commonly underestimated.
- **Backpressure honoured at the source.** If downstream is saturated, the source *stops decoding*
  rather than decoding into a full buffer. For `realtime` sources it drops to keyframes; for `archival`
  it blocks.
- **Budget:** decode should consume <25% of a node's compute, leaving headroom for inference.

### Extension Points

- **Source adapters** (port): RTSP, RTMP, WebRTC, file, image directory, USB/CSI, ONVIF, VMS
  integration, cloud object storage, **future drone telemetry-bearing streams**, **future mobile
  uplinks**. Each is an adapter; the module is unchanged.
- **Decoder adapters** (port): NVDEC, QSV, VAAPI, software.
- **Clock synchronization strategies** (port): PTP, NTP+RTCP, arrival-time estimation.
- **Privacy masking strategies** (port): static polygon mask, detection-driven face/plate blur,
  full-frame encryption for regulated sites.

> **Drone and mobile readiness.** These arrive as source adapters plus one extension already
> anticipated in M1: time-varying calibration. Telemetry (GPS, IMU, gimbal angles) enters as frame
> metadata and feeds calibration; no platform module changes. This is what "future sources without
> redesign" concretely means.

---

# M3 · Frame Scheduler

### Purpose

Decide, for every frame that arrives, **whether it is processed, at what fidelity, and with which
pipeline profile** — under a finite compute budget shared by every camera on the node.

> **Single responsibility:** *Allocate scarce perception capacity; process nothing yourself.*

This module is the platform's economic regulator and the primary implementation of invariant V7. At one
camera it is nearly trivial. At 100 cameras it is the difference between a system that works and one
that collapses under its own input rate.

### Responsibilities

1. Apply per-camera **cadence** (target processing fps, independent of source fps).
2. Enforce **global compute budget** across all cameras on the node, and per-tenant fair share.
3. Apply **admission policy** under saturation: which camera loses frames first, and why.
4. Select **fidelity**: inference resolution and model tier for this frame.
5. Support **adaptive cadence**: raise the rate on cameras with activity, lower on static scenes —
   *purely on visual-change signals, never on business importance* (V1).
6. **Count and attribute every drop** with a reason (V8). No silent discards.
7. In deterministic mode, schedule from the virtual clock so replay is exact (V13).

### Public API

```text
offer(frame_ref, frame_meta)      → Admitted(profile, fidelity) | Dropped(reason)
register_camera(camera_id, profile)   → void
set_budget(budget)                → void
current_pressure()                → PressureReport
override_cadence(camera_id, fps, ttl) → void      # operational, time-boxed
subscribe()                       ⇢ BudgetExceeded | CadenceAdapted | SustainedDropAlarm
```

```text
DropReason:
  CADENCE            # by design — this frame was not due
  BUDGET_EXHAUSTED   # node-level saturation
  TENANT_QUOTA       # fair-share limit reached
  QUEUE_FULL         # downstream backpressure
  DUPLICATE          # identical to previous (static scene suppression)
  QUALITY_REJECT     # decode-damaged beyond use
  DEADLINE_EXPIRED   # too old to be useful by the time capacity appeared
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| Frame references + metadata (M2) | Admission decisions with profile and fidelity |
| Pipeline profiles (M1) | Drop records with attributed reasons |
| Downstream queue depths (backpressure signals) | Pressure telemetry |
| Device utilization (Model Manager / Metrics) | `coverage` observations when drops are sustained |
| Budget configuration | |

### Dependencies

Camera Manager (M1), Configuration Manager, Metrics Engine, Event Bus, Clock (injected — **must** be,
for V13), device utilization signals from Model Manager.

### State Ownership

**Owns:** per-camera cadence state and phase, budget accounting, pressure history, adaptive cadence
state, drop counters. All ephemeral and node-local; rebuilt on restart from configuration.

### Thread Safety

`offer` is called from every source actor concurrently and must be **lock-free on the common path**.
Design: per-camera state is single-writer (owned by that camera's actor context); shared budget
accounting uses atomic counters with a periodic reconciliation tick rather than a lock. Precision of
budget accounting is deliberately traded for contention-freedom — being 2% off on a budget is
irrelevant; being a lock contention point at 3000 calls/second is fatal.

### Failure Handling

| Failure | Response |
|---|---|
| Sustained saturation | Progressive cadence reduction across cameras by fair-share policy; `SustainedDropAlarm`; **emit `coverage` observations so consumers know perception is thinned** (V8) |
| One camera floods (misconfigured 60 fps) | Per-camera quota caps its share; other cameras unaffected |
| Downstream stall | Queue-full backpressure propagates to admission; no unbounded queue growth |
| Budget misconfigured (impossibly low) | Warn loudly at startup with a computed feasible value; run anyway rather than refusing to start — a site with degraded perception beats a site with none (V9) |
| Clock jumps (NTP step) | Cadence is phase-based on monotonic time, immune to wall-clock steps |

### Performance

The decision must be **sub-microsecond** — it runs on every decoded frame from every camera, ~3000/s at
100 cameras, and any allocation or lock here is amplified 3000×. Implementation shape: integer phase
accumulators per camera, atomic budget counters, no allocation, no logging on the common path (drops
are counted, not logged individually; logging 3000 drops/second is itself a failure mode).

### Extension Points

- **Admission policies** (port): fixed cadence, weighted fair share, priority classes, deadline-aware,
  **activity-adaptive**.
- **Fidelity policies** (port): fixed resolution, resolution ladder under pressure, model-tier
  switching (small model under load, large model when idle).
- **Change-based suppression** (port): frame differencing, motion vectors extracted from the codec
  (nearly free — the encoder already computed them), background subtraction. This is the highest-value
  extension in the module: in most real deployments the majority of frames contain nothing new, and
  suppressing them at the scheduler is the cheapest possible saving.

> **A note on what must never enter here.** "Process the kitchen camera more often because it matters
> more" is a business priority and a V1/V2 violation. The platform exposes **priority classes** as
> opaque configuration; the *reason* a camera is class A lives with the consumer. The scheduler
> allocates; it never values.

---

# M4 · Frame Buffer

### Purpose

Hold decoded pixels in bounded, pooled memory and **lend** them to stages under lease, so that multiple
consumers can read the same frame without copying and memory can never grow without bound.

> **Single responsibility:** *Own pixel memory and its lifetime; know nothing about pixels.*

### Responsibilities

1. Pooled allocation of frame-sized buffers (host and device), with no steady-state allocation.
2. Lease issuance, tracking, and reclamation (`01_LAYERED` §4.3).
3. Pinning for late consumers (the Crop Manager needs a frame after detection has moved on).
4. Enforce capacity: bounded, with declared overflow policy per source semantics.
5. Detect and break leaked leases (a holder that exceeds its deadline).
6. Optional short **history window** for retrospective cropping.

### Public API

```text
allocate(camera_id, size, location: host|device) → FrameSlot !PoolExhausted
publish(slot, frame_ref, metadata)      → void          # slot becomes readable
acquire(frame_ref, holder_id, deadline) → FrameLease !NotAvailable
lease.pixels()                          → ReadOnlyView    # no copy
lease.release()                         → void
pin(frame_ref, ttl, reason)             → PinHandle !NotAvailable
unpin(pin_handle)                       → void
stats()                                 → BufferStats
subscribe()                             ⇢ PoolPressure | LeaseLeaked | FrameEvicted
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| Decoded frames from M2 | Frame slots (write side) |
| Acquire/pin requests from M5, M8 | Read-only leases |
| Capacity configuration | Pressure and eviction telemetry |

### Dependencies

Configuration Manager, Metrics Engine, Event Bus, a memory-pool allocator (host and device). **No
vision dependencies whatsoever** — this module could serve an audio platform unchanged.

### State Ownership

**Owns:** the pools, slot occupancy, the frame index (`FrameRef` → slot), lease and pin tables, eviction
order. Entirely ephemeral, node-local, and never durable.

### Thread Safety

**The most concurrency-sensitive module in the platform.** It is written by every source actor and read
by every inference stage.

Design:
- **Per-camera slot rings** — each camera writes only to its own ring, eliminating write contention.
- **Atomic reference counts** for leases; release is a decrement, and reclamation happens when the
  count reaches zero with no active pin.
- **Sharded lease table** by camera to avoid a single hot map.
- **Immutable published frames** — once published, pixels are never mutated, so readers need no lock at
  all. This is what makes multi-consumer reads free, and it is why the lease is defined as read-only in
  `01_LAYERED` §4.3 rather than as a convenience.

### Failure Handling

| Failure | Response |
|---|---|
| Pool exhausted, `realtime` source | Evict oldest unpinned frame; count; emit `PoolPressure`. Latency is protected over completeness |
| Pool exhausted, `archival` source | Block the producer. Completeness is protected over latency |
| Acquire on evicted frame | Return `NotAvailable`; the caller degrades (Crop Manager skips understanding for that object and counts it) — never an error that propagates upward |
| Lease held past deadline | Force-break, emit `LeaseLeaked` with the holder id, mark holder unhealthy. **One stuck stage must not exhaust the pool for every camera** (V9) |
| Pin TTL expires | Auto-unpin; count |
| Device memory exhausted | Fall back to host pool with a recorded penalty; if sustained, reduce buffer depth and inform the Scheduler to lower cadence |

### Performance

- **No steady-state allocation.** Pools are sized at startup from `cameras × pipeline_depth × jitter
  factor`; the steady state performs zero allocations, which is what makes 30-day soak stability
  achievable.
- **Sizing is by pipeline depth, not camera count**, which is why memory does not scale linearly with
  cameras (`01_LAYERED` §4.3).
- **NUMA and device affinity**: buffers are allocated on the node/device where they will be consumed.
- **History window is small by default** (~1–2 s). It exists so the Crop Manager can crop a frame the
  detector has already released — not to be a recorder. A large history window silently converts this
  module into a VMS, which is an explicit anti-goal.

### Extension Points

- **Allocator strategies** (port): host pinned, CUDA unified, device-resident, shared memory for
  cross-process pipelines, RDMA-registered for future distributed data planes.
- **Eviction policies** (port): FIFO, pin-aware LRU, importance-weighted.
- **Compressed retention** for a longer history window at lower fidelity, when a deployment genuinely
  needs retrospective cropping over minutes rather than seconds.

---

# M5 · Detection Engine

### Purpose

Answer **"what is present in this frame, and where"** — converting pixels into `Detection` objects in
platform taxonomy and normalized coordinates, at high throughput, behind an interface that makes the
underlying model irrelevant.

> **Single responsibility:** *Find things in a frame. Nothing else — no memory, no identity, no
> meaning.*

### Responsibilities

1. Invoke a detector adapter for admitted frames.
2. **Batch across cameras** to achieve GPU efficiency (`01_LAYERED` §6.2).
3. Translate model-native labels into platform taxonomy via validated mappings (`02_VOM` §8).
4. Normalize coordinates, undoing letterboxing/scaling exactly (`02_VOM` §6.2 rule 2).
5. Apply confidence calibration where a profile exists (`02_VOM` §7).
6. Compute per-detection quality contributions (scale, truncation).
7. Emit detection telemetry: counts by class, latency, batch efficiency.

**Explicitly not responsible for:** temporal reasoning, identity, or attributes. The detector is
memoryless by construction — a property that keeps it trivially testable and freely replaceable.

### Public API

```text
detect(frame_ref, profile)         → Detection[] !DetectionFailed
detect_batch(frame_refs, profile)  → Map<FrameRef, Detection[]>
capabilities()                     → DetectorCapabilities   # classes, geometry kinds, input constraints
warm()                             → void
health()                           → ComponentHealth
```

```text
DetectorCapabilities:
  producible_classes : ClassId[]        # published so V8 capability gaps are detectable
  geometry_kinds     : [box | oriented_box | mask | keypoints]
  input_constraints  : resolution range, colour space, batch limits
  calibration_profile: CalibrationId?
  deterministic      : bool
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| Admitted frame references + fidelity (M3) | `Detection[]` per frame |
| Frame pixels via lease (M4) | Capability declarations |
| Model handle (Model Manager) | Latency, batch, and class-count metrics |
| Taxonomy mapping (validated at load) | `DetectionFailed` events |

### Dependencies

Frame Buffer (M4), Model Manager (handles, devices), Detector port (adapter), Taxonomy registry,
Metrics, Event Bus, Configuration.

### State Ownership

**Owns:** batch accumulation state, in-flight request tracking, per-adapter warmup state. **Owns no
temporal state at all** — this is deliberate and is what makes the module replaceable without migration
and testable with a single image.

### Thread Safety

**Batching coordinator + device workers.** A lock-free-ish batch accumulator gathers requests from many
camera pipelines under a **dual trigger** (batch full *or* max-wait elapsed), then hands the batch to a
device worker. One worker per device; the adapter itself need not be thread-safe, which greatly widens
the set of usable third-party models. Results scatter back to callers via per-request completion
handles.

The max-wait timer is essential: without it, a lightly-loaded 3-camera deployment waits forever for a
batch of 16 that will never form.

### Failure Handling

| Failure | Classification | Response |
|---|---|---|
| Inference timeout | Transient | Fail the batch, retry once with smaller batch, then drop with `coverage` observation |
| Device OOM | Transient→Systemic | Halve batch size, retry; on repeat, request Model Manager reduce residency; inform Scheduler to cut cadence |
| Adapter crash (in-process) | Systemic | Circuit-break the adapter, fall back to secondary model if configured, else mark stage `failed` and camera `blind` (V8/V9) |
| Adapter crash (subprocess) | Persistent | Restart subprocess with backoff; pipeline continues degraded |
| Model produces unmapped label | Data | Apply `unmapped_policy` (drop or `unknown`); count. **Never** leak a native label |
| Coordinates out of range | Data | Clamp, count, flag quality. A systematic occurrence indicates an adapter letterboxing bug and is alarmed — this is exactly the silent-misalignment class that normalization exists to catch |
| Poison frame (repeatedly crashes the model) | Poison | Quarantine that `FrameRef`, never retry it, continue the stream |

### Performance

Detection is typically the **largest fixed cost** in the platform.

| Lever | Effect |
|---|---|
| **Cross-camera batching** | The single biggest win. Batch 16 versus batch 1 is commonly 5–10× throughput on the same GPU |
| **Precision** (FP16/INT8) | 2–4× throughput; requires per-model calibration validation before adoption |
| **Resolution ladder** | Quadratic cost in input size; the fidelity policy from M3 lands here |
| **Region-of-interest inference** | Skip inference on statically empty image areas |
| **Model tiering** | Small model always; large model on demand or under low load |
| **Keyframe-only detection** | Detect on keyframes, propagate by tracking between them |

**Budget:** at 100 cameras × 5 fps = 500 inferences/s. A 640×640 detector at ~3 ms batched amortized
requires roughly 1.5 GPU-seconds/second — 2 GPUs with headroom. That arithmetic is the entire basis of
the deployment sizing in `13_DEPLOYMENT_ARCHITECTURE.md`.

### Extension Points

- **Detector adapters** (port): YOLO family, RT-DETR, DINO/Grounding-DINO, open-vocabulary detectors,
  segmentation models, pose estimators, specialized detectors (face, plate, fire/smoke).
- **Ensemble/cascade strategies** (port): cheap model first, expensive model on ambiguity.
- **Open-vocabulary detection**: a text-prompted detector maps prompts to taxonomy classes at the
  adapter boundary — new classes without retraining, and the module is unchanged.
- **3D and depth**: `SpatialInfo` already admits volumes and ground points, so stereo/LiDAR-assisted
  detection is an adapter concern.

---

# M6 · Tracking Engine

### Purpose

Answer **"is this the same thing I saw a moment ago?"** within a single camera — converting per-frame
detections into temporally continuous `Track` objects with motion state and honest association
confidence.

> **Single responsibility:** *Associate detections across time within one camera. Never assert durable
> identity — that is M7.*

### Responsibilities

1. Associate detections frame-to-frame into tracks.
2. Maintain track lifecycle: `tentative → confirmed → coasting → lost → terminated`.
3. Estimate motion (velocity, heading, acceleration) and classify `motion_state`.
4. Predict positions during detection gaps, marking predictions as such (`measurement_basis`).
5. Report association confidence and `break_reason` diagnostics.
6. Handle detection gaps caused by scheduler drops — *the platform deliberately skips frames, so gap
   handling is a normal operating condition here, not an exception path.*

### Public API

```text
update(camera_id, frame_ref, detections)  → TrackUpdate
tracks(camera_id)                          → Track[]
reset(camera_id, reason)                   → TrackerEpoch     # mints a new epoch
capabilities()                             → TrackerCapabilities
health()                                   → ComponentHealth
```

```text
TrackUpdate:
  active     : Track[]
  new        : TrackId[]
  terminated : [(TrackId, reason)]
  coasting   : TrackId[]
  associations : [(TrackId, DetectionIndex, Confidence, method)]
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| `Detection[]` per frame (M5) | `Track[]` with lifecycle and motion |
| Frame timing (for correct dt across skipped frames) | Association confidences and methods |
| Optional appearance embeddings (from a re-ID adapter) | `break_reason` diagnostics |
| Tracker configuration | Track lifecycle events |

### Dependencies

Detection Engine (M5), Tracker port (adapter), optional Re-ID/embedding port, Camera Manager (for
calibration when tracking on the ground plane), Metrics, Event Bus, Clock.

### State Ownership

**Owns:** per-camera tracker state — active tracks, motion filter state, appearance memory, epoch
counter. This is the platform's most *volatile* state and is deliberately **not durable**: on restart,
tracks restart under a new `TrackerEpoch`. Object continuity across restarts is M7's problem, solved
with durable object identity, which is exactly why the two modules are separate.

### Thread Safety

**Strictly single-threaded per camera.** Tracking is inherently sequential — frame N's association
depends on frame N−1's state. Each camera's tracker is an actor processing its frames in order. There
is no cross-camera state, so cameras run fully in parallel with zero contention.

**Ordering is a hard requirement.** Out-of-order frames corrupt tracking silently. The pipeline
guarantees per-camera ordering (M2's actor assigns `FrameSeq`; queues preserve order per camera), and
the tracker asserts monotonicity and rejects out-of-order input loudly rather than degrading quietly.

### Failure Handling

| Failure | Response |
|---|---|
| Detection gap (scheduler drop, detector miss) | Coast with prediction; mark output `predicted`; terminate after `max_coast` |
| Occlusion | Coast; `break_reason = occlusion`; hand re-association to M7 if the gap exceeds tracker capability |
| ID switch (suspected) | Emit low association confidence; M7 may split the object later. **The tracker never hides uncertainty to look clean** — a confidently wrong association is far more damaging downstream than an admitted uncertain one |
| Crowded scene, association ambiguity | Prefer terminating a track over a wrong association; publish the ambiguity |
| Adapter failure | Fall back to a trivial IoU tracker (always available, no model needed) so the pipeline degrades rather than stops (V9) |
| Out-of-order frame | Reject, count, alarm — this is a pipeline bug and must be loud |
| Tracker state corruption / unbounded growth | Reset with a new epoch; emit `lifecycle` observations so consumers see the discontinuity rather than inferring teleportation |

### Performance

Tracking is CPU-bound and cheap relative to detection — typically <5% of pipeline cost — **unless**
appearance-based re-identification is enabled, which adds an embedding model per detection and can
exceed detection cost. Therefore:

- Geometric tracking is the default.
- Appearance embeddings are computed **selectively** (on track initiation, on ambiguity, on re-entry
  candidates) rather than per detection per frame. This is invariant V7 applied inside tracking, and it
  is the difference between a tracker that costs 5% and one that costs 60%.
- Association is O(n·m); with gating by predicted position it is effectively linear at realistic
  densities. Crowd scenes (n > 100) need spatial hashing.

### Extension Points

- **Tracker adapters** (port): IoU/SORT, ByteTrack, BoT-SORT, OC-SORT, DeepSORT, transformer trackers
  (MOTR-family), joint detection-and-tracking models.
- **Motion models** (port): constant velocity, Kalman variants, learned motion priors, ground-plane
  tracking using homography (markedly better than image-space tracking under perspective).
- **Appearance/Re-ID adapters** (port) — shared with M7's cross-camera matching.
- **Joint detect-track models**: absorbed by having the adapter implement both ports and the platform
  fusing the two stages internally. The module boundary survives even a model that erases it, because
  the boundary is about *responsibility*, not about process count.

---

# M7 · Object Registry

### Purpose

Own **durable object identity** — converting fragile, camera-local track IDs into stable `ObjectId`s
that survive occlusion, track breaks, re-entry, and (in later phases) camera handoff.

> **Single responsibility:** *Decide what is the same thing over time, and be the only module allowed
> to decide it.*

This module exists because invariant V10 requires that track ≠ object. It is the seam where cross-camera
re-identification will plug in years from now without touching any tracker.

### Responsibilities

1. Mint, bind, and retire `ObjectId`s — **sole authority** (`01_LAYERED` §8).
2. Bind tracks to objects with method and confidence; re-bind after breaks.
3. Own the `VisualObject` lifecycle state machine (`02_VOM` §10.6).
4. Resolve class flapping using the retained class distribution.
5. Compute region membership, entry/exit, and dwell — as **pure geometry** (V1/V2).
6. Hold current attribute values as they are produced, and mark them stale on schedule.
7. Emit identity assertions as revisable claims with evidence (`02_VOM` §4.2).
8. Provide the merge/split operations that correct identity errors without rewriting history (V5).

### Public API

```text
ingest(camera_id, track_update)     → RegistryUpdate
get(object_id)                      → VisualObject !NotFound
active(scope)                       → VisualObject[]
bind(track_id, object_id, method, confidence, evidence) → BindingId
merge(source_object, target_object, evidence)  → ObjectId    # source → merged_into
split(object_id, at: Time, evidence)           → (ObjectId, ObjectId)
apply_attribute(object_id, attribute)          → void
expire_stale(now)                   → ObjectId[]
subscribe()                         ⇢ ObjectCreated | ObjectLifecycleChanged
                                    | IdentityAsserted | IdentityRevised
                                    | RegionTransition
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| `TrackUpdate` from M6 | `VisualObject` records and lifecycle transitions |
| Attributes from the Observation Builder path | Identity assertions with confidence + method |
| Region definitions (M1) | Region entry/exit/dwell (geometry only) |
| Optional appearance embeddings | Registry events |
| Optional cross-camera hints (Phase 2+) | Candidate objects for M8's trigger evaluation |

### Dependencies

Tracking Engine (M6), Camera Manager (M1, regions & calibration), optional Re-ID port, Storage
Interfaces (durable object state), Metrics, Event Bus, Clock.

### State Ownership

**Owns:** the `VisualObject` population, track↔object bindings, lifecycle states, current attribute
values, region membership state, dwell accumulators.

This is the **first durable, semantically meaningful state in the pipeline.** It is partitioned by
camera (site-scoped IDs, camera-owned partitions) and is the primary input to the Vision State
projection. Unlike tracker state, it *must* survive restart — an object that has been present for 20
minutes must not become a new object because a process recycled.

### Thread Safety

**Single writer per camera partition.** Each partition is owned by one actor; all mutations are
serialized through it, which makes lifecycle transitions and dwell accumulation race-free without
locks.

Two cross-partition operations exist — `merge` and cross-camera binding — and they are handled
deliberately as **two-phase, event-driven, eventually-consistent** operations at the site layer rather
than by taking cross-partition locks. Taking locks across camera partitions would reintroduce, at the
worst possible place, exactly the global contention the sharding model was designed to eliminate.

Readers use immutable snapshots.

### Failure Handling

| Failure | Response |
|---|---|
| Track ends without explanation | Object → `occluded`, then `dormant`, then `departed` on horizon expiry. Never deleted abruptly |
| Re-entry ambiguity (two candidates match) | Create a *new* object and emit a low-confidence identity assertion linking candidates. **Never guess silently**; let the consumer choose a confidence threshold (V1) |
| Late merge discovery | `merge` with lineage; prior observations remain valid and resolvable via `merged_into` (V5) |
| Class flapping | Resolve using accumulated distribution, publish `class_history`; never silently rewrite past class assertions |
| Object population explosion (tracker thrashing) | Cap per-camera population; shed `provisional` objects first; alarm — a runaway registry is a memory leak with a face |
| Region geometry changes mid-flight | Existing dwell accumulations are closed out and new ones opened against the new region version; both are published with their version |
| Restart | Reload durable objects; all tracks are new (new `TrackerEpoch`); re-bind by spatial and temporal proximity with explicitly reduced confidence |

### Performance

- Per-camera object population is small (tens to low hundreds); operations are trivially cheap.
- Attribute maps and spatial history are **bounded ring buffers**, sized by configuration. Unbounded
  history here is the most likely long-run memory leak in the entire platform, which is why bounding is
  a structural property rather than a tuning parameter.
- Durable writes are **batched and asynchronous** — the hot path updates memory and enqueues
  persistence; it never blocks on I/O.
- Region membership uses precomputed spatial indices; polygon tests are per object per frame and must
  not be naive at 100 objects × 20 regions.

### Extension Points

- **Identity resolution strategies** (port): spatio-temporal only; appearance-based; hybrid; learned
  association.
- **Cross-camera re-identification** (port) — the designed-for future. It plugs in *here*, consumes
  embeddings and topology, and emits identity assertions. No tracker, detector, or pipeline module
  changes. This is the concrete payoff of separating M6 from M7.
- **Camera topology model**: which cameras are adjacent, with transit-time priors, enabling constrained
  handoff matching.
- **Long-term identity** (a returning object recognized days later): the same port, with a durable
  gallery. The lifecycle state machine already has `dormant` and `departed` states to build on.
- **Cross-site identity**: a federation concern, deliberately deferred, and heavily constrained by
  privacy policy (`12_SECURITY_AND_PRIVACY.md`).

---

# M8 · Crop Manager

### Purpose

Decide **what deserves expensive analysis**, and prepare defensible input for it — the platform's
attention mechanism and the primary enforcement point of invariant V7.

> **Single responsibility:** *Choose what to look at closely, and produce a crop worth looking at.*

This module is why a 100-camera deployment is affordable. Without it, understanding cost is
`cameras × fps × objects`. With it, cost is `demands × changes`, which is smaller by two to three orders
of magnitude in every realistic deployment.

### Responsibilities

1. Evaluate **understanding triggers** against active demand contracts and budget.
2. Apply **quality gating** — reject crops too poor to support a defensible claim.
3. Extract crops: padding, rectification, resolution normalization, colour handling.
4. Content-address crops (`CropId`) and deduplicate.
5. Manage the **understanding budget** — a hard ceiling on expensive inference per unit time.
6. Prioritize when demand exceeds budget.
7. Record skip reasons for every candidate not analysed (V8 — a consumer must be able to tell "no
   attribute because nothing was there" from "no attribute because we could not afford to look").

### Public API

```text
evaluate(object_ids, frame_ref)      → CropRequest[] | Skipped[(object_id, reason)]
extract(crop_request)                → Crop !GateRejected !FrameUnavailable
register_demand(demand)              → DemandId
revoke_demand(demand_id)             → void
budget_status()                      → BudgetStatus
subscribe()                          ⇢ BudgetExhausted | GateRejectionSpike
```

```text
TriggerReason:
  FIRST_SIGHT            # object newly confirmed; no attributes yet
  ATTRIBUTE_MISSING      # a demand requires an attribute never computed
  ATTRIBUTE_STALE        # beyond the demand's freshness SLA
  APPEARANCE_CHANGED     # visual change exceeds threshold — re-look warranted
  LOW_CONFIDENCE         # prior claim was weak; better crop now available
  QUALITY_IMPROVED       # previously gate-rejected; conditions now adequate
  PERIODIC_REFRESH       # cadence floor
  EXPLICIT_REQUEST       # bounded, rate-limited on-demand API call
  LIFECYCLE_TRANSITION   # object entered/left a region, changed lifecycle state
```

```text
SkipReason:
  NO_DEMAND | BUDGET_EXHAUSTED | QUALITY_INSUFFICIENT | FRESH_ENOUGH
  | DEDUPLICATED | PRIORITY_PREEMPTED | FRAME_UNAVAILABLE
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| Candidate objects (M7) | `Crop` objects with quality grades and transform records |
| Demand contracts (via Observation API → demand registry) | Skip records with attributed reasons |
| Frame pixels via lease/pin (M4) | Budget telemetry |
| Current attribute state and staleness (M7) | `TriggerReason` for evidence |
| Budget configuration | |

### Dependencies

Object Registry (M7), Frame Buffer (M4), demand registry, Configuration, Metrics, Event Bus, Clock.

### State Ownership

**Owns:** per-object trigger state (last analysis time per attribute, last appearance signature),
budget accounting, crop deduplication cache, priority queues. Ephemeral and node-local; rebuilt from
registry state after restart, with the conservative consequence that a restart causes one round of
`FIRST_SIGHT` re-analysis. Acceptable and bounded.

### Thread Safety

Per-camera single-writer for trigger state, matching M7's partitioning. The **budget is shared across
cameras** and uses atomic counters with periodic reconciliation — the same trade as M3, and for the
same reason.

The crop extraction itself is CPU/GPU work and runs on a worker pool; extraction is a pure function of
(frame, box, transform) and is therefore trivially parallel and trivially testable.

### Failure Handling

| Failure | Response |
|---|---|
| Frame already evicted | Skip with `FRAME_UNAVAILABLE`; count. Signals that pin TTL or buffer depth needs tuning — a diagnosable configuration issue rather than a mystery |
| Quality gate rejects | Skip with reason; retry when `QUALITY_IMPROVED` fires. Never send a hopeless crop to an expensive model |
| Budget exhausted | Skip by priority; emit `BudgetExhausted`; **publish coverage observations** so consumers know attributes are thinned (V8) |
| Demand cannot ever be satisfied (e.g. object always too small at that camera) | Detect the persistent pattern, publish a **capability gap** so the consumer stops waiting for data that will never arrive |
| Extraction error | Count, skip, continue |
| Deduplication cache growth | Bounded LRU |

### Performance

The single most important cost-control point in the platform.

| Lever | Typical effect |
|---|---|
| **Demand-driven only** | Nothing is computed that no consumer asked for — often a 10× reduction on its own |
| **Change-based triggering** | A stationary object does not need re-analysis every second — often another 5–20× |
| **Quality gating** | Avoids paying for crops that cannot produce a usable answer |
| **Deduplication** | Identical crops resolve from cache |
| **Batch-aware extraction** | Crops are grouped for the understanding tier's batch |
| **Resolution normalization** | Crops are emitted at the model's native input size — never larger, which is pure waste |

**Worked cost model.** 100 cameras × 5 objects × 5 fps = 2500 candidate analyses/second. With demand
filtering (~3 attributes on ~30% of objects), change-based triggering (~5% of frames warrant re-look),
and quality gating (~80% pass), the real rate is roughly **10–15 VLM calls/second** — a difference
between "impossible" and "one GPU." That reduction is not an optimization; it is the architecture.

### Extension Points

- **Trigger policies** (port): the trigger set above is a default policy, fully replaceable. Novelty-
  driven, uncertainty-driven, and learned-salience policies all plug in here.
- **Quality estimators** (port): heuristic sharpness/scale today; learned quality predictors later.
- **Crop strategies** (port): tight box, context-padded, multi-scale, part-focused (head region for
  headwear, torso for hi-vis), temporal stacks for motion-dependent attributes, panoramic composites.
- **Appearance-change detectors** (port): histogram, embedding distance, learned change detection.
- **Budget policies** (port): fixed rate, cost-aware (different models cost differently), deadline-aware,
  value-of-information ranking.

> **The ceiling holds here too.** A trigger policy may say "re-look because appearance changed by 0.4
> cosine distance." It may never say "re-look because this is the kitchen." Priority is expressed as an
> opaque class supplied by configuration; the reason a class exists lives with the consumer (V1/V2).

---

## Where to go next

| Question | Document |
|---|---|
| What happens to these crops? | `04_MODULES_UNDERSTANDING_AND_STATE.md` |
| Who provides the models and plugins? | `05_MODULES_PLATFORM_KERNEL.md` |
| What exactly is a detector port? | `06_PORTS_AND_ADAPTERS.md` |
| How do threads and queues actually run? | `08_RUNTIME_AND_THREADING.md` |
