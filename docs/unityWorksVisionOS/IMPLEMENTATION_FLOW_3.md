# Implementation Flow 3 — Tracking

**Status:** complete
**Scope:** Flow 3 only — the Tracking Engine (M6)
**Architecture:** unchanged. One conflict was found and resolved *inside Flow 2's
implementation*; the constitution was not modified.

Tracking answers exactly one question: *does this detection belong to the same
visual object observed recently?* It owns temporal continuity. It does not own
identity, semantic understanding, or business meaning.

---

## 1. Constitution / Architecture Compliance Review

Performed **before any code was written**, as required. The full review is a
separate document — [FLOW_3_COMPLIANCE_REVIEW.md](./FLOW_3_COMPLIANCE_REVIEW.md)
— and is summarised here.

### 1.1 What the architecture binds

| Source | Binding constraint |
| --- | --- |
| `03_MODULES` §M6 | Public API fixed at `update / tracks / reset / capabilities / health`. Six numbered responsibilities. |
| `02_VOM` §10.5 | `Track` fields fixed. `TrackId = (CameraId, TrackerEpoch, LocalTrackId)`. `confidence.semantics = ASSOCIATION`. |
| `06_PORTS` §P9 | Obligations **T1–T8**. |
| `07_STATE` | Tracking owns volatile per-camera state only; writes no Vision State. |
| `08_RUNTIME` | Actor per camera; ordering is a hard requirement; `Detection → Tracking` is **`block`**, never drop. |
| `10_RELIABILITY` | `tracker.iou` is a mandatory always-available fallback. |
| `11_PERFORMANCE` | ~0.3 ms/frame, scaling with object count. |
| `12_SECURITY` | Appearance embeddings are **C2 biometric, disabled by default**. |
| `14_TESTING` §7.2 | Quality is fragmentation, ID switches, occlusion recovery, non-uniform gaps — not per-frame accuracy. |
| `15_ROADMAP` | Cross-camera identity is Phase 2. Not implemented. |

### 1.2 The lifecycle has five states, not six

The architecture specifies exactly `tentative → confirmed → coasting → lost →
terminated`. An earlier framing of this work named a six-state model adding `NEW`
and `RECOVERED`. Those are not states in the constitution and were **not added**.
They map onto what already exists without loss:

- `NEW` is the *creation* of a track, which enters at `tentative` — published as
  `TrackCreated`.
- `RECOVERED` is the *transition* `coasting|lost → confirmed` — published as
  `TrackRecovered`.

Modelling them as events rather than states preserves the architecture exactly
while losing none of the observability that motivated them. `coasting` is
first-class, as `02_VOM` §10.5 requires: a coasted position is a prediction, and
anything derived from it is marked so.

### 1.3 Conclusion

The architecture specifies M6 completely enough to implement without inference.
**No architectural change was requested or made.**

---

## 2. Implementation Report

### 2.1 What was built

15 new source files, 3,858 lines, plus 439 tests.

| Area | Modules | Lines |
| --- | --- | --- |
| Track object model | `core/model/track.py` | 322 |
| Ports (P9, P10, motion, association) | `core/ports/tracking.py` | 242 |
| Tracking toolkit | `perception/tracking/{lifecycle,association,table}.py` | 880 |
| Platform layer | `perception/tracking/{engine,manager,runtime}.py` | 766 |
| Adapters | `adapters/tracking/{motion,geometric,trackers}.py` | 902 |
| Conformance + composition | `conformance/tracker_kit.py`, `tracking_bootstrap.py` | 662 |

### 2.2 The required components

| Required | Where | Responsibility |
| --- | --- | --- |
| Tracking Engine | `perception/tracking/engine.py` | Orchestrates one frame. `track()` never raises. |
| Tracking runtime integration | `perception/tracking/runtime.py` | Implements the `DetectionConsumer` seam; actor per camera. |
| Track lifecycle | `perception/tracking/lifecycle.py` | Closed transition table; illegal edges impossible. |
| Track association | `perception/tracking/association.py` | Cost matrix, gating, greedy + optimal assignment. |
| Track prediction | `adapters/tracking/motion.py` | Stationary and linear predictors behind a port. |
| Track recovery | lifecycle + `geometric.py` | `coasting\|lost → confirmed` on re-association. |
| Track expiration | `lifecycle.py` | Coast budget, recovery window, absolute max age. |
| Track confidence | `core/model/track.py` | `ASSOCIATION` semantics, derived from cost **and margin**. |
| Track history | `perception/tracking/table.py` | Bounded ring of `FrameRef`, never copies. |
| Tracking events | `kernel/events/events.py` | 10 new event types. |
| Tracking metrics | `kernel/metrics/names.py` | 18 new metric names. |
| Tracking health | `engine.py` + `kernel/health` | Surfaces through the existing aggregator. |
| Tracking configuration | `kernel/config/schema.py` | `TrackingSection`, strongly typed, validated at load. |
| Tracker Port | `core/ports/tracking.py` | P9 with T1–T8 in the contract. |
| Tracker adapters | `adapters/tracking/trackers.py` | `tracker.iou`, `tracker.sort`, `tracker.bytetrack`. |
| Tracker plugin loading | `perception/tracking/manager.py` | Two gates; failure never activates. |
| Tracker conformance kit | `conformance/tracker_kit.py` | 22 checks + determinism. |

### 2.3 The Track object

Fixed by `02_VOM` §10.5 and implemented verbatim. Three properties carry the
design:

**`TrackId` is composite** — `(camera_id, tracker_epoch, local_id)`. A bare
integer is the single most common route by which a camera-local, fragile,
seconds-lived handle becomes an identity: it compares equal across cameras,
survives a reset in appearance only, and reads like a primary key. Carrying the
camera and epoch *inside* the identifier makes each of those a type-level
impossibility rather than a convention.

**`detections` holds `FrameRef`, never `Detection`.** References, not copies.
Copying detections into tracks makes tracking memory grow with track lifetime,
breaking T8 on exactly the long-lived tracks that matter most.

**`measurement_basis` is per-position.** A coasting track's position is a
prediction, and presenting it as a measurement is V8 violated at object scale —
invisible to every consumer unless the field travels with the value.
`__post_init__` refuses to construct a predicted-state track that claims a
`MEASURED` position.

### 2.4 The lifecycle is a closed machine

Transitions are an explicit table, not scattered conditionals, because **illegal
transitions must be impossible, not merely unlikely**. A resurrected terminated
track produces output that looks like an object teleporting across the scene
after an unrelated object leaves — plausible, and undetectable downstream.

Read the absences as carefully as the presences:

- `TERMINATED` appears only as a destination. Nothing leaves it.
- `TENTATIVE → LOST` is absent: an unconfirmed track never established continuity,
  so a recovery window would let it compete for associations it has no claim to.
- `LOST → COASTING` is absent: recovery is a return to measurement.

### 2.5 Association refuses to guess

`03_MODULES` §M6 is explicit: *"Prefer terminating a track over a wrong
association"* and *"the tracker never hides uncertainty to look clean — a
confidently wrong association is far more damaging downstream than an admitted
uncertain one."*

That is implemented literally. The **margin** between the best and second-best
candidate is computed and retained rather than discarded, and a match whose margin
falls below `ambiguity_margin` is **refused** — the track coasts rather than
binding to a detection it might not own. Every refusal is published as
`AssociationFailure` carrying both costs.

---

## 3. Engine Interaction Report

### 3.1 The two seams

```
Frame Scheduler (M3, Flow 1)
        │  AdmittedFrameConsumer.on_admitted(frame_ref, fidelity)
        ▼
Detection Runtime (M5, Flow 2)
        │  DetectionConsumer.on_detected(outcome)      ← the Flow 3 seam
        ▼
Tracking Runtime (M6, Flow 3)
        │  actor per camera, awaited inline
        ▼
Tracking Engine ──▶ TrackerPort ──▶ adapter
        │
        ▼
   TrackingOutcome  +  Event Bus (observability)
```

**Backpressure, not dropping.** `08_RUNTIME` §5.2 specifies the
`Detection → Tracking` edge as `block` — *"ordering matters; dropping here
corrupts tracks"*. `on_detected` is awaited inline, so a slow tracker propagates
pressure back through detection to the Frame Scheduler, which is the component
whose job it is to shed.

**Ordering is preserved structurally.** The Flow 1 source actor awaits its sink,
so a camera's frames are offered in sequence; detection awaits its consumer; the
tracking runtime takes a per-camera lock. Frame N+1 cannot begin before frame N
completes for the same camera, while different cameras never contend.

### 3.2 What each engine may assume of the other

| Direction | Guarantee |
| --- | --- |
| Detection → Tracking | Per-camera frame order; **every** outcome including empty and failed. |
| Tracking → Detection | Never raises; never blocks indefinitely (bounded by the frame timeout). |
| Tracking → Flow 4 | `TrackingOutcome` with immutable `Track` objects, and events on the bus. |

**A detection failure is not a tracking failure.** When the detector could not
look, tracking still ages its tracks — an unmeasured frame is exactly when a track
should coast. Skipping it would freeze every track for the duration of a detector
outage and then resume as though no time had passed.

### 3.3 Failure isolation, tested end to end

A tracking consumer that raises is caught by the Detection Runtime, counted as
`vision_os.runtime.consumer_failures`, and detection continues —
`test_a_broken_tracking_consumer_does_not_stop_detection` proves it against a
fully booted platform.

---

## 4. Architecture Compliance Report

| | Invariant | How Flow 3 holds it |
| --- | --- | --- |
| V1 | Semantic Ceiling | `MotionState` is `stationary/moving/erratic/unknown` — no `loitering`, no `queueing`. An AST guard rejects domain vocabulary in the layer. |
| V2 | Vertical neutrality | No vertical appears. Tracking has no vocabulary for what a region means. |
| V3 | Ports over implementations | P9 with a 22-check kit. Four independent tests prove the platform cannot reach a tracker. |
| V4 | Explainability | Every track carries provenance, association method, cost, runner-up cost, and `break_reason`. |
| V5 | Immutability | `Track`, `TrackUpdate` and every model type are frozen slotted dataclasses. |
| V6 | Single-writer state | One `TrackTable` per camera, owned by one actor. No locks on the hot path. |
| V7 | Perceptual economy | Geometric tracking is the default; appearance is unbound and unshipped. |
| V8 | Blindness is explicit | Coasting is marked `PREDICTED`; `failed` is distinct from empty; refused associations are published. |
| V9 | Degrade never die | `track()` never raises; a failed tracker falls back to `tracker.iou`, which needs no weights or device. |
| V10 | Layered identity | `TrackId` is camera- and epoch-scoped. No `object_id`, no identity field, no cross-camera field. |
| V11 | Normalized time and space | Coordinates normalized; motion integrated over **elapsed seconds**, never frame count. |
| V12 | Pixels stay local | Tracking never touches a frame. It consumes detections only. |
| V13 | Deterministic replay | No wall clock, no `random` import, tie-breaks fixed by index order. Proven by a determinism check comparing two independent runs. |

### 4.1 The platform does not know ByteTrack exists

Four independent assertions, mirroring how Flow 2 proved YOLO's invisibility:

1. `test_no_platform_module_names_a_tracker_vendor` — AST scan of `core`,
   `kernel` and `perception` for vendor identifiers.
2. `test_only_the_composition_root_names_a_concrete_tracker` — only
   `tracking_bootstrap.py` and `adapters/` may name a factory or a tracker id.
3. `test_the_tracking_layer_imports_no_adapter` — nothing under
   `perception/tracking/` imports from `adapters/`.
4. `test_the_manager_holds_a_port_not_a_tracker` — the binding's annotation is
   `TrackerPort`.

Swapping ByteTrack for a transformer tracker is one entry in `TRACKER_FACTORIES`
and one config value.

### 4.2 Flow 1 was modified only through documented extension points

**No Flow 1 module was changed in this flow.** The only Flow 1 files touched are
shared vocabulary, extended additively:

| File | Change |
| --- | --- |
| `core/model/ids.py` | Added `TrackerEpoch`, `LocalTrackId`, `TrackId`. |
| `core/model/__init__.py` | Re-exported the Flow 3 model types. |
| `core/errors.py` | Added the tracking error family. |
| `kernel/config/schema.py` | Added `TrackingSection`; existing sections untouched. |
| `kernel/events/events.py` | Added 10 tracking events. |
| `kernel/metrics/names.py` | Added 18 tracking metric names. |
| `kernel/plugins/manifest.py` | `BINDABLE_PORTS \|= FLOW3_PORTS`. |
| `conformance/flow1_kits.py` | Registered `TRACKER_KIT` in `platform_registry()`. |

`AdmittedFrameConsumer` and the Flow 1 Runtime are **byte-for-byte unchanged**.

### 4.3 Flow 2 was modified only through public contracts

Four changes, all additive except one relocation, and none altering detection
behaviour. See §10.1 for why.

| File | Change |
| --- | --- |
| `core/model/detection.py` | `DetectionOutcome` **moved here** from `engine.py` (re-exported, so every call site still works). A port may not name a type living inside a flow layer. |
| `core/ports/pipeline.py` | Added `DetectionConsumer` alongside `AdmittedFrameConsumer`. |
| `perception/detection/runtime.py` | Added optional `consumer` parameter (default `None`); `_publish` became async; corrected a docstring that contradicted the architecture. |
| `detection_bootstrap.py` | Added `detection_consumer` passthrough. |

`test_the_detection_consumer_is_optional` asserts the default is `None`, and
`test_without_a_tracking_consumer_flow_2_is_unchanged` boots a full platform
without tracking and verifies detection behaves exactly as before.

### 4.4 Explicit scope confirmations

- **No Identity exists.** No `object_id`, no identity field, no identity
  confidence. `test_no_tracking_module_mints_an_object_id` and
  `test_no_tracking_module_uses_identity_confidence` enforce it.
- **No Cross-Camera Tracking exists.** `TrackId` is camera-scoped;
  `no_cross_camera_state` is a conformance check; `IdentityResolverPort` (P11) is
  defined and unbindable.
- **No Re-identification exists.** `EmbeddingPort` (P10) is declared but
  **unbindable and unimplemented** — appearance embeddings are C2 biometric data,
  disabled by default. No embedding adapter ships.
- **No Vision Understanding exists.** `UnderstanderPort` unbindable; no
  `perception/understanding` package.
- **No Observation Builder exists.** `test_tracking_emits_no_observations`.
- **No Vision State exists.** `test_tracking_writes_no_vision_state`.
- **No Business Logic exists.** No alerts, no dwell judgments, no domain
  vocabulary anywhere in the layer.
- **Tracking produces only standardized tracked objects.** The engine's single
  output type is `TrackingOutcome`, carrying `tuple[Track, ...]`.

---

## 5. Tracking Dependency Graph

Dependencies point inward. Adapters may use the toolkit; nothing in the platform
imports an adapter.

```
                       tracking_bootstrap.py
                    (composition root — the only
                     module that names a tracker)
                                │
                ┌───────────────┼───────────────┐
                ▼               ▼               ▼
        TrackingRuntime   TrackingManager   TRACKER_FACTORIES
        (actor per camera) (2 gates + fallback)      │
                │               │                   │
                ▼               ▼                   │
        TrackingEngine ──▶ TrackerBinding            │
        (never raises,      (adapter + caps)         │
         verifies output)         │                  │
                │                 │                  │
                ▼                 ▼                  ▼
         P9 TrackerPort ◀────────────────── adapters/tracking
                                             (iou / sort / bytetrack)
                                                     │
                        ┌────────────────────────────┤
                        ▼                            ▼
              perception/tracking toolkit    P-motion / P-association
              ┌──────────┬──────────┐        LinearPredictor
              ▼          ▼          ▼        StationaryPredictor
        LifecycleMachine  CostMatrix  TrackTable
        (closed table)    Builder     (bounded)
                              │
                              ▼
                    Greedy / Optimal Associator
```

**Acyclic, and the important directions hold:**

- `perception/tracking/` imports nothing from `adapters/` — asserted.
- `adapters/tracking/` imports the toolkit, which is the *allowed* direction: an
  adapter implements a port the platform defines. Sharing the lifecycle machine
  and the bounded table is deliberate — those obligations (T3, T5, T6, T8) are
  owed by *every* tracker, and re-implementing them per adapter is how one
  adapter ends up quietly violating one.
- `core/` imports no flow layer — asserted, with relative sibling imports
  correctly excluded.

---

## 6. Port & Adapter Report

### 6.1 P9 TrackerPort

Interface implemented verbatim from `06_PORTS` §P9. All eight obligations carry
an executable check.

| # | Obligation | Check |
| --- | --- | --- |
| T1 | Strictly sequential per camera; reject violations | `out_of_order_is_rejected` |
| T2 | Non-uniform gaps are normal; integrate over elapsed time | `non_uniform_gaps_are_handled` |
| T3 | Ids unique within `(camera, epoch)`, never reused | `ids_are_unique_within_epoch`, `track_ids_carry_camera_and_epoch` |
| T4 | Association confidence is `ASSOCIATION` and honest | `association_confidence_semantics` |
| T5 | Coasting explicitly marked | `coasting_is_marked_predicted` |
| T6 | Termination carries a `break_reason` | `termination_carries_a_reason` |
| T7 | Per-camera state, fully reset; no cross-camera state | `reset_mints_a_new_epoch`, `no_cross_camera_state`, `update_returns_the_right_camera` |
| T8 | Memory bounded regardless of duration or object count | `memory_is_bounded`, `track_count_stays_within_declared_maximum`, `terminated_tracks_are_released` |

### 6.2 The three shipped adapters

| Adapter | Motion | Association | Occlusion | Role |
| --- | --- | --- | --- | --- |
| `tracker.iou` | none | single-stage greedy | none | **Universal fallback** |
| `tracker.sort` | linear | single-stage optimal | short | Default |
| `tracker.bytetrack` | linear | two-stage optimal | short | Crowded scenes |

`tracker.iou` is not a convenience. `10_RELIABILITY` §7.3 names it one of only
**two** always-available fallbacks in the entire platform: *"pure geometry, no
weights, no device."* It cannot become unavailable, so `fall_back()` cannot itself
fail — which is what makes "degrade, never die" true rather than aspirational. It
passes the same conformance kit as the others.

`tracker.bytetrack` implements the observation the real ByteTrack is built on: a
detection too weak to *start* a track is often strong enough to *continue* one.
`test_bytetrack_continues_a_track_through_a_weak_detection` shows the track
surviving a confidence collapse to 0.25 that fragments the single-stage tracker.

### 6.3 P10 EmbeddingPort — declared, unbound, unshipped

`12_SECURITY` §4.3 classifies appearance embeddings as **C2 · Biometric**:
disabled by default, session-scoped when enabled, policy-gated. Threat #4 in the
same document is *identity linkage* — "any persistent mapping that links sightings
across time or cameras" — which is what a retained embedding gallery is.

So the port is **declared** (making `requires_embeddings` a meaningful capability
and a DeepSORT-class adapter possible later under policy) and deliberately **not
bindable**. No provider ships. A tracker declaring `requires_embeddings: true`
fails to activate with `EmbeddingUnavailableError` rather than degrading silently
to geometry — a silent downgrade would make the capability gap invisible (V8).

Two standing tests enforce this: `test_the_embedding_port_is_not_bindable` and
`test_the_embedding_port_is_never_bindable`, the latter explicitly *not* a
frontier guard — it must still hold when Flow 4 ships.

### 6.4 Two gates before activation

1. **Compatibility** — satisfies `TrackerPort`; embeddings available if required;
   deterministic if deterministic mode is on.
2. **Conformance** — the fast subset (19 of 22 checks) runs against the live
   adapter.

**An adapter failing either gate never becomes reachable.** It is not loaded in a
degraded mode; the binding is simply never installed. A *missing* kit is fatal
too — treating it as "no checks required" is how a gate quietly stops being one.

---

## 7. Conformance Kit Report

### 7.1 Coverage

| Kit | Checks | Fast subset | Sections |
| --- | --- | --- | --- |
| `TRACKER_KIT` v1.0.0 | 22 (+1 determinism) | 19 | shape 5, semantics 10, failure 4, resource 3 |

Obligations covered: **T1–T8** plus adapter obligations **A1** and **A4**.

The determinism check is separate because it needs a *factory*, not an instance:
it compares two independent runs from a clean state, which cannot be done with one
already-used object.

### 7.2 The required verification areas

| Required | Check |
| --- | --- |
| Lifecycle correctness | `termination_carries_a_reason`, `terminated_tracks_are_released` |
| Deterministic behaviour | `determinism` (factory-based) |
| ID stability | `ids_are_unique_within_epoch`, `track_ids_carry_camera_and_epoch` |
| Expiration | `terminated_tracks_are_released` |
| Recovery | `coasting_is_marked_predicted` + `non_uniform_gaps_are_handled` |
| Confidence normalization | `association_confidence_semantics` |
| Metadata correctness | `declares_capabilities`, `capabilities_are_stable` |
| Memory safety | `memory_is_bounded` |
| Resource cleanup | `terminated_tracks_are_released`, `reset_mints_a_new_epoch` |
| Performance expectations | `track_count_stays_within_declared_maximum` |
| Graceful failure | `no_fabricated_tracks`, `degenerate_boxes_are_survived`, `many_objects_are_survived`, `reset_of_unknown_camera_is_safe` |

### 7.3 The kit is proven to fail

A kit that passes everything it is shown is indistinguishable from no kit. Thirteen
broken trackers are built by wrapping a real one and corrupting exactly one
behaviour, so an unrelated failure cannot mask the obligation under test:

anonymous capabilities · drifting capabilities · accepts out-of-order frames ·
reuses ids · presents predictions as measurements · terminates without a reason ·
wrong confidence semantics · reset that does not advance the epoch · leaks across
cameras · rejects empty frames · fabricates tracks · overstates capacity · never
terminates.

Each is asserted to fail **its own** check by name.

### 7.4 What the kit cannot establish

Stated plainly, because a kit that overstates its reach is worse than none.

It **can** prove structural obligations — id uniqueness, epoch advance, coasting
marked, termination reasons, bounded memory, camera isolation, determinism, empty
frames handled. These are properties of output shape and bookkeeping, checkable
against any tracker's own behaviour.

It **cannot** prove tracking *quality* — fragmentation rate, ID-switch rate,
occlusion recovery rate. Those require ground-truth annotated sequences
(`14_TESTING` §7.2), which are deployment data rather than platform code. A kit
claiming to measure them from synthetic input would be measuring its own fixtures.
Recorded as a known limitation (§11.1).

---

## 8. Performance Report

### 8.1 Measured

`tracker.sort`, CPU, single camera, steady state.

| Objects | Measured | Budget (`11_PERFORMANCE` §1.1) |
| --- | --- | --- |
| 1 | **0.140 ms/frame** | ~0.3 ms/frame |
| 5 | 0.514 ms/frame | scales with object count |
| 10 | 1.013 ms/frame | scales with object count |
| 20 | 2.396 ms/frame | scales with object count |
| 40 | 6.713 ms/frame | scales with object count |

The single-object case sits at **47% of budget**. Growth from 1 to 40 objects is
48× for 40× the objects — very close to linear, which is the documented shape
(*"Processing rate × object count"*). Gating by predicted position is what keeps
it there; `test_gating_keeps_association_sub_quadratic` asserts that 4× the
objects costs under 12× the time, where an ungated O(n·m) matrix would cost ~16×.

### 8.2 Budgets and why they are loose

Budget assertions sit an order of magnitude above measured cost. A budget tuned
within 2× of normal fails whenever CI is busy, and a test that cries wolf is one
people learn to re-run rather than read. These catch the class of regression that
turns 100 cameras into 10.

### 8.3 Bounded everywhere

- **Track table** bounded per camera; a crowd degrades by refusing new tracks,
  after evicting the weakest (tentative first, then longest-coasting).
- **History** is a bounded ring of `FrameRef` — an hour-long track holds the same
  memory as a one-second track.
- **Max age** terminates even a healthy track: a track alive for two hours at 5 fps
  is far likelier to be a stuck association than a genuinely persistent object, and
  an unbounded age is how tracking quietly becomes long-term memory.
- `test_object_count_does_not_grow_across_a_long_run` asserts under 15,000 new
  objects across 600 frames — the 30-day soak failure caught in seconds.

### 8.4 Scaling shape

1, 10 and 100 cameras are the same code path at different scales. There is no
cross-camera state, so cameras are fully parallel with zero contention;
`test_a_hundred_cameras_sustain_the_processing_rate` drives 500 tracking calls
(100 cameras × 5 frames) inside 5 s.

---

## 9. Test Report

### 9.1 Totals

```
Plain run:     1,041 passed, 0 skipped        (49.9s)
Coverage run:  1,030 passed, 11 skipped       94% of app/vision_os
                                              (9,427 statements, 578 missed)
Ruff:          all checks passed
Wider Atlas:   2,086 tests collect cleanly; tests/cognitive_kernel 36 passed
```

The 11 tests that skip *only* under coverage are timing budgets; instrumentation
inflates per-call cost by an order of magnitude, so a latency assertion measured
under a trace function tests the profiler, not the platform. They run in full in
every uninstrumented run.

### 9.2 Flow 3 tests by required category

439 tests.

| Category | File | Tests |
| --- | --- | --- |
| Unit — object model | `unit/test_track_model.py` | 59 |
| Unit — lifecycle | `unit/test_lifecycle.py` | 46 |
| Unit — association | `unit/test_association.py` | 45 |
| Unit — motion | `unit/test_motion.py` | 30 |
| Unit — bounded table | `unit/test_table.py` | 33 |
| Adapter — tracker behaviour | `unit/test_tracker_behaviour.py` | 68 |
| Conformance | `unit/test_tracker_conformance.py` | 29 |
| Integration + port + plugin + failure | `integration/test_tracking_pipeline.py` | 55 |
| Integration — end to end | `integration/test_end_to_end.py` | 9 |
| Architecture | `test_tracking_architecture.py` | 38 |
| Performance + concurrency + stress + regression | `test_tracking_performance.py` | 27 |

### 9.3 Coverage by area

| Module | Coverage |
| --- | --- |
| `adapters/tracking/motion.py` | 100% |
| `adapters/tracking/trackers.py` | 100% |
| `tracking_bootstrap.py` | 100% |
| `core/model/track.py` | 99% |
| `perception/tracking/association.py` | 99% |
| `perception/tracking/lifecycle.py` | 99% |
| `conformance/tracker_kit.py` | 99% |
| `perception/tracking/manager.py` | 98% |
| `perception/tracking/table.py` | 98% |
| `adapters/tracking/geometric.py` | 97% |
| `core/ports/tracking.py` | 97% |
| `perception/tracking/engine.py` | 91% |
| `perception/tracking/runtime.py` | 88% |

### 9.4 Quality metrics that matter

`14_TESTING` §7.2 states tracker quality is **not** per-frame accuracy. The four
metrics it names each have tests:

- **Fragmentation** — `test_a_walking_object_keeps_one_id` (all three adapters),
  `test_hit_ratio_stays_high_for_a_clean_sequence`.
- **ID switches** — `test_an_indistinguishable_pair_is_refused_rather_than_guessed`,
  `test_two_separated_objects_get_two_ids`.
- **Occlusion recovery** — `test_a_stationary_object_recovers_after_occlusion`,
  `test_a_lost_track_recovers_within_the_window`.
- **Non-uniform time gaps** — `test_a_steady_object_survives_wildly_uneven_gaps`
  (gaps of 200/1000/100/1500/250/800/200 ms), plus the same as a conformance check.

### 9.5 Frontier tests updated, not weakened

Five pre-existing tests asserted Flow 3 did not exist. Each was moved forward to
police the **Flow 4** frontier, and two new standing guards were added that are
*not* frontier tests: `EmbeddingPort` and `IdentityResolverPort` must remain
unbindable in every future flow.

---

## 10. Architectural Discoveries

### 10.1 Flow 2 described the wrong transport for Detection → Tracking

**Found during the compliance review, before any code was written.**

Flow 2's `DetectionRuntime` docstring asserted: *"Detections are published to the
Event Bus, not handed to a named successor. Flow 3 subscribes."*

The architecture says otherwise in three places:

1. `01_LAYERED` §2.1 classifies `L2 Tracking consumes L2 Detection output` as a
   **sideways within-layer** dependency — a direct call. The Event Bus is listed
   separately, for **upward** notification only.
2. `08_RUNTIME` §5.2 specifies the edge as a bounded queue with **`block`**
   policy: *"ordering matters; dropping here corrupts tracks."*
3. `08_RUNTIME` §3.2 makes per-camera ordering a hard guarantee the tracker
   asserts on.

The Event Bus as built in Flow 1 is **lossy by design** — bounded per-subscriber
capacity with `drop_oldest` and a synthesized `Gap`. Correct for notification,
wrong for pipeline data: routing detections over it would drop them under load and
silently corrupt tracks, the exact failure §5.2 legislates against.

**This was a defect in Flow 2's implementation, not in the architecture.** Flow 2
correctly published `DetectionCompleted`/`DetectionFailed` for *observability*,
then described that bus as the *pipeline transport*. The constitution never said
that. Resolved by widening Flow 2's existing `sink` extension point into a
`DetectionConsumer` protocol and correcting the docstring. No architectural change.

### 10.2 The existing sink could not have served tracking

Flow 2 shipped `DetectionRuntime(sink=...)` — "an optional in-process tap". It was
insufficient in four ways, one of them fatal:

| Gap | Consequence |
| --- | --- |
| Fired only when `outcome.detections` was non-empty | **Fatal.** An empty frame is exactly when tracks coast and terminate. A tracker never seeing empty frames never ages anything. |
| No `FrameRef` on empty frames | Ordering could not be asserted. |
| No failure signal | "Detector failed" and "nothing was there" become indistinguishable — V8 violated. |
| Synchronous, exceptions swallowed | No backpressure; a fault vanished silently. |

The new seam fires on **every** outcome and counts consumer failures.

### 10.3 Tenancy is per-camera, not per-platform

Discovered when the composition root tried to read `tenant_id` from
`PlatformSection` — it is not there. `CameraDeclaration` carries it, because one
node can serve several tenants.

The first implementation took tenancy as a tracker constructor argument. That would
have stamped one tenant across every track on the node, silently breaching the
platform's hard isolation boundary on any multi-tenant deployment. Corrected: a
track inherits tenancy from the detections that formed it. Pinned by
`test_tenancy_comes_from_the_detection_not_the_tracker`.

### 10.4 A default tracker name in the config schema is coupling

`TrackingSection.tracker_id` initially defaulted to `"tracker.sort"`. The
architecture test caught it: a platform module was naming an implementation.

Naming one there makes the config schema the place that decides which tracker is
right, which is the coupling the port structure exists to prevent. The default is
now empty, and enabling tracking without naming a tracker is a validation error.

### 10.5 Two implementation defects, found by tests, pinned as regressions

**Coasting positions did not advance.** Predictions extrapolated by one frame's
elapsed time rather than the cumulative time since the last measurement, so a
coasting track's gate stayed anchored to a stale position and **no moving object
was ever re-acquired after a gap**. Invisible on stationary objects — which is
what made it easy to ship, and why `test_a_coasting_position_advances_with_elapsed_time`
now exists.

**Refused associations were invisible.** A refused track was terminated in the same
frame, so it appeared in neither `active` nor `associations` and nothing was
published — exactly the uncertainty `03_MODULES` §M6 forbids hiding. Fixed by
making `RefusedAssociation` a first-class field on `TrackUpdate`, carrying both
costs, since the refused track is gone by the time anything else could report them.

---

## 11. Known Limitations

### 11.1 The conformance kit cannot measure tracking quality

Fragmentation rate, ID-switch rate and occlusion recovery rate need ground-truth
annotated sequences (`14_TESTING` §7.2). The kit verifies structural obligations
and leaves quality to the golden section, which is defined and wired but empty
because no corpus ships. This is a data problem, not a code problem — and it is
the same gap Flow 2 recorded for letterbox exactness.

Partially compensated: fragmentation and recovery are tested behaviourally in
`test_tracker_behaviour.py` against scripted scenarios. Those prove the tracker
works on the cases written; they cannot report a *rate* on real footage.

### 11.2 Appearance-based tracking is unavailable by design

`EmbeddingPort` is declared and unbindable; no provider ships. This is a
deliberate security posture (`12_SECURITY` §4.3), not an omission — but it does
mean the platform cannot currently re-associate through a long occlusion where an
object's motion has changed. Such a track terminates and a new one is created,
which is correct behaviour for M6: durable identity across that gap is M7's job.

### 11.3 No ground-plane tracking

`supports_ground_plane_tracking` is declared `False` by all three adapters.
Tracking in metric ground coordinates via homography is markedly better under
perspective (`03_MODULES` §M6 extension points) and the port supports it, but it
requires per-camera calibration data that Flow 1 models and no deployment has
supplied. The seam exists; the adapter does not.

### 11.4 Motion prediction is linear only

`LinearPredictor` covers the majority of surveillance motion. A Kalman filter
would handle acceleration and measurement noise better, and is deliberately *not*
built in — its process- and measurement-noise parameters are correct for one
camera geometry and wrong for another, so it belongs behind
`MotionPredictorPort` as an adapter. The seam is proven; the Kalman adapter is
not written.

### 11.5 Crowd behaviour above the declared maximum

Beyond `max_tracks_per_camera`, new detections are refused after one eviction
attempt. This is bounded and deterministic, but in a scene genuinely containing
more objects than the bound, some objects will simply not be tracked. The
architecture's answer for `n > 100` is spatial hashing (`03_MODULES` §M6
performance), which is not implemented — the gating already keeps association
near-linear at the densities the bound permits.

### 11.6 `TrackingSection.queue_capacity` is declared but unused

The `block` policy is currently implemented by awaiting the per-camera lock, which
provides backpressure without an explicit queue. The config field is present for
when a queued implementation is needed (for example when tracking moves to a
separate process); today it has no effect. Flagged rather than removed, because
the architecture specifies the connection as a bounded queue and a future
distributed deployment will need it.

---

## 12. Future Extension Points

| Extension point | Where | For |
| --- | --- | --- |
| `TrackingOutcome` consumer | `TrackingRuntime(sink=...)` | **Flow 4.** The Object Registry attaches here, as tracking attached to detection. |
| `TrackerPort` | `core/ports/tracking.py` | Any tracker. Implement, pass the kit, add one factory entry. |
| `MotionPredictorPort` | `core/ports/tracking.py` | Kalman, learned motion priors, ground-plane tracking. |
| `AssociationPort` | `core/ports/tracking.py` | Learned association, spatial-hash assignment for crowds. |
| `EmbeddingPort` | `core/ports/tracking.py` | Appearance-assisted association — **policy-gated, C2** (§6.3). |
| `IdentityResolverPort` | catalogue | Cross-camera identity, Phase 2. Defined, unused, unbindable. |
| `LifecyclePolicy` | `perception/tracking/lifecycle.py` | Retuning track memory without code change. |
| `AssociationPolicy` | `perception/tracking/association.py` | Reweighting signals; the `confidence_weight` hook is present and defaults to zero. |
| `KitSection.GOLDEN` | `conformance/tracker_kit.py` | Corpus-based quality checks when annotated data exists (§11.1). |
| `TrackingSection` | `kernel/config/schema.py` | New resource and capability knobs, strongly typed. |

**Frontier discipline.** `BINDABLE_PORTS` is now
`FLOW1_PORTS | FLOW2_PORTS | FLOW3_PORTS`. Every later-flow port remains defined
and unbindable, and `test_flow_four_ports_remain_unbindable` fails if that changes
before Flow 4. `EmbeddingPort` and `IdentityResolverPort` are guarded separately
and permanently — they are not frontier ports waiting their turn.

---

## Final Verification

✓ **Flow 1 remains unchanged except through approved extension points.** No Flow 1
module was modified in this flow; only shared vocabulary (ids, errors, config,
events, metrics, the port frontier) was extended additively.

✓ **Flow 2 remains unchanged except through approved extension points.** Four
public-contract changes, all additive except relocating `DetectionOutcome` into
the object model (re-exported, so no call site changed). Detection behaviour with
no consumer attached is byte-for-byte what it was, verified end to end.

✓ **Tracking consumes only standardized Detection objects.** `TrackingRequest`
carries `Sequence[Detection]` and nothing else.

✓ **Tracking does not expose tracker-specific structures.** The output is `Track`
and `TrackUpdate`; no adapter type crosses the port.

✓ **Tracking does not create identities.** No `object_id`, no identity field, no
`IDENTITY` confidence. `TrackId` is camera- and epoch-scoped by construction.

✓ **Tracking does not perform semantic understanding.** No VLM, no attributes, no
captioning.

✓ **Tracking does not perform business reasoning.** `MotionState` is descriptive;
domain vocabulary is rejected by an AST guard.

✓ **Tracking does not build observations.** Asserted.

✓ **Tracking does not modify Vision State directly.** Asserted; tracker state is
volatile and per-camera by design.

✓ **No future roadmap functionality has been implemented.** Cross-camera identity,
persistent biometric identity and federated identity are all absent and
structurally prevented.

---

## Summary

Flow 3 is complete. 15 new source files, 3,858 lines, 439 new tests, 94% coverage,
ruff clean.

The architecture was treated as a constitution. One conflict surfaced during the
mandatory review — and it lay in Flow 2's implementation, not the architecture, so
it was resolved by conforming Flow 2 to what the constitution already said. Four
further discoveries during implementation (§10) each corrected the code to match
the architecture rather than the reverse.

Tracking maintains temporal continuity within one camera and stops there. It has
no identity, no memory beyond its declared bounds, no vocabulary for meaning, and
no knowledge of which tracker is bound.
