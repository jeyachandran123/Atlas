# UnityWorks Vision OS — Flow 1 Implementation Report

## Infrastructure & Acquisition

| | |
|---|---|
| **Flow** | 1 of 8 — Infrastructure & Acquisition |
| **Status** | Complete |
| **Package** | `backend/app/vision_os/` |
| **Tests** | `backend/tests/vision_os/` |
| **Result** | **315 tests passing · 94% coverage · ruff clean** |
| **Architecture** | Implemented as frozen. No deviations. Two clarifications recorded in §7. |

---

## 1. Implementation Summary

Flow 1 delivers the L0 kernel and the L1 acquisition layer: everything required to
turn a configured camera into a stream of **trustworthy frames** — correctly
identified, correctly timestamped, privacy-masked, admitted under budget — and
nothing beyond that.

The flow ends at admission. An admitted frame is counted and released; there is no
detection, no tracking, no cropping, no understanding, no observation, no state
projection, and no API. Those are Flows 2–8.

```
                     ┌──────────────── L0 KERNEL ────────────────┐
                     │ Runtime · Config · Plugins · EventBus     │
                     │ Health · Metrics · (Clocks)               │
                     └───────────────────┬───────────────────────┘
                                         │ injected into every module
   ┌─────────────────────────────────────▼─────────────────────────────────┐
   │                          L1 ACQUISITION                               │
   │  CameraManager ─▶ VideoSourceManager ─▶ FrameBuffer ─▶ FrameScheduler │
   │   (identity)       (actor per source)    (leases)       (admission)   │
   └───────────────────────────────────────────────────────┬───────────────┘
                                                           │
                                              ══ FLOW 1 ENDS HERE ══
                                              Flow 2 (Detection) resumes
```

**Scale of work:** 66 implementation modules (9,938 lines), 20 test modules
(5,021 lines).

---

## 2. Implemented Modules

### L0 Kernel — 6 of 7 (M18 deferred, see §7.1)

| Module | Package | Single responsibility |
|---|---|---|
| **M15 Runtime** | `kernel/runtime/` | Make the platform exist and keep it running. Composition root, lifecycle, staggered attach, graceful drain. |
| **M16 Configuration Manager** | `kernel/config/` | Resolve and validate layered configuration. The **closed schema** lives here. |
| **M17 Plugin Manager** | `kernel/plugins/` | Validate, load, isolate, bind plugins. Runs the conformance gate. |
| **M19 Event Bus** | `kernel/events/` | Deliver typed notifications, bounded, with structural gap reporting. |
| **M20 Health Monitor** | `kernel/health/` | Know what is working. Owns observability state and silent-failure detection. |
| **M21 Metrics Engine** | `kernel/metrics/` | Count things cheaply. Enforces cardinality bounds. |
| *(Clocks)* | `kernel/clock.py` | `SystemClock` · `VirtualClock` · `ScaledClock` — the V13 prerequisite. |

### L1 Acquisition — 4 of 4

| Module | Package | Single responsibility |
|---|---|---|
| **M1 Camera Manager** | `acquisition/camera_manager/` | Know what each camera is. Copy-on-write snapshots; calibration versioning. |
| **M2 Video Source Manager** | `acquisition/source_manager/` | Produce trustworthy frames. One actor per source; epoch discipline; fail-closed privacy. |
| **M3 Frame Scheduler** | `acquisition/scheduler/` | Allocate scarce perception capacity. Every drop attributed. |
| **M4 Frame Buffer** | `acquisition/buffer/` | Own pixel memory and its lifetime. Per-camera rings, leases, pins. |

### Vision Object Model — Flow 1 subset

Implemented: `Camera` · `Frame` · `Region` + the identity, time, space and health
models. **Deliberately absent:** `Detection`, `Track`, `VisualObject`, `Crop`,
`Attribute`, `Observation`, `Evidence`, `VisionState` — each belongs to a later
flow, and an architecture test asserts they do not exist.

### Ports — 11 of the 32-port catalogue

`P1 Source` · `P2 Decoder` · `P3 PrivacyMask` · `P4 ClockSync` · `P5 AdmissionPolicy` ·
`P6 ChangeDetector` · `P7 Allocator` · `P23 ConfigSource` · `P24 SecretProvider` ·
`P29 EventTransport` · `P30 MetricsExport` · *(Clock)*

The other 21 are named in `PortCatalogue` so a manifest referencing a later-flow
port fails validation with a clear message — but they are **not bindable**.

### Adapters — 21 reference implementations, all dependency-free

| Port | Adapters |
|---|---|
| P1 | `InMemoryRawSource` (scriptable: connect failure, mid-stream loss, looping) |
| P2 | `PassthroughDecoder` (injectable decode failures, poison payloads) |
| P3 | `NoMaskPolicy` · `StaticZoneMask` · `FailingMask` |
| P4 | `ArrivalTime` · `WallclockHint` · `Pts` · `Unknown` ClockSync |
| P5 | `CadenceAdmissionPolicy` · `AdmitAllPolicy` · `ResolutionLadderPolicy` |
| P6 | `NullChangeDetector` · `SampledDigestChangeDetector` |
| P7 | `HostMemoryPool` |
| P23/P24 | `InMemoryConfigSource` · `JsonFileConfigSource` · `InMemorySecretProvider` · `EnvironmentSecretProvider` |
| P29/P30 | `Null`/`Recording`/`Failing` EventTransport · `InMemory`/`OpenMetricsText` exporters |
| *(M2 private)* | `JsonFileEpochStore` — atomic, crash-safe epoch persistence |

Every adapter is stdlib-only, so the entire suite runs in CI with no network, no
codec library, and no camera.

---

## 3. Public APIs

Contract-level surfaces; full signatures in each module's docstring.

```text
CameraManager
  get · try_get · list · resolve_profile · regions_of
  get_calibration · calibration_history · project_to_ground
  provision · retire · recalibrate · report_viewpoint_drift · set_status

VideoSourceManager
  open(camera, bindings, on_frame, credential) → SourceActor
  close · close_all · status · statuses · is_open

FrameBuffer
  acquire_slot · publish · discard_slot          (write side)
  acquire · try_acquire · pin · unpin · is_resident   (read side)
  sweep · stats · close · register_camera · forget_camera

FrameScheduler
  offer(camera_id, view?, dimensions?) → AdmissionVerdict
  complete · register_camera · forget_camera
  override_cadence · current_pressure · camera_rates

ConfigurationManager
  load · reload · effective · revision · explain · history
  platform/buffer/scheduler/source/health/metrics/runtime/cameras/regions/profiles
  resolve_secret · override · clear_override · watch · validate_candidate

EventBus        publish · subscribe · unsubscribe · register_event_type · stats · close
MetricsEngine   counter · gauge · histogram · timer · snapshot · export
HealthMonitor   report · component_health · set_observability · observability
                coverage_gaps · site_health · observe_frame_digest · readiness · liveness
PluginManager   register · validate · load · activate · resolve · swap · unload
                run_conformance · catalogue · bindings · capabilities
VisionRuntime   boot · attach_pipeline · detach_pipeline · drain · shutdown
                readiness · liveness · topology · pipeline_stats

bootstrap       build_platform(...) → VisionPlatform      # the composition root
```

---

## 4. Dependency Graph

```
                    core/  (contracts — stdlib only, zero I/O)
                      ▲
        ┌─────────────┼──────────────┬──────────────┐
        │             │              │              │
    kernel/      acquisition/    adapters/    conformance/
        ▲             │              ▲              ▲
        └─────────────┘              │              │
        (L1 calls L0)                │              │
                                     │              │
                              bootstrap.py ─────────┘
                          (the ONLY place adapters are chosen)
```

**Enforced mechanically** by `tests/vision_os/architecture/`:

- `core` imports stdlib only — no numpy, cv2, torch, redis, sqlalchemy, fastapi…
- `core` never references `kernel`, `acquisition`, or `adapters`.
- `kernel` never imports a flow layer (the kernel law: no L0 module knows what a frame is).
- `acquisition` never imports `adapters`.
- No platform module names a concrete adapter (`HostMemoryPool`, `PassthroughDecoder`, …).
- No module reads `time.time()` / `datetime.now()` — only `kernel/clock.py` may.
- No mutable module-level singletons.
- Every module receives collaborators by constructor.

---

## 5. Architecture Compliance Report

| # | Invariant | Status | How it is enforced in code |
|---|---|---|---|
| **V1** | Semantic Ceiling | ✅ | Closed config schema rejects `rules`/`alerts`/`business` sections; identifier-token scan for judgment vocabulary; `Region` carries geometry + an **opaque** label with no semantic field. |
| **V2** | Vertical Neutrality | ✅ | `ALLOWED_TOP_LEVEL` is closed and asserted; no config key may contain `rule`/`alert`/`threshold_seconds`/`violation`; domain-vocabulary scan over all platform identifiers. |
| **V3** | Ports over implementations | ✅ | 11 ports + 11 conformance kits; `PluginManager.load` runs the fast subset and **refuses to activate a failing adapter**; proven with deliberately broken adapters. |
| **V4** | Explainability | ⚪ Partial (by design) | Provenance fields exist in the object model; full evidence assembly belongs to the Observation Builder (Flow 6). |
| **V5** | Immutability | ✅ | `Frame`, `Camera`, `Region`, all value objects frozen; `Camera.with_status`/`with_calibration` return copies; calibration history is append-only. |
| **V6** | Single-writer state | ⚪ N/A in Flow 1 | Vision State arrives in Flow 7. Per-camera single-writer discipline is already established (actor per source, ring per camera). |
| **V7** | Perceptual economy | ✅ | Scheduler cadence + budget + duplicate suppression; `ChangeDetectorPort` for stride-sampled suppression. |
| **V8** | Blindness is explicit | ✅ | `DropReason` has **no `UNKNOWN` member** and `AdmissionVerdict` rejects an unattributed drop at construction; coverage gaps opened/closed on every transition; `Gap` synthesized structurally on bus drain; shutdown recorded in the coverage record. |
| **V9** | Degrade, never die | ✅ | Reconnect with bounded backoff; decode errors drop one frame; poison payloads quarantined; adapter exceptions never escape the actor; missing calibration degrades to normalized space. |
| **V10** | Layered identity | ⚪ N/A in Flow 1 | Track/object identity is Flows 3 & 7. `FrameRef` identity discipline is fully implemented. |
| **V11** | Normalized time & space | ✅ | `t_capture_uncertainty` mandatory and validated; `ClockQuality.UNKNOWN` refuses fusion; `SpatialInfo` rejects metric coordinates without a `calibration_id` and a `ground_point` without its uncertainty ellipse. |
| **V12** | Pixels stay local | ✅ | `EventTransportPort` carries bounded dict payloads only; `PixelBuffer` never crosses the control plane; architecture test forbids frame-sized payloads on the bus. |
| **V13** | Deterministic replay | ✅ | Clock injected everywhere and statically enforced; `VirtualClock` wakes sleepers in deadline order with insertion-order tie-breaking; an end-to-end replay test asserts byte-identical output across two runs. |

### The Semantic Ceiling, concretely

The platform contains **no** restaurant, hospital, warehouse or retail concept.
Regions are polygons with opaque string labels; `priority_class` is a label the
scheduler orders by and never interprets; the config schema has no slot for a
threshold with business meaning. All four are asserted by tests.

### Single Responsibility

Each module's docstring opens with its one-sentence responsibility, and no module
required an "and" to describe itself. The Frame Buffer owns pixel *lifetime* and
knows nothing about pixels; the Camera Manager owns *identity* and never touches
bytes; the Scheduler *allocates* and processes nothing.

---

## 6. Test Report

```
315 passed · 94% coverage · ruff: All checks passed
```

| Suite | Tests | What it defends |
|---|---|---|
| `unit/test_object_model.py` | 32 | Epoch uniqueness across reconnect · mandatory time & projection uncertainty · fail-closed Frame construction · inline-credential rejection · region opacity |
| `unit/test_kernel_config.py` | 32 | Closed schema rejects business sections · fail-fast provisioning · layer precedence & `explain()` · failed reload keeps current revision · secret hygiene |
| `unit/test_kernel_observability.py` | 33 | Clocks · gap markers · cardinality bounds · **silence is never health** · blind ≠ healthy · suspicion never auto-blinds |
| `unit/test_frame_buffer.py` | 24 | Lease/pin semantics · pinned & leased frames never evicted · lease deadline force-break with attribution · pool returns to baseline |
| `unit/test_scheduler.py` | 26 | Unattributed drop impossible by construction · cadence vs budget ordering · sustained shedding degrades published observability · cadence drops do not |
| `unit/test_camera_manager_and_plugins.py` | 40 | Calibration versioning & degenerate rejection · drift inflates uncertainty without blinding · **conformance gate rejects a leaky adapter** · signature enforcement · swap rollback |
| `integration/test_acquisition_flow.py` | 27 | Full path source→decode→mask→buffer→admission · epoch advance on reconnect · **fail-closed privacy** · poison quarantine · actor isolation · **deterministic replay** |
| `integration/test_runtime_lifecycle.py` | 21 | Composition root · fail-fast boot · capacity · graceful drain recorded in coverage · clock selection · maintenance tick |
| `architecture/test_boundaries.py` | 27 | All of §4 and §5, statically |
| `conformance/test_flow1_kits.py` | 32 | Every shipped adapter passes its kit **and** the kits reject 5 deliberately broken adapters |
| `concurrency/test_concurrency.py` | 9 | Torn-read freedom under 8 threads · cross-camera publish · no deadlock across publish/sweep/acquire · slow subscriber never stalls a publisher · lossless metric recording |
| `performance/test_hot_paths.py` | 12 | Admission budget (3000 decisions) · lease cycle cost · **no steady-state growth** across 2000 cycles · bounded histograms/cardinality/bus buffers · memory scales with depth not camera count |

**Coverage by area:** ports 99–100% · object model 88–100% · kernel 87–100% ·
acquisition 90–99% · adapters 83–100% · bootstrap 100%.

### The tests that earn their keep

- **`test_epoch_makes_frame_refs_unique_across_reconnects`** — the bug every naive
  RTSP implementation ships: frame 100 before and after a reconnect comparing equal.
- **`test_mask_failure_drops_the_frame_and_blinds_the_camera`** — the only
  fail-closed path in the platform, rehearsed rather than assumed.
- **`test_leaky_allocator_fails_the_resource_section`** — proves the conformance
  gate has teeth; without it "every model is replaceable" is already false.
- **`test_identical_input_yields_identical_output`** — V13, the basis of every
  future regression test.
- **`test_no_domain_vocabulary_in_platform_code`** — catches the *first* domain
  leak, which is the one that establishes precedent.

---

## 7. Architectural Clarifications (no deviations)

The architecture is frozen and was implemented as written. Two points where it was
**silent** rather than contradicted, resolved conservatively and recorded here.

### 7.1 M18 Model Manager deferred to Flow 2

`05_MODULES_PLATFORM_KERNEL` places the Model Manager in L0. Its declared
responsibilities — artifact verification, device residency, model handles,
calibration profiles, canary/shadow rollout — exist **exclusively** to serve the
Detection Engine (Flow 2) and the Understanding Engine (Flow 5). No Flow 1 module
acquires a model handle.

Implementing it now would mean building a device broker, artifact store and
residency policy with no consumer to validate them against — speculative work that
the instruction "do not implement future flows" forbids. It is therefore the first
item of Flow 2, where its first real consumer appears.

**No architecture change. No module merged. Nothing skipped.**

### 7.2 Stream-epoch persistence is M2-private, not a new port

`03_MODULES` §M2 requires that "the last used epoch" survive process restart, but
does not say which storage contract holds it. It is not configuration, not
observation log, and not state projection.

Rather than add a 33rd entry to the closed port catalogue, this is implemented as a
**module-private persistence protocol** (`EpochStore`) inside M2 — squarely within
M2's declared state ownership — with an in-memory default and a crash-safe
`JsonFileEpochStore` adapter. If a future flow shows this belongs in the platform
catalogue, promoting it is a one-line change.

**The port catalogue remains closed at 32.**

---

## 8. Known Limitations

| # | Limitation | Consequence | Resolution |
|---|---|---|---|
| 1 | Reference adapters only — no RTSP, NVDEC, QSV, VAAPI | Cannot ingest a real camera yet | Author adapters behind P1/P2; conformance kits already exist. No platform change. |
| 2 | `SignatureVerifier` checks presence and a trust set, not cryptography | Supply-chain enforcement is structural, not yet cryptographic | Substitute a real verifier; the enforcement point already exists. |
| 3 | Plugin isolation is `IN_PROCESS` only | A crashing in-process plugin circuit-breaks but shares the process | `SUBPROCESS`/`REMOTE` are declared in the manifest and honoured by design; implement when an untrusted adapter arrives. |
| 4 | Buffer is host-memory only | No device-resident zero-copy path | `AllocatorPort` + `WritableSlot` already express it; add a CUDA adapter. |
| 5 | Single-node placement | No distributed pipeline placement | `topology()`/`attach_pipeline` already express placement (08_RUNTIME §8.3). |
| 6 | Soak testing is allocation-driven, not 30-day wall-clock | Long-run leaks proven over 2,000 cycles, not 30 days | Add a scheduled soak job using `ScaledClock`. |
| 7 | Frozen-frame detection only (Layer 1 liveness) | Distribution-drift and active-probe detection absent | Layers 2–3 need detection-rate baselines — Flow 2. |
| 8 | pytest-asyncio deprecation warning suppressed | Caused by the pre-existing Atlas root `conftest.py`, not by Vision OS | Resolves when Atlas migrates off its custom `event_loop` fixture. |

---

## 9. Extension Points

Every one of these is an **adapter or configuration change** — no platform module
is touched.

| Extension | Mechanism |
|---|---|
| RTSP / WebRTC / ONVIF / file / **drone** / **mobile** sources | `SourcePort` implementations. Drone adds telemetry as `wallclock_hint`; M1's calibration API is already time-varying. |
| Hardware decode (NVDEC/QSV/VAAPI) | `DecoderPort` |
| Face/plate blur, full-frame encryption | `PrivacyMaskPort` |
| PTP, NTP+RTCP | `ClockSyncPort` |
| Fair-share, priority, deadline-aware, activity-adaptive admission | `AdmissionPolicyPort` |
| Codec motion vectors, learned change detection | `ChangeDetectorPort` |
| CUDA / unified / shared memory / RDMA pools | `AllocatorPort` |
| Git, K8s ConfigMap, cloud parameter store | `ConfigSourcePort` |
| Vault, cloud secret manager | `SecretProviderPort` |
| NATS, Kafka, cloud pub/sub | `EventTransportPort` |
| Prometheus, OpenTelemetry, StatsD | `MetricsExportPort` |
| Edge / node / cluster topology | `deployment_profile` configuration |
| Deterministic replay & accelerated soak | `clock_mode: virtual | scaled` |

---

## 10. Confirmation: No Future Flow Implemented

| Flow | Responsibility | Present? | Verified by |
|---|---|---|---|
| **2** | Detection | ❌ | No `DetectorPort` binding; `Detection` type absent; no `detection/` package |
| **3** | Tracking | ❌ | No `TrackerPort` binding; `Track`/`VisualObject` absent; no `tracking/` package |
| **4** | Crop Management | ❌ | No `CropStrategyPort`; `Crop` absent |
| **5** | Vision Understanding | ❌ | No `UnderstanderPort`; no `Attribute`; no prompt manager |
| **6** | Observation Builder | ❌ | No `Observation`/`Evidence`; `build_coverage` absent — coverage exists only as **state and events** |
| **7** | Vision State | ❌ | No `VisionState`; no observation log; no projection |
| **8** | Observation API | ❌ | No query, subscription, or demand-contract surface |
| — | M18 Model Manager | ❌ | Deferred to Flow 2 with justification (§7.1) |

**Asserted, not merely claimed**, by `architecture/test_boundaries.py::TestFlowScope`:

```python
def test_only_flow1_ports_are_bindable()      # 11 bindable; detector/tracker/understander excluded
def test_no_later_flow_object_kinds_exist()   # Detection, Track, Crop, Attribute, Observation…
def test_no_later_flow_modules_exist()        # detection/, tracking/, understanding/, state/, api/
def test_model_manager_is_deferred_to_flow_2()
def test_no_observation_types_are_emitted()   # Flow 1 emits state and events, never Observations
```

Flow 1's frame sink deliberately ends at admission:

```python
if verdict.admit:
    pipeline.admitted += 1
    self._health.observe_frame_digest(camera_id, _digest(frame))
    # Flow 1 boundary: the admitted frame is released immediately.
    # Flow 2 will take a lease here and hand it to detection.
    self._scheduler.complete(camera_id)
```

---

## 11. Readiness for Flow 2

Flow 2 (Detection) attaches at exactly one seam and needs exactly three things,
all of which already exist:

1. **A frame to detect on** — `FrameBuffer.acquire(frame_ref, holder_id)` returns a
   deadline-bounded, read-only lease.
2. **A model to run** — M18 Model Manager, the first item of Flow 2.
3. **A port to run it behind** — `PortCatalogue.DETECTOR` is already named; adding
   it to `FLOW1_PORTS`' successor set plus a `kit.detector` makes it bindable.

The admitted-frame path in `VisionRuntime._make_sink` is the single line that
changes.

---

*Flow 1 complete. Awaiting authorization to begin Flow 2 — Detection.*
