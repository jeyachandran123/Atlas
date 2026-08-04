# Implementation Flow 5 — M8 Crop Manager

**Status:** complete. `1,908` Vision OS tests pass; `352` are new.

> **Single responsibility:** *Choose what to look at closely, and produce a crop
> worth looking at.*

M8 is the platform's attention mechanism and the primary enforcement point of
invariant V7. Without it, understanding cost is `cameras × fps × objects`. With
it, cost is `demands × changes`. `03_MODULES` §M8 is unusually direct about what
that means:

> *"That reduction is not an optimization; it is the architecture."*

---

## 1. Architecture Compliance Review

Performed **before any code was written** and recorded in full at
[`FLOW_5_COMPLIANCE_REVIEW.md`](FLOW_5_COMPLIANCE_REVIEW.md). It answers the
thirteen required questions and closes with: *"No architectural change is
requested. Implementation may proceed."*

Three ambiguities were found. Each was documented and resolved **against the
architecture**, not by inference:

| # | Ambiguity | Resolution |
|---|---|---|
| 12.1 | `QualityGrades` (Flow 2) has no `overall`, but `02_VOM` §10.8 specifies one and says quality is computed *in the Crop Manager* | Added `overall: QualityLevel \| None = None` as an **optional** field. Additive to Flow 2: every existing construction still type-checks and still means what it meant. |
| 12.2 | The brief says *"never introduce cross-camera synchronization"*; §M8 says *"the budget is shared across cameras"* | Resolved in the Constitution's favour. Trigger state is per-camera single-writer; the budget is a shared **counter** with a nanosecond critical section — M3's existing precedent — and no camera ever waits on another. Proved by `test_cropping_determinism.py::TestSharedBudgetUnderContention::test_no_thread_starves`. |
| 12.3 | The demand registry is listed both as an M8 *dependency* and as M8's *API* | M8 owns it (`register_demand`/`revoke_demand` are in §M8's Public API). The Observation API forwards to it in Flow 8. This is the only reading under which §M8's API, §M8's dependency list and `09_API_CONTRACTS` §4.1 all hold at once. |

**No architectural document was modified.** The architecture remains frozen.

---

## 2. Implementation Report

### What was built

**16 files, 5,649 lines of implementation.**

| File | Lines | Role |
|---|---:|---|
| `core/model/crop.py` | 482 | The Crop object (`02_VOM` §10.7), `CropTransform`, `GateResult`, `CropRequest`, `Skipped`, `EvaluationResult`, `PrivacyClass`, `RetentionMode`, 9 `TriggerReason`s, 7 `SkipReason`s, 7 `GateRejection`s |
| `core/model/demand.py` | 269 | `Demand`, `DemandScope`, `SubjectFilter`, `DemandBudget`, `DemandAcknowledgement`, `DemandState`, 7-state `DemandStatus` |
| `core/ports/cropping.py` | 323 | **P12** `TriggerPolicyPort` (G1–G6), **P13** `QualityEstimatorPort` (Q1–Q5), **P14** `CropStrategyPort` (C1–C5), `CropExtractorPort` |
| `perception/cropping/engine.py` | 925 | `CropManager` — M8's public API, verbatim |
| `perception/cropping/runtime.py` | 499 | `CropRuntime` — the `RegistryConsumer` seam, one actor per camera |
| `perception/cropping/demands.py` | 419 | `DemandRegistry` + the closed `09_API_CONTRACTS` §4.4 lifecycle |
| `perception/cropping/budget.py` | 377 | `UnderstandingBudget`, `CropDeduplicationCache`, `PriorityQueue` |
| `perception/cropping/state.py` | 238 | Per-camera trigger state, bounded; `GateRejectionWindow` |
| `perception/cropping/gate.py` | 150 | `QualityGate` — grades to verdict, with an attributed reason |
| `perception/cropping/__init__.py` | 66 | Package surface |
| `adapters/cropping/quality.py` | 365 | `HeuristicQualityEstimator` (P13), `AlwaysUsableEstimator` |
| `adapters/cropping/strategies.py` | 344 | `TightCropStrategy`, `PaddedCropStrategy` (P14), `ReferenceCropExtractor` |
| `adapters/cropping/triggers.py` | 329 | `DefaultTriggerPolicy` (P12), `ExplicitRequestPolicy` |
| `adapters/cropping/__init__.py` | 69 | Closed factory tables |
| `conformance/cropping_kits.py` | 493 | Executable kits for P12, P13, P14 |
| `cropping_bootstrap.py` | 301 | Composition root — the only module that selects an adapter |

Plus additive edits: `core/model/detection.py` (`QualityLevel`, `QualityGrades.overall`), `core/model/ids.py` (`CropId`, `DemandId`, `SubscriberId`), `core/errors.py` (6 crop errors), `core/ports/pipeline.py` (`RegistryConsumer`), `kernel/events/events.py` (3 events), `kernel/metrics/names.py` (21 metrics), `kernel/config/schema.py` + `manager.py` (`CroppingSection`), `kernel/plugins/manifest.py` (`FLOW5_PORTS`).

### The public API, verbatim from §M8

```text
evaluate(object_ids, frame_ref)      → CropRequest[] | Skipped[(object_id, reason)]
extract(crop_request)                → Crop !GateRejected !FrameUnavailable
register_demand(demand)              → DemandId
revoke_demand(demand_id)             → void
budget_status()                      → BudgetStatus
subscribe()                          ⇢ BudgetExhausted | GateRejectionSpike
```

All six implemented. `evaluate` **never raises** — an attention failure may not
stop the registry, which may not stop tracking, which may not stop detection,
which may not stop acquisition (V9). `extract` **does** raise, because its two
documented failures are answers the caller must handle: swallowing a gate
rejection would turn *"we refused"* into *"there was nothing there"*.

### All nine trigger reasons, all seven skip reasons

Every documented value is reachable and reachable **for its own cause**.
`test_triggers.py::test_all_nine_reasons_are_reachable` reads the policy's source
and fails if any reason can never be emitted — a reason the platform cannot
produce is a reason a consumer will never see.

The policy evaluates in **cost order**, cheapest-and-most-certain first, so an
object that obviously needs analysis is decided without computing an appearance
delta:

```
missing → gate-recovered → stale → lifecycle/region → appearance → low-confidence → cadence → fresh
```

`QUALITY_IMPROVED` is checked *before* staleness deliberately: an object that has
just become gradable should not wait out a freshness window it was never able to
satisfy.

---

## 3. Data Ownership Chain Report

The chain from pixels to evidence, with **one owner per link**:

```
Frame Buffer (M4)      owns pixels               ─┐ lends via lease
                                                   │
Detection (M5)         owns detections            │  no identity
                                                   │
Tracking (M6)          owns TrackId               │  fragile, camera-local
                                                   │
Object Registry (M7)   owns ObjectId              │  THE ONLY WRITER of objects
                       owns attribute *storage*   │
                       owns region membership     │
                                                   │
Crop Manager (M8)      owns trigger state         ◄┘  reads M7, leases M4
                       owns budget accounting
                       owns the dedup cache
                       owns crop lifecycle
                       owns CropId
                                                   │ produces
Understanding (M9)     owns attribute *production* ▼  Flow 6
```

**What M8 owns**, from §M8 State Ownership verbatim: per-object trigger state
(last analysis time per attribute, last appearance signature), budget accounting,
crop deduplication cache, priority queues — *"ephemeral and node-local; rebuilt
from registry state after restart"*.

**What M8 does not own**, and how each absence is enforced:

| Not owned | Owner | Enforcement |
|---|---|---|
| Vision Objects | M7 | `test_the_crop_manager_never_writes_an_object` — AST scan; constructing `VisualObject`, `Attribute` or `ObjectId` anywhere in `cropping/` fails the build |
| Attributes | M9 (Flow 6) | `test_no_inference_vocabulary` — no `classify`, `caption`, `ocr`, `embed`, `infer`, `predict`, `vlm`, `prompt` identifier may exist |
| Vision State | M13 (Flow 7) | `test_no_durable_store_is_held` + `test_nothing_in_the_crop_path_touches_the_filesystem` — no `pathlib`, `os`, `sqlite3`, `pickle` import is permitted |
| Region *meaning* | the consumer (V1) | `test_no_region_semantics_reach_the_crop_path`; `TriggerCandidate` carries `region_ids`, never a label |
| Identity | nobody, in Phase 1 | `test_no_identity_vocabulary`; P10/P11 unbindable and unreachable |

**The single-writer rule holds transitively.** M8 reads `VisualObject` snapshots
and writes nothing back. `apply_attribute` — M7's write path for attributes — is
called by M9 in Flow 6, never by M8. That is why M8 can be removed from a
deployment without changing a single object the registry produces, which
`test_the_registry_still_produces_objects_with_cropping_attached` verifies
end to end.

---

## 4. Crop Lifecycle Report

A crop's life, from candidate to expiry. **Every arrow is observable.**

```
 VisualObject (from M7)
        │
        │  evaluate()            ── control plane, no pixels leased
        ▼
 TriggerCandidate ─────────────► TriggerDecision
        │                          │        │
        │                     fires│        │skips
        │                          ▼        ▼
        │                    CropRequest   Skipped(reason)   ◄── 7 reasons, always attributed
        │                          │
        │                    priority order
        │                          │
        │                     budget spend ──── refused ──► Skipped(BUDGET_EXHAUSTED)
        │                          │                         + BudgetExhausted event
        ▼                          ▼
                            extract()  ── ONE lease per frame, not per request
                                 │
                            pre-gate on geometry ── rejected ──► GateRejectedError
                                 │                               + budget refund
                            extract pixels ─── fault ──────────► CropExtractionError
                                 │                               + budget refund
                            grade with pixels
                                 │
                            post-gate ──────── rejected ──────► GateRejectedError
                                 │                               + budget refund
                                 │                               + rejection counted
                            content hash  ── CropId = sha256(pixels)
                                 │
                            dedup cache put (tenant-keyed)
                                 ▼
                              Crop  ─── retention: EPHEMERAL | EVIDENCE(ttl) | NEVER_PERSIST
                                 │
                                 ├── without_pixels() ──► control-plane reference (V12)
                                 └── expires_at() ─────► evidence store may discard
```

**Five properties this lifecycle guarantees:**

1. **Exactly-once accounting.** Every candidate ends in `requests` or `skipped`,
   never both and never neither. This survives the extraction stage: a request
   that is admitted and then gate-rejected *moves* to the skip column rather than
   appearing twice. That defect was caught by
   `test_crops_and_skips_both_reach_the_sink` during development and fixed in
   `runtime._publish` — see §11.
2. **A rejection always names its axis.** `GateResult.__post_init__` refuses to
   construct a rejection without a reason, so *"the VLM never answers for
   far-away people"* is a statistic rather than a mystery.
3. **A rejected crop costs nothing.** Budget is refunded on every rejection and
   every extraction fault. Without it, a run of failures would exhaust the budget
   having bought nothing and the platform would stop looking at what it *could*
   have answered.
4. **Trigger state is ephemeral.** No store, no snapshot, no reload. A restart
   costs one round of `FIRST_SIGHT` — bounded, predictable and conservative.
5. **Retention is decided here, executed elsewhere.** M8 stamps the mode and TTL;
   persisting imagery is a different module's job, which is why P22
   `EvidenceStorePort` remains unbindable.

---

## 5. Evidence Provenance Report

`02_VOM` §10.7's whole argument is that a crop without provenance is an image,
and an image is not evidence. Every field below exists because omitting it
produces a failure nobody detects.

| Field | What it defends | Failure if absent |
|---|---|---|
| `crop_id` | Identity | Two runs over the same footage produce different evidence. Content addressing makes the same pixels one crop — free dedup, free cache keys, free integrity checking, and a reference that survives storage migration. |
| `camera_id` + `source_frame` | Traceability | A claim that cannot be traced to the instant it was made from. Enforced: `Crop.__post_init__` refuses a crop whose frame belongs to another camera. |
| `object_id` | Subject | An attribute with nothing to attach to. |
| `source_box` + `padding_applied` | Comparability | An attribute computed on a tight crop and on a padded one are *different measurements*. |
| `transform` | Fairness | `02_VOM` §10.7: *"two models evaluated on differently-letterboxed crops are not comparable, and without this field nobody finds out."* |
| `quality` | Interpretability | A confident answer from 14 blurry pixels reads exactly like a confident answer from a good crop. |
| `gate_result` | Explicability | Rejections become countable and attributable rather than an unexplained absence. |
| `t_capture` | Truth about the world | Extraction time would make a dwell a measurement of the platform rather than of the world (V11). |
| `trigger_reason` | Why this exists | `02_VOM` §10.9 requires evidence to record *why this was computed at all*. Six months later, this is the difference between explaining a result and guessing. |
| `provenance` | Reproducibility | Without `config_revision`, no result is reproducible (V4). |
| `privacy_class` | Safe handling | A class inferred downstream is a class someone forgets, and imagery lands in an unclassified path. |

### The transform record is measured, not assumed

`ReferenceCropExtractor.extract` returns `(bytes, CropTransform)` — the transform
describes **what it actually did**, not what was requested. A crop whose record
and reality disagree is worse than one with no record, because it invites a
comparison that looks valid and is not.

`CropTransform.drawn_width` / `drawn_height` were added for exactly this reason.
Letterbox padding splits by integer division, so an odd leftover pixel goes to one
side; reconstructing the drawn size as `output − 2 × pad` is then wrong by a
pixel, and `aspect_preserved` reported a distortion that never happened. Recording
the drawn area directly fixed it. `aspect_preserved` also tolerates **one pixel**
rather than floating-point epsilon: preserving a 32×384 aspect inside 64×64 means
drawing 5×64 rather than the exact 5.33×64, and an epsilon comparison would call
every real letterbox squashed.

### Evidence chain, end to end

```
FrameRef(camera, epoch, seq) ──► Crop.source_frame
Frame.t_capture              ──► Crop.t_capture            (world time, V11)
VisualObject.object_id       ──► Crop.object_id            (M7's durable handle)
VisualObject.tenant_id       ──► Crop.tenant_id            (per-object, not global)
TriggerDecision.reason       ──► Crop.trigger_reason       (why we looked)
CropPlan.padding_applied     ──► Crop.padding_applied      (what was requested)
extractor measurement        ──► Crop.transform            (what actually happened)
QualityEstimatorPort output  ──► Crop.quality              (how good the input was)
QualityGate verdict          ──► Crop.gate_result          (whether it was defensible)
sha256(normalized pixels)    ──► Crop.crop_id              (what it is)
```

Verified end to end by `test_a_crop_is_fully_traceable`.

---

## 6. Engine Interaction Report

```
                       ┌────────────────────────────────────────┐
                       │  M7 Object Registry (Flow 4)           │
                       │  RegistryUpdate(objects, frame_ref)    │
                       └──────────────────┬─────────────────────┘
                                          │ RegistryConsumer   ← the Flow 5 seam
                                          ▼
        ┌──────────────────────────────────────────────────────────┐
        │  CropRuntime          one asyncio.Lock per camera        │
        │   • never raises  • one lease per frame  • demand expiry │
        └──────────────────┬───────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────────────────────────┐
        │  CropManager                                             │
        │                                                          │
        │  DemandRegistry ──► required_attributes(camera,class,rgn)│
        │        │                        │                        │
        │        │                        ▼                        │
        │        │              P12 TriggerPolicyPort              │
        │        │                        │                        │
        │        │              TriggerDecision[]                  │
        │        │                        │                        │
        │        │              PriorityQueue (opaque class→rank)  │
        │        │                        │                        │
        │        └──────────────► UnderstandingBudget (shared)     │
        │                                 │                        │
        │                         CropRequest[] / Skipped[]        │
        │                                 │                        │
        │             ┌───────────────────┴──────────────┐         │
        │             ▼                                  ▼         │
        │   P13 QualityEstimatorPort            P14 CropStrategyPort│
        │             │                                  │         │
        │        QualityGate                     CropExtractorPort │
        │             │                                  │         │
        │             └──────────────┬───────────────────┘         │
        │                            ▼                             │
        │                  CropDeduplicationCache (tenant-keyed)   │
        │                            ▼                             │
        │                          Crop                            │
        └──────────────────────────────────────────────────────────┘
                                    │
                                    ▼  Flow 6
                          M9 Vision Understanding
```

**Why the split between `evaluate` and `extract` is load-bearing.** `evaluate` is
a control-plane decision about metadata and leases nothing. `extract` is the only
thing that touches pixels. That is what lets one node evaluate thousands of
candidates a second while leasing pixels for a handful — and it is why
`test_no_lease_is_taken_when_nothing_fires` asserts that an undemanded population
costs zero pixel access.

**Why the extractor is a separate port from the strategy.** The *decision* is
cheap and per-object; the *work* is expensive and batchable. A deployment that
moves extraction to a GPU replaces `CropExtractorPort` and nothing else.

---

## 7. Architecture Compliance Report

| Requirement | Where | Enforced by |
|---|---|---|
| Produce canonical visual evidence | `engine.extract` | `test_a_crop_is_fully_traceable` |
| One crop format; no model-specific preprocessing | `adapters/cropping/strategies.py` | `test_no_model_name_appears_in_the_crop_path`, `test_no_normalization_vocabulary` |
| Evaluate triggers against demands and budget | `engine._evaluate`, `_admit` | `test_crop_manager.py` (42 tests) |
| Quality gating with a recorded reason | `gate.py` | `GateResult.__post_init__`; 15 gate tests |
| Content-address and deduplicate | `engine.content_hash`, `budget.CropDeduplicationCache` | `test_the_crop_id_is_a_content_hash`, `test_the_cache_is_tenant_scoped` |
| Hard budget ceiling | `budget.UnderstandingBudget` | `test_the_ceiling_holds_across_threads` |
| Prioritize when demand exceeds budget | `budget.PriorityQueue` | `test_shedding_follows_priority` |
| Skip reason for **every** candidate | `EvaluationResult` | `test_every_candidate_appears_exactly_once` |
| V1 Semantic Ceiling | throughout | `test_no_region_semantics_reach_the_crop_path`, `test_priority_is_an_opaque_string` |
| V2 Vertical neutrality | `CroppingSection` | `test_the_config_section_has_no_business_slot` |
| V3 Ports over implementations | P12/P13/P14 + kits | `test_only_the_composition_root_names_a_concrete_adapter`, 18 conformance tests |
| V4 Explainability | `trigger_reason`, `gate_result`, `provenance` | §5 above |
| V5 Immutability | frozen slotted `Crop` | construction-time validation |
| V6 Single-writer state | per-camera partition | `test_no_cross_camera_synchronization_exists` |
| V7 Perceptual economy | the entire module | `test_cropping_performance.py` (13 tests) |
| V8 Blindness explicit | 7 skip reasons, never silence | `test_every_candidate_appears_exactly_once` |
| V9 Degrade never die | `evaluate` firewall | `test_evaluate_never_raises`, `test_the_seam_never_raises` |
| V11 Normalized time | `t_capture` from the frame | `test_capture_time_is_the_frames_not_the_extractions` |
| V12 Pixels stay local | `Crop.without_pixels()` | `test_a_crop_reference_carries_no_pixels`, `test_no_crop_event_type_exists` |
| V13 Deterministic replay | pure policy, pure gate, pure extractor | `test_cropping_determinism.py` (18 tests) |

### Prohibited behaviours — each structurally impossible

The brief listed what M8 must never do. Each is enforced by a test that reads the
source tree, not by convention:

> *no detection, no tracking, no identity, no attribute extraction, no OCR, no
> captioning, no VLM inference, no semantic understanding, no observation
> generation, no business reasoning, no alerts, no prediction, no learning, no
> cross-camera identity.*

`test_cropping_architecture.py::TestM8UnderstandsNothing` covers the inference,
identity and observation vocabularies (3 AST scans over 10 modules).
`TestNoModelSpecificPreprocessing` covers the model-name and normalization
prohibitions. `TestM8OwnsNoState` covers state. `test_cropping_security.py`
covers biometrics and identity persistence.

---

## 8. Dependency Graph

```
core/model/crop.py ──► detection.py (QualityGrades), ids, provenance, space, timebase
core/model/demand.py ──► ids, timebase
core/ports/cropping.py ──► model/{crop, detection, ids, space, timebase}

perception/cropping/gate.py     ──► model/{crop, detection}
perception/cropping/state.py    ──► model/{crop, ids, timebase}
perception/cropping/budget.py   ──► model/{ids, timebase}
perception/cropping/demands.py  ──► errors, model/{demand, ids, timebase}
perception/cropping/engine.py   ──► the four above + ports/{clock, cropping}
                                     + kernel/{config, events, metrics}
perception/cropping/runtime.py  ──► engine + registry/engine (RegistryUpdate)
                                     + kernel/{config, health, metrics}

adapters/cropping/* ──► core only.  No adapter imports another adapter.

cropping_bootstrap.py ──► adapters + conformance + perception + registry_bootstrap
```

**Direction, verified mechanically:**

* `perception/cropping/` imports **no adapter** — `test_cropping_imports_no_adapter`.
* `perception/registry/` imports **nothing from cropping** — the dependency runs
  one way and M7 holds a callable it never learns the type of.
* `kernel/` imports nothing from cropping.
* `acquisition/` and `perception/detection/` import nothing from cropping.
* `core/` remains stdlib-only. The engine's single stdlib import beyond the usual
  is `hashlib`, for content addressing.

The one import that looks like a violation and is not:
`perception/cropping/` imports `core.model.detection` for `QualityGrades` and
`QualityLevel`. That is the **shared model**, not the detection module — quality
is platform vocabulary the whole pipeline shares. The guard is scoped to
`perception.detection` precisely so it stays meaningful.

---

## 9. Runtime Integration Report

`08_RUNTIME` places M8 in the actor table. §M8's Thread Safety section splits its
concurrency in two, and `CropRuntime` makes both real:

**Per-camera single-writer for trigger state.** One `asyncio.Lock` per camera, so
two updates for one camera can never interleave and two cameras never contend at
all. Matches M7's partitioning exactly. `TriggerStateStore` deliberately holds
**no lock** — a lock there would suggest cross-camera access is expected, and
`test_no_cross_camera_synchronization_exists` asserts its absence.

**The budget is shared across cameras**, deliberately, because understanding cost
is a property of the node's GPU rather than of any camera. A per-camera cap
cannot stop 100 cameras each staying under their own limit while collectively
exhausting the device. The critical section is a counter increment held for
nanoseconds — M3's existing trade, for M3's reason. Verified under 8 threads:
3,600 calls granted against a 3,600 ceiling, exactly, with no thread starved.

**Lease discipline.** One lease per frame, not one per request. A lease is a
buffer-slot reservation; taking N of them for N objects on the same frame
multiplies pool pressure for no benefit. `evaluate` holds no lease at all — it
peeks at frame metadata and releases immediately.

**The scheduled work M8 owns:** demand expiry. A demand with a TTL must expire
even at a camera that has gone quiet, or a consumer's contract outlives the
window it was acknowledged for.

**The seam.** `CropRuntime.on_registered` implements `RegistryConsumer`, attached
at `RegistryRuntime(sink=…)` — the extension point the Flow 4 report declared.
Flow 4 remains unaware of the Crop Manager: it holds a callable and never learns
what implements it. The bootstrap schedules rather than awaits the hand-off, so
attention latency never sits on the critical path of the layer beneath it.

---

## 10. Performance Report

§M8's worked cost model, reproduced as executable tests rather than asserted from
a document.

| Lever | Architecture's claim | How it is verified |
|---|---|---|
| Demand-driven only | *"often a 10× reduction on its own"* | `test_no_demand_costs_nothing` — 100 objects, zero requests, 100 attributed skips |
| Change-based triggering | *"another 5–20×"* | `test_a_stationary_analysed_object_stops_costing` — 29 frames after the first look, **zero** re-analyses |
| Measured reduction factor | — | `test_the_reduction_factor_is_measurable` — 400 naive candidate-frames reduced by ≥4× |
| Quality gating | avoids paying for unanswerable crops | 15 gate tests; scale is checked first because it is *"the strongest single predictor"* |
| Deduplication | identical crops resolve from cache | `test_identical_pixels_hit_the_cache` |
| Resolution normalization | *"never larger, which is pure waste"* | `test_extraction_cost_is_independent_of_frame_size` — a 16× larger source frame produces an identically-sized crop |

**Structural cost guards**, not wall-clock budgets. A timing assertion on a shared
machine measures the machine; these measure the design:

* `test_evaluation_is_linear_in_candidates` — 4× the candidates must not take 20×
  the time. Catches an accidental O(n²) scan.
* `test_the_demand_lookup_does_not_scale_with_population` — 50 objects against 20
  demands, order-of-magnitude bound. Catches a registry scanned per object *per
  demand*.

**Bounded resources**, all three verified against 10,000–20,000 insertions:
trigger state (LRU per camera), the dedup cache (LRU, tenant-keyed), and the gate
rejection window (rolling). §M8 names cache growth as a failure mode; an
unbounded dedup cache is a memory leak that looks like a hit-rate improvement.

---

## 11. Test Report

**352 new tests**, all passing. Total Vision OS suite: **1,908 passing**.

| File | Tests | Category |
|---|---:|---|
| `unit/test_triggers.py` | 28 | All 9 trigger reasons, skip reasons, decision structure |
| `unit/test_quality_and_gate.py` | 38 | Grades, folding, gate verdicts, thresholds |
| `unit/test_extraction.py` | 22 | Strategies, extraction, transform-record integrity |
| `unit/test_budget.py` | 30 | Ceiling, refunds, dedup cache, priority queue |
| `unit/test_demands.py` | 27 | Registration, honest freshness, closed lifecycle |
| `unit/test_crop_model.py` | 21 | Traceability, retention, the V12 boundary |
| `unit/test_crop_manager.py` | 42 | The accounting identity, shedding, alarms |
| `unit/test_crop_runtime.py` | 23 | Seam, firewall, lease discipline, failure distinctions |
| `unit/test_conformance.py` | 18 | Kits pass shipped adapters, **fail broken ones** |
| `integration/test_end_to_end.py` | 21 | Flows 1–5, real modules, no mocks at a boundary |
| `test_cropping_architecture.py` | 29 | Ceiling, layering, ownership, flow scope |
| `test_cropping_security.py` | 22 | Classification, tenancy, retention, no biometrics |
| `test_cropping_determinism.py` | 18 | Replay, shared-budget contention, partitioning |
| `test_cropping_performance.py` | 13 | Reduction factors, bounded resources |

### Coverage of the Flow 5 surface

| Module | Coverage |
|---|---:|
| `core/model/crop.py` | 99% |
| `core/model/demand.py` | 92% |
| `core/ports/cropping.py` | 97% |
| `perception/cropping/budget.py` | 98% |
| `perception/cropping/demands.py` | 98% |
| `perception/cropping/engine.py` | 97% |
| `perception/cropping/gate.py` | 94% |
| `perception/cropping/runtime.py` | 96% |
| `perception/cropping/state.py` | 94% |
| `adapters/cropping/quality.py` | 93% |
| `adapters/cropping/strategies.py` | 97% |
| `adapters/cropping/triggers.py` | 94% |
| `conformance/cropping_kits.py` | 99% |
| `cropping_bootstrap.py` | 86% |

### The conformance kits are tested against broken adapters

A kit that only ever passes proves nothing. Every kit runs twice: against the
shipped adapter, which must pass, and against an adapter built to violate one
obligation, which must fail **with that obligation named**. Ten deliberately
broken adapters ship in the test suite: `_DroppingPolicy` (G1),
`_ReorderingPolicy` (G3), `_NonDeterministicPolicy` (G3), `_EagerPolicy` (G4),
`_PriorityInterpretingPolicy` (G5), `_ZeroingEstimator` (Q2),
`_UngradedEstimator` (Q3), `_OptimisticEstimator` (Q5), `_EscapingStrategy` (C1),
`_ScalingStrategy` (C2).

---

## 12. Architectural Discoveries

Six defects were found during implementation. Each was found by a test, and four
of them were found by the platform's *own invariants* rather than by an assertion
I wrote for the occasion.

**1. `demands or DemandRegistry()` silently discarded the injected registry.**
`DemandRegistry` defines `__len__`, so an *empty* one is falsy. Every caller that
injected a registry before its first demand got a fresh one instead — and the
caller's capability view with it, which meant every demand was rejected as
naming an unregistered attribute. Fixed with explicit `is None` checks. This is
the classic Python truthiness trap, and it was invisible until 38 tests failed at
once with an error message about attribute registration.

**2. The budget granted nothing, forever, at low rates.** A ceiling of 30
calls/hour over a 60-second window earns 0.5 calls per window. The original
rolling-window implementation discarded the remainder each window, so an integer
call never became affordable and the platform would have gone permanently blind
on a configuration that reads as perfectly reasonable. Replaced with a token
bucket whose credit carries across windows, capped at one window's allowance so a
quiet night cannot buy an unbounded morning burst.

**3. A gate-rejected request appeared in both `requests` and `skipped`.** The
runtime republished the original request list alongside the new skips, so a
candidate that was admitted and then rejected was counted twice — breaking the
exactly-once identity that makes V8 checkable at all. `_extract_all` now returns
the *fulfilled* requests, and a rejected one moves rather than duplicating.

**4. `aspect_preserved` reported distortions that never happened.** Letterbox
padding splits by integer division; reconstructing the drawn size as
`output − 2 × pad` is wrong by a pixel when the leftover is odd. Fixed by
recording `drawn_width`/`drawn_height` on the transform — measuring rather than
inferring — and by tolerating one pixel rather than floating-point epsilon.

**5. Clamping a fully out-of-frame box raised from geometry code.**
`Box.clamped_to_unit()` refuses to construct a zero-area box, which is exactly
what an object walking out of shot produces. A strategy that raised would produce
the same outcome as a gate rejection *with no statistic attached*. Fixed with
`_clamped`, which guarantees a non-degenerate result so the gate can reject it
with `DEGENERATE_GEOMETRY` — a counted outcome rather than an exception.

**6. A pre-existing latent defect in `Event.payload()`.** Several event types
narrow `detail` to a `str`, shadowing the base class's `dict`. `payload()` splats
it with `**self.detail`, which raises `TypeError: 'str' object is not a mapping`.
The defect predates Flow 5 — `ObjectPopulationCapped` and `TrackingWarning` carry
it — and would drop exactly those event types at the transport, which is the
hardest kind of observability gap to notice. Repaired in the base class rather
than propagated: `payload()` now handles both shapes.

### What went right, and why

Three of the six defects were caught by construction-time validation in the
platform's own model types — `GateResult` refusing an unattributed rejection,
`TriggerDecision` refusing to carry neither reason nor skip, `Box` refusing zero
area. That is the third flow in a row where the invariants have been load-bearing
rather than decorative.

---

## 13. Known Limitations

Stated plainly rather than papered over.

**The conformance kits cannot measure judgment.** No check can tell whether a
trigger policy makes *good* decisions, or whether an estimator's blur score
correlates with real sharpness. That needs labelled ground truth the platform
does not have. The kits verify contracts — the structural properties whose
violation is silent — and stop there. This is stated in the kit module's own
docstring so nobody mistakes a green kit for a quality guarantee.

**Occlusion is approximated by crowding.** The heuristic estimator reports the
same number for both, because separating them needs a segmentation mask no bound
model produces. Recorded as the same value twice rather than as a second invented
measurement.

**Crowding uses the largest single overlap, not a true union.** That keeps the
measure O(n) and bounded, and it *understates* crowding — which fails in the
direction of still trying rather than rejecting a usable crop.

**The reference extractor is nearest-neighbour and pure Python.** Correct,
dependency-free and slow. It defines what a crop *is* so a fast implementation
can be checked against it. A production node replaces `CropExtractorPort` and
nothing else changes.

**`ExplicitRequestPolicy` has no rate limiter.** §M8 calls the on-demand path
*"bounded, rate-limited"*. It is bounded — one request, one analysis, consumed on
use — but the *rate* limit belongs with the API that accepts the request, which
arrives in Flow 8. The policy composes with normal triggering rather than
bypassing it, so budget and gating still apply.

**Capability is supplied, not discovered.** `CapabilityView` is injected and
**empty by default**, which means every demand today is admitted and immediately
marked `UNSATISFIABLE` with `NO_CAPABLE_MODEL`. That is the honest state until
Flow 6 binds an understander, and it is better than leaving a consumer waiting
forever — but it does mean the shipping default produces no crops until Flow 6.
`test_with_no_understander_every_demand_is_unsatisfiable` pins this behaviour so
it cannot drift silently.

**One change was made to Flow 4.** `RegistryUpdate.frame_ref` was widened from
`str` to `FrameRef`. M8 attaches to this update as its declared extension point
and must lease pixels for exactly that frame; reconstructing a `FrameRef` by
parsing its own `__str__` would be a silent correctness hazard the type system is
right there to prevent. Anything wanting the old text calls `str(...)`. All Flow 4
tests pass unchanged.

**The wider Atlas suite has 82 pre-existing failures** in `tests/unit`,
`tests/integration` and `tests/vision` — memory flow, review agents, workspace.
None reference `vision_os` or cropping, and none were introduced by this flow.

---

## 14. Future Extension Points

| Extension point | Where | For |
|---|---|---|
| `CropConsumer` | `perception/cropping/runtime.py` (`sink=…`) | **Flow 6.** Vision Understanding attaches here, as the Crop Manager attached to the registry. |
| `TriggerPolicyPort` (P12) | `core/ports/cropping.py` | Novelty-driven, uncertainty-driven, learned-salience policies. §M8 names all three. |
| `QualityEstimatorPort` (P13) | `core/ports/cropping.py` | Learned quality predictors, replacing today's heuristics. |
| `CropStrategyPort` (P14) | `core/ports/cropping.py` | Multi-scale, part-focused (head region for headwear, torso for hi-vis), temporal stacks, panoramic composites. |
| `CropExtractorPort` | `core/ports/cropping.py` | OpenCV, CUDA, NVJPEG. Separated from the strategy because the *work* is batchable and the *decision* is not. |
| Appearance-change detectors | the `appearance_of` callable | Histogram, embedding distance, learned change detection. Today the platform passes a scalar delta and stays biometric-free. |
| Budget policies | `perception/cropping/budget.py` | Cost-aware (different models cost differently), deadline-aware, value-of-information ranking. |
| `EvidenceStorePort` (P22) | `core/ports/` | Persisting imagery. M8 decides retention *policy* and stamps it; it never writes. |
| `CroppingSection` | `kernel/config/schema.py` | New resource and quality knobs, strongly typed and validated. |

**Frontier discipline.** `BINDABLE_PORTS` is now
`FLOW1 | FLOW2 | FLOW3 | FLOW4 | FLOW5`. Every later-flow port stays defined and
unbindable, and `test_flow_six_and_later_ports_remain_unbindable` fails if that
changes before Flow 6. `EmbeddingPort` (P10) and `IdentityResolverPort` (P11) are
guarded **separately and permanently** — they are not frontier ports awaiting
their turn, they are the biometric and cross-camera-identity capabilities, C2 and
policy-gated.

---

## Final Verification

✓ **The Crop Manager produces canonical visual evidence.** Camera, frame, object,
transform, quality, gate verdict, trigger reason and provenance travel with every
crop. `test_a_crop_is_fully_traceable`.

✓ **Crops are traceable to camera, frame, track and object.** Track is reached
through the object, which is M7's binding — the layered identity V10 requires.
Construction-time validation refuses a crop whose frame belongs to another camera.

✓ **Quality is measured, recorded and gated.** Six grades plus one verdict,
computed once in M8 and travelling with everything derived from them. Unmeasured
is `None`, never zero.

✓ **Every candidate is accounted for.** Requests and skips partition the
population exactly. Seven skip reasons, every one attributed. Verified at the
unit, runtime and end-to-end levels.

✓ **The budget is a hard ceiling.** 3,600 calls granted against a 3,600 ceiling
under 8 threads, with no thread starved.

✓ **No model-specific preprocessing exists.** No YOLO crop, no CLIP crop, no
Florence crop, no Qwen crop, no InternVL crop. Enforced by an AST scan over every
module in the crop path.

✓ **M8 owns images, not identities.** No face recognition, no person recognition,
no biometric linkage, no identity persistence. P10 and P11 remain unbindable and
unreachable.

✓ **M8 writes no Vision State and no Vision Objects.** M7 remains the only writer
of objects; M9 will be the only producer of attributes. Both enforced by AST scan.

✓ **Execution is deterministic.** Same objects, demands and pixels produce the
same requests, the same skips and the same crop ids. 18 determinism tests.

✓ **Camera partitioning is respected and no cross-camera synchronization exists.**
One lock per camera for trigger state; the only shared thing is a counter.

✓ **Missing evidence is explicit.** `FRAME_UNAVAILABLE`, `BUDGET_EXHAUSTED` and
`QUALITY_INSUFFICIENT` are distinct, counted and separately actionable. Nothing is
ever silently fabricated or silently replaced.

✓ **Flows 1–4 remain unchanged except through approved extension points.** One
typed widening at the declared seam (`RegistryUpdate.frame_ref`), one repaired
pre-existing kernel defect (`Event.payload`), and four additive extensions
(`QualityGrades.overall`, three id types, six errors, one protocol). All 1,556
pre-existing Vision OS tests pass.

✓ **No Flow 6+ functionality was implemented.** No understanding, no observations,
no Vision State, no API. Guarded by directory-existence and port-bindability tests
in three separate suites.

---

## Summary

| Metric | Value |
|---|---:|
| Implementation files | 16 |
| Implementation lines | 5,649 |
| Test files | 15 |
| Test lines | 5,423 |
| New tests | 352 |
| Vision OS tests passing | 1,908 |
| Flow 5 coverage | 86–99% |
| Ports implemented | 3 (P12, P13, P14) |
| Conformance obligations | 16 (G1–G6, Q1–Q5, C1–C5) |
| Broken adapters proving the kits work | 10 |
| Architecture documents modified | **0** |
| Defects found and fixed during implementation | 6 |
