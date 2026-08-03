# Implementation Flow 2 — Detection

**Status:** complete
**Scope:** Flow 2 only — Detection
**Architecture:** unchanged. No architectural review was raised during this flow.

Detection answers exactly one question: *what objects are visible in this frame?*
It has no memory of previous frames, assigns no persistent identity, performs no
reasoning, and interprets no business meaning. It ends when standardized
detections are emitted.

---

## 1. Implementation Report

### 1.1 What was built

33 new source files, 5,696 lines, across seven areas. Every module owns one
responsibility and receives its collaborators through its constructor.

| Area | Modules | Lines |
| --- | --- | --- |
| Detection object model | `core/model/{detection,confidence,provenance,taxonomy}.py` | 434 |
| Ports | `core/ports/{detection,models,pipeline}.py` | 352 |
| Taxonomy | `taxonomy/registry.py` | 213 |
| Model kernel (M18) | `kernel/models/{manager,devices,calibration}.py` | 916 |
| Detection layer (M5) | `perception/detection/*.py` | 1,729 |
| Adapters | `adapters/detection/*`, `adapters/models/*` | 1,175 |
| Conformance + composition | `conformance/{detector_kit,model_kits}.py`, `detection_bootstrap.py` | 877 |

### 1.2 The twelve required modules

Each maps to a named unit. Where the brief named a concept the architecture
already assigns to an existing kernel module, it was implemented there rather
than duplicated — a second metrics engine or a second plugin loader would be two
sources of truth for one fact.

| Required module | Where it lives | Responsibility |
| --- | --- | --- |
| Detection Engine | `perception/detection/engine.py` | Orchestrates one detection request end to end. `detect()` never raises. |
| Detection Runtime | `perception/detection/runtime.py` | Implements the Flow 1 seam; owns lease acquisition and release. |
| Detection Manager | `perception/detection/manager.py` | Loads, gates, swaps and unloads detector bindings. |
| Detection Scheduler | `perception/detection/scheduler.py` | Cross-camera batching under a dual trigger; bounded queue. |
| Detection Ports | `core/ports/detection.py`, `core/ports/models.py` | P8 DetectorPort, P25/P26/P27 model ports. |
| Detection Adapters | `adapters/detection/`, `adapters/models/` | YOLO, reference, empty; artifact stores, runtimes, device providers. |
| Detection Plugin Loader | `kernel/plugins/` (Flow 1, extended) | `FLOW2_PORTS` added to the bindable set. No second loader. |
| Detection Health Checks | `perception/detection/manager.py` + `kernel/health` | Detector health surfaces through the existing aggregator. |
| Detection Metrics | `kernel/metrics/names.py` (17 new names) | Emitted through the existing engine; cardinality bounded. |
| Detection Configuration | `kernel/config/schema.py` | `DetectionSection`, `ModelsSection`, strongly typed, validated at load. |
| Detection Result Model | `core/model/detection.py` | The standardized `Detection`. |
| Detection Events | `kernel/events/` (6 new events) | Published on the existing bus. |

### 1.3 The standardized Detection

Every field the brief requires is present. Several are named for what they are
rather than what they are called colloquially, with the requested name exposed as
a property so both vocabularies work:

| Required | Field | Note |
| --- | --- | --- |
| Detection ID | `detection_id` | |
| Frame ID | `frame_ref` | `(camera_id, stream_epoch, frame_seq)` — a bare frame number collides across reconnects. |
| Timestamp | `t_capture` + `t_capture_uncertainty` | Capture time, not processing time, with its error bar. |
| Bounding Box | `spatial.box` | Normalized, origin top-left. |
| Confidence | `confidence` | A `Confidence` value carrying its semantics, not a bare float. |
| Object Class | `class_id` + `taxonomy_version` | Platform taxonomy. A class without its taxonomy version is unresolvable later. |
| Detector Name | `provenance.detector_id` → `.detector_name` | |
| Detector Version | `provenance.model_version` → `.detector_version` | |
| Inference Time | `timing.inference_ms` → `.inference_ms` | |
| Coordinate Space | `spatial.frame_of_reference` → `.coordinate_space` | |
| Evidence | `evidence` | What the claim rests on. |
| Metadata | `labels` | Opaque; never interpreted. |

`__post_init__` rejects a detection that is not internally coherent: confidence
that is not `DETECTION_PRESENCE`, a missing box, coordinates outside `[0,1]`, an
empty taxonomy version. An incoherent detection cannot be constructed, so no
downstream stage needs to defend against one.

**Confidence is a type, not a float.** A bare 0.87 is ambiguous — presence?
class? calibrated against what? `Confidence` carries `semantics`, `calibrated`,
`calibration_id` and always preserves `raw_score`, and `comparable_with()`
refuses cross-semantics comparison. Calibration is a platform capability applied
by the normalizer; the model's own number is never overwritten.

### 1.4 Detection is memoryless — enforced, not documented

The brief's central constraint is structural here rather than aspirational:

- `Detection` has no track ID, object ID, or previous-frame reference. Asserted
  by `test_detection_carries_no_identity`.
- `DetectorPort` has no `reset`, `update`, or any method implying a sequence.
  Asserted by `test_detector_port_has_no_temporal_method`.
- No module under `perception/detection/` holds a per-camera or per-object
  dictionary that survives a call. Asserted by
  `test_detection_layer_holds_no_cross_frame_state`, which walks the AST for
  instance attributes that accumulate across frames.
- The kit's `semantics/statelessness` check feeds an adapter the same frame twice
  with an unrelated frame between and requires identical output — an adapter that
  remembers fails to load.

---

## 2. Architecture Compliance Report

### 2.1 Invariants

| | Invariant | How Flow 2 holds it |
| --- | --- | --- |
| V1 | Semantic Ceiling | Detection emits visual classes only. `_FORBIDDEN_CLASS_TOKENS` rejects a taxonomy declaring `customer`, `staff`, `waiting`, `clean` at config load. `test_detection_layer_uses_no_domain_vocabulary` walks the AST for domain nouns. |
| V2 | Vertical neutrality | No vertical appears in code. Taxonomy and mappings are data; `capability_gap()` reports what a deployment demands but no loaded detector produces. |
| V3 | Ports over implementations | Four new ports, each with a conformance kit. `test_no_platform_module_names_a_detector_vendor` scans every module outside `adapters/` and the composition root for vendor identifiers. |
| V4 | Explainability | Every detection carries provenance (detector, model, artifact hash, config revision), timing, and `evidence`. `Provenance` refuses construction without a config revision, and refuses a model id without an artifact hash. |
| V5 | Immutability | All Flow 2 model types are frozen slotted dataclasses. |
| V6 | Single-writer state | The Detection Manager owns bindings; the Model Manager owns model lifecycle; the scheduler owns queues. No shared mutable state between them. |
| V7 | Perceptual economy | Cross-camera batching amortizes inference; fidelity from Flow 1 is honoured when `dynamic_resolution` is set. |
| V8 | Blindness is explicit | A failed detection produces `DetectionOutcome(failed=True, reason=...)`, never an empty success. Empty-but-successful and failed are different states. |
| V9 | Degrade never die | `DetectionEngine.detect()` never raises. GPU loss falls back to CPU. A consumer exception cannot stop acquisition. |
| V10 | Layered identity | Detection assigns none. Identity begins in Flow 3. |
| V11 | Normalized time and space | Coordinates normalized against the rectified source; time from the injected clock. |
| V12 | Pixels stay local | The seam carries a `FrameRef`, not a `Frame`. Pixels are reached through a lease and released in `finally`. |
| V13 | Deterministic replay | No module reads the wall clock. `batch_max_wait_ms=0` makes batch composition independent of arrival timing. The kit's `determinism` check requires byte-identical repeat output. |

### 2.2 The platform does not know YOLO exists

Four independent assertions, because this is the claim most easily eroded by a
single expedient import:

1. `test_no_platform_module_names_a_detector_vendor` — AST scan of every module
   outside `adapters/` and `detection_bootstrap.py` for vendor identifiers.
2. `test_only_the_composition_root_names_a_concrete_detector` — `yolo_factory` in
   `detection_bootstrap.py` is the only function that names YOLO.
3. `test_detection_layer_imports_no_adapter` — nothing under
   `perception/detection/` imports from `adapters/`.
4. `test_engine_holds_a_port_not_a_model` — the engine's annotations reference
   `DetectorPort`, never a concrete type.

Swapping YOLO for RT-DETR is a change to one factory function and one config
file. No platform module changes.

### 2.3 Flow 1 was modified only through documented extension points

Six files, all additive. No Flow 1 behaviour changed for an existing deployment,
and `DetectionSection.enabled` defaults to `False` so Flow 1 remains the default
runtime shape.

| File | Change | Why it is an extension point |
| --- | --- | --- |
| `core/model/ids.py` | Added `ModelId`, `ClassId`, `DetectionId` | The id module is the declared home for platform identifiers. |
| `core/errors.py` | Added the Flow 2 error taxonomy | The error hierarchy is the declared extension surface for new failure modes. |
| `kernel/config/schema.py` | Added `DetectionSection`, `ModelsSection`, declarations | Config sections are per-flow by design; existing sections untouched. |
| `kernel/plugins/manifest.py` | `BINDABLE_PORTS = FLOW1_PORTS \| FLOW2_PORTS` | The frontier constant exists to be widened one flow at a time. |
| `kernel/runtime/runtime.py` | Added optional `admitted_frame_consumer` | **The seam.** Documented in Flow 1 as where a later flow resumes the admitted-frame path. |
| `bootstrap.py` | Added the parameter; default registry `flow1_registry()` → `platform_registry()` | Composition root. |

The seam itself is three lines of protocol:

```python
@runtime_checkable
class AdmittedFrameConsumer(Protocol):
    async def on_admitted(self, frame_ref: FrameRef, fidelity: Fidelity) -> None: ...
```

It carries a `FrameRef` rather than a `Frame` for three reasons: it is
control-plane sized so it works across a process boundary, it forces the consumer
through the lease protocol rather than handing out pixels, and it keeps V12
intact. `None` is the Flow 1 behaviour. The runtime holds the protocol and never
learns what implements it (`test_runtime_holds_the_protocol_not_a_detection_type`,
`test_consumer_is_optional`, `test_seam_carries_a_reference_not_a_frame`).

A consumer that raises is caught, counted as
`vision_os.runtime.consumer_failures`, and the source actor survives — acquisition
is the platform's floor and no downstream stage may take it down.

### 2.4 Explicit scope confirmations

- **No Tracking functionality exists.** No module, class, or field assigns or
  carries a persistent identity. `TrackerPort` is defined in the catalogue and is
  **not** bindable — `test_flow_three_ports_remain_unbindable` fails if it becomes
  bindable before Flow 3.
- **No Cropping functionality exists.** No crop module, no crop policy, no crop
  storage.
- **No Vision Understanding exists.** No VLM, no captioning, no attribute
  enrichment. `UnderstandingPort` is unbindable.
- **No Observation Builder exists.** `test_detection_emits_no_observations` — no
  Flow 2 module constructs an `Observation`.
- **No Vision State exists.** `test_detection_writes_no_state` — no Flow 2 module
  imports or writes a state store.
- **No Business Logic exists.** No alerts, no thresholds on meaning, no POS, no
  restaurant/warehouse/hospital vocabulary anywhere in the layer.
- **Detection produces only standardized detections.** The engine's single output
  type is `DetectionOutcome`, carrying `tuple[Detection, ...]` and nothing else.

---

## 3. Detection Dependency Graph

Dependencies point inward. Nothing in the detection layer imports an adapter;
composition happens only at the root.

```
                        detection_bootstrap.py
                      (composition root — the only
                       place a vendor is ever named)
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
      DetectionRuntime     DetectionManager      ModelManager (M18)
      (implements the       (four load gates)     (artifacts, devices,
       Flow 1 seam)               │                versions, calibration)
              │                   │                       │
              ▼                   ▼                       ▼
      DetectionEngine ──▶ DetectorBinding          DeviceBroker
      (never raises)      (adapter + caps +        CalibrationRegistry
              │            mapping + model)                │
              │                                            │
      ┌───────┴────────┐                                   │
      ▼                ▼                                   ▼
DetectionScheduler  DetectionNormalizer            P25 / P26 / P27
(cross-camera        (D1/D2/D6, NMS,               ArtifactStore
 batching)            calibration, quality)         ModelRuntime
      │                      │                      Device
      ▼                      │                            │
 DeviceWorker                │                            │
      │                      │                            │
      └──────────┬───────────┘                            │
                 ▼                                        │
          P8 DetectorPort ◀───────────────────────────────┘
                 │
                 ▼
        adapters/detection/{yolo,reference}
```

**Acyclic, and the important direction is preserved:** the taxonomy registry is
depended upon by the normalizer and the manager but depends on neither. The Model
Manager knows nothing about vision — `test_model_manager_has_no_vision_vocabulary`
asserts it contains no detection vocabulary, and
`test_model_manager_imports_no_flow_layer` asserts it imports no flow layer. It
manages artifacts on devices; that they happen to be detectors is not its concern.

---

## 4. Plugin Architecture Report

### 4.1 Four gates, in order

`DetectionManager.load()` refuses activation unless all four pass. Order is
deliberate: each gate is cheaper than the one after it, and each makes the next
meaningful.

1. **Compatibility** — does the adapter satisfy the port protocol, and does its
   declared platform version match?
2. **Conformance** — the fast subset of `DETECTOR_KIT` (21 of 23 checks) runs
   against the live adapter. Any failure aborts the load.
3. **Taxonomy validation** — every class the adapter's mapping produces must exist
   in the registry at the declared taxonomy version. A mapping to an unknown class
   is a configuration error caught at boot, not a silent `unknown` in production.
4. **Capability vs mapping** — the adapter's declared capabilities must be
   consistent with what its mapping can actually produce. An adapter claiming to
   detect a class its mapping never emits is rejected.

**An adapter that fails any gate never becomes reachable.** It is not loaded in a
degraded mode, not loaded with a warning: the binding is never installed, so no
frame can reach it.

### 4.2 Swap and rollback

`DetectionManager.swap()` loads and gates the new binding *before* retiring the
old one. If any gate fails, the old binding stays active and the swap reports
failure. A failed model upgrade leaves a working detector running.

### 4.3 Version, capabilities, provenance

Capabilities are derived from the adapter's *mapping*, not from its model name —
a detector's filename is a claim, its mapping is a fact. `ModelMeta` carries the
artifact hash, and `Provenance` refuses to be constructed with a model id but no
artifact hash, so a detection can always be traced to the exact weights that
produced it.

---

## 5. Conformance Kit Report

### 5.1 Coverage

34 executable checks across four ports.

| Port | Kit | Checks | Fast subset | Sections |
| --- | --- | --- | --- | --- |
| P8 DetectorPort | `DETECTOR_KIT` v1.0.0 | 23 | 21 | shape 6, semantics 10, failure 5, resource 2 |
| P25 ArtifactStorePort | `ARTIFACT_STORE_KIT` v1.0.0 | 3 | 3 | shape 1, semantics 1, failure 1 |
| P26 ModelRuntimePort | `MODEL_RUNTIME_KIT` v1.0.0 | 4 | 4 | shape 1, semantics 2, failure 1 |
| P27 DevicePort | `DEVICE_KIT` v1.0.0 | 4 | 4 | shape 1, semantics 2, failure 1 |

Port obligations covered by executable checks: **D1, D2, D3, D4, D5, D6, D7** and
adapter obligations **A1, A3, A4**.

### 5.2 The brief's eleven areas

| Required area | Check |
| --- | --- |
| Bounding Boxes | `semantics/coordinate_normalization` (D1) |
| Confidence | `semantics/confidence_semantics` (D3) |
| Coordinate System | `semantics/letterbox_inverse_exactness` (D1) |
| Class Mapping | `semantics/taxonomy_mapping_complete` (D2) |
| Threshold Behaviour | `semantics/threshold_behaviour` |
| Error Handling | `failure/corrupt_input_is_typed`, `failure/health_never_raises` |
| Performance | `resource/no_steady_state_growth`, `resource/batch_declaration_is_truthful` |
| Determinism | `semantics/determinism`, `semantics/statelessness` (D7) |
| No Fabrication | `failure/no_fabrication_on_failure` (A4) |
| Model Metadata | `shape/model_metadata_is_complete` (A3) |
| Inference Timing | `shape/inference_timing_is_reported` |

### 5.3 The kits are proven to fail

A kit that passes everything it is shown is indistinguishable from no kit.
`test_detector_conformance.py` and `test_model_port_conformance.py` pair every
obligation with a fixture that violates exactly that obligation and nothing else,
and assert the kit rejects it — a drifted-coordinate adapter, a stateful adapter,
an adapter that fabricates on failure, an artifact store that skips hash
verification, a runtime that loses provenance, a device provider that raises when
a card is pulled.

### 5.4 The kit caught a real bug

`ReferenceDetector` — an adapter shipped in this flow — ignored
`request.max_detections`. The kit's `max_detections_respected` check rejected it
at load. This was not a hypothetical: it was a working adapter, written by the
same hand as the kit, that would have silently exceeded its declared bound in
production. The gate mechanism earned its cost during its own implementation.

### 5.5 What the kit cannot prove

Stated plainly because a conformance kit that overstates its reach is worse than
none. See §8.1.

---

## 6. Performance Report

### 6.1 Measured

Reference adapter, CPU only, no GPU present.

| Path | Measured | Budget | Headroom |
| --- | --- | --- | --- |
| Adapter translation per frame | 3.5 µs | 1500 µs | 428× |
| Letterbox inverse per box | 1.28 µs | 80 µs | 62× |
| 3,000 scheduler decisions (100 cameras × 30 fps) | < 5 s | 5 s | sustained |
| 500 concurrent detections | < 30 s | 30 s | sustained |

Budgets are set an order of magnitude above measured cost deliberately. A budget
tuned within 2× of normal fails whenever CI is busy, and a test that cries wolf is
one people learn to re-run rather than read. These catch the class of regression
that turns 100 cameras into 10.

### 6.2 Batching

Cross-camera batching uses a dual trigger — flush when the batch is full **or**
when `batch_max_wait_ms` elapses. Batching across cameras rather than within one
camera is what makes GPU economics work at 100 cameras: one camera cannot fill a
batch of 8 without adding 8 frames of latency, but 100 cameras fill it in
milliseconds.

`batch_max_wait_ms=0` flushes immediately, which is what deterministic mode
requires: batch composition must not depend on arrival timing.

### 6.3 Bounded everywhere

- Inference queue is bounded (`queue_capacity`, default 64). An unbounded
  inference queue is a memory leak with a delayed fuse. Overflow raises
  `DetectionQueueFullError`, counted, never silently dropped.
- Inference runs under `asyncio.wait_for(inference_timeout_ms)`. A hung device
  fails its waiters instead of blocking the platform — the busy path always
  spawns rather than awaiting inline, so a full batch cannot bypass the timeout
  guard.
- Metric cardinality is bounded; no per-detection label exists.
- `resource/no_steady_state_growth` runs an adapter 500 times and asserts object
  count does not grow — the 30-day soak failure, caught in seconds.

### 6.4 Scaling shape

1, 10 and 100 cameras are the same code path at different scales. Detection
capacity is a function of device count and batch size, not camera count; cameras
contribute queue depth, which is bounded and shed under pressure rather than
buffered without limit.

---

## 7. Test Report

### 7.1 Totals

```
Plain run:     599 passed, 0 skipped        (25.6s)
Coverage run:  592 passed, 7 skipped        93% of app/vision_os
                                            (7,431 statements, 523 missed)
Ruff:          all checks passed
Wider Atlas:   1,619 tests collect cleanly; tests/cognitive_kernel 36 passed
```

The 7 tests that skip *only* under coverage are timing budgets. Coverage
instrumentation inflates per-call cost by an order of magnitude, so a latency
assertion measured under a trace function tests the profiler, not the platform.
They run in full in every uninstrumented run — which is the run that matters for
a timing claim. Growth and boundedness assertions stay enabled under coverage;
those remain valid because object counts do not care about tracing.

### 7.2 Flow 2 tests by category

282 tests across ten required categories.

| Category | File | Tests |
| --- | --- | --- |
| Unit — object model | `unit/test_detection_model.py` | 32 |
| Unit — coordinates | `unit/test_letterbox.py` | 44 |
| Unit — normalizer + taxonomy | `unit/test_normalizer_and_taxonomy.py` | 28 |
| Unit — model manager, GPU fallback | `unit/test_model_manager.py` | 45 |
| Conformance — detector | `unit/test_detector_conformance.py` | 20 |
| Conformance — model ports | `unit/test_model_port_conformance.py` | 25 |
| Integration + plugin + failure | `integration/test_detection_pipeline.py` | 35 |
| Integration — end to end | `integration/test_end_to_end.py` | 13 |
| Architecture | `test_detection_architecture.py` | 24 |
| Performance + stress | `test_detection_performance.py` | 16 |

### 7.3 Coverage by area

| Area | Coverage |
| --- | --- |
| `core/model/detection.py` | 100% |
| `core/ports/pipeline.py` | 100% |
| `adapters/detection/letterbox.py` | 100% |
| `conformance/model_kits.py` | 97% |
| `perception/detection/normalizer.py` | 97% |
| `conformance/detector_kit.py` | 95% |
| `perception/detection/scheduler.py` | 93% |
| `adapters/detection/yolo.py` | 93% |
| `kernel/models/manager.py` | 91% |
| `perception/detection/manager.py` | 81% |
| `adapters/models/runtimes.py` | 71% |
| `adapters/models/devices.py` | 72% |

The two lowest are the lazy `torch` and `ultralytics` import paths, which cannot
execute on a machine without CUDA or ultralytics installed. That gap is real and
is recorded in §8.3 rather than papered over with a mock that would prove only
that the mock works.

### 7.4 Architecture tests are executable rules

24 tests assert the architecture rather than describing it. They walk the AST —
not raw text — for vendor identifiers, domain vocabulary, temporal state, and
forbidden imports. An early text-based version flagged legitimate port docstrings
that name YOLO as an *example*; scanning identifiers instead of prose fixed the
false positive without weakening the rule.

---

## 8. Known Limitations

### 8.1 The conformance kit cannot prove letterbox-inverse exactness

A *drifted* letterbox inverse — one that is smooth, self-consistent, and wrong by
a few percent — cannot be detected by any generic kit without ground truth. The
kit can prove a box is in `[0,1]`, ordered correctly, and stable; it cannot prove
it is in the *right place* without knowing where the object actually was.

An earlier check attempted this and rejected the *correct* YOLO adapter, because a
fixed box in letterboxed pixel space legitimately inverts to different normalized
positions at different source aspect ratios. It was removed rather than weakened,
and the kit's docstring now states precisely what its coordinate checks do and do
not establish.

Exactness is instead proven by 44 pure-arithmetic tests over ten aspect ratios
including 1920×60, 60×1920 and 7×5000. This is a real gap in the *gate*, closed
in the *suite*.

### 8.2 "False Detection Counter" was implemented as `DETECTIONS_REJECTED`

The brief asks for a false-detection counter. Falseness requires ground truth —
knowing a detection was wrong is a judgment the platform cannot make from pixels,
and a metric named `false_detections` would be a number the platform invents.
That is a V1 violation.

What is counted instead is `vision_os.detection.rejected`, labelled by reason:
`below_threshold`, `nms_suppressed`, `max_detections`, `not_requested`,
`invalid_geometry`. This is strictly more informative and is true.
`test_there_is_no_false_detection_metric` asserts no metric name contains
"false", so the distinction cannot erode later.

### 8.3 GPU and real YOLO weights are untested in CI

`torch` and `ultralytics` are optional lazy imports. On a CPU-only CI box the CUDA
enumeration path, real weight loading, half-precision, and multi-GPU selection do
not execute — hence 71–72% coverage on those two adapter modules.

What *is* tested: the broker's device selection, headroom, pinning, eviction and
CPU-fallback logic against `StaticDeviceProvider`, including a device disappearing
mid-operation; and that a machine with no CUDA degrades to CPU rather than failing
to start. What is not tested is the torch call itself. Validating against real
hardware is a deployment-time step, not a CI step.

### 8.4 Obligation D8 has no kit check

D8 (quality contributions where derivable) is implemented in the normalizer and
unit-tested, but has no conformance check, because whether a quality signal is
"derivable" depends on the adapter's access to the model internals. An adapter
that declines to contribute quality is conformant.

### 8.5 The golden section is empty

`KitSection.GOLDEN` — correctness against a fixed annotated corpus — is defined
and wired but has no checks, because it needs annotated reference data that is not
shipped with the platform. This is the section that would close §8.1. It is a
data problem, not a code problem.

### 8.6 Calibration profiles are declared, not fitted

`CalibrationProfile` supports identity, temperature and piecewise mapping, and
applies correctly. Fitting a profile from a labelled validation set is out of
scope for Flow 2 — the platform applies calibration; producing the calibration is
an offline activity.

---

## 9. Extension Points

Documented seams for later flows. Each is a place a later flow attaches without
modifying Flow 2.

| Extension point | Where | For |
| --- | --- | --- |
| `DetectionOutcome` consumer | `DetectionRuntime` | **Flow 3.** Tracking attaches to the detection output the way detection attached to the admitted-frame seam. |
| `DetectorPort` | `core/ports/detection.py` | Any detector. Implement, pass the kit, register in config. |
| `ArtifactStorePort` | `core/ports/models.py` | S3, OCI registry, signed artifact store. |
| `ModelRuntimePort` | `core/ports/models.py` | TensorRT, ONNX Runtime, OpenVINO, Triton. |
| `DevicePort` | `core/ports/models.py` | ROCm, Jetson, Hailo, other accelerators. |
| `TaxonomyRegistry.register_class` | `taxonomy/registry.py` | New visual classes without code change; hierarchy is data. |
| `CalibrationRegistry` | `kernel/models/calibration.py` | New calibration methods behind the existing profile type. |
| `ConformanceKit.checks` | `conformance/` | New obligations; a kit is a tuple of checks. |
| `KitSection.GOLDEN` | `conformance/kit.py` | Corpus-based checks when reference data exists (§8.5). |
| `DetectionSection` | `kernel/config/schema.py` | New resource/capability knobs. Strongly typed and validated. |

**Frontier discipline.** `BINDABLE_PORTS` is now `FLOW1_PORTS | FLOW2_PORTS`.
`TrackerPort` and every later-flow port remain defined but unbindable, and
`test_flow_three_ports_remain_unbindable` fails if that changes before Flow 3 is
implemented. The four Flow 1 architecture tests that asserted Flow 2 did not exist
were updated to police the Flow 3 frontier — made stricter, not weaker.

---

## 10. Summary

Flow 2 is complete. 33 new source files, 5,696 lines, 282 new tests, 93% coverage,
ruff clean, no architectural change requested or made.

Detection converts frames into standardized detections and stops there. It has no
memory, assigns no identity, reasons about nothing, and knows no vertical. The
platform does not know YOLO exists — four independent tests enforce it. Every
adapter passes an executable kit before it can receive a frame, and the kits are
themselves proven to reject the adapters they should.

Flow 1 was modified only through documented public extension points, and every one
of those changes is additive with a default that preserves existing behaviour.
