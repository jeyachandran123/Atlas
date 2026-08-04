# Implementation Flow 4 — M7 Object Registry

**Status:** complete
**Scope:** Flow 4 only — the Object Registry (M7)
**Architecture:** unchanged. No architectural conflict was found.

M7 answers one question: *this is the platform's canonical representation of that
visual object.* It converts fragile, camera-local track ids into stable
`ObjectId`s that survive occlusion, track breaks, re-entry and process restart —
and it is the only module permitted to decide any of that.

---

## 1. Architecture Compliance Review

Performed **before any code was written**, as required. The full document is
[FLOW_4_COMPLIANCE_REVIEW.md](./FLOW_4_COMPLIANCE_REVIEW.md); it answers all
twelve constitutional questions the brief specifies. Summary:

**Why M7 exists.** `03_MODULES` §M7: *"This module exists because invariant V10
requires that track ≠ object. It is the seam where cross-camera
re-identification will plug in years from now without touching any tracker."*

**What M7 owns.** The `VisualObject` population, track↔object bindings, lifecycle
states, current attribute values, region membership state, dwell accumulators —
the platform's first durable, semantically meaningful state.

**What M7 does not own.** Pixels, detections, track association, attribute
*extraction*, observation assembly, the Vision State projection, cross-camera
identity, any business meaning.

**Three ambiguities were found and resolved by closer reading, not invention:**

| Ambiguity | Resolution |
| --- | --- |
| `VisualObject` (02_VOM §10.6) has no `regions` field, yet M7 owns region membership | Membership is **partition state keyed by object**, not an object field. The richer `ObjectState` (07_STATE §3.1) is the **L6 Vision State projection** — a different type at a different layer. |
| P11 is "an M7 port" but `15_ROADMAP` §3 says no implementations in Phase 1 | M7's native spatio-temporal binding is **mandatory responsibility 2**, not an extension. P11 is the seam for *replacing* it, ships with no implementations, and stays unbindable. |
| §M7 depends on "Storage Interfaces (durable object state)" — M12, a later flow | A narrow `ObjectStorePort` with reference adapters, satisfying `07_STATE` §9.3 without building a storage layer M7 does not own. |

**No architectural change was requested or made.**

---

## 2. Implementation Report

### 2.1 What was built

14 source files, 4,380 lines, plus 484 tests.

| Area | Modules | Lines |
| --- | --- | --- |
| Object model | `core/model/visual_object.py` | 321 |
| Ports (P11, object store) | `core/ports/registry.py` | 161 |
| Lifecycle machine | `perception/registry/lifecycle.py` | 272 |
| Neutrality gate | `perception/registry/attributes.py` | 211 |
| Region membership + dwell | `perception/registry/regions.py` | 305 |
| Single-writer partition | `perception/registry/partition.py` | 545 |
| Binding | `perception/registry/binding.py` | 227 |
| Engine + runtime | `perception/registry/{engine,runtime}.py` | 1,344 |
| Adapters | `adapters/registry/stores.py` | 317 |
| Conformance + composition | `conformance/registry_kits.py`, `registry_bootstrap.py` | 582 |

### 2.2 The public API, implemented verbatim

`03_MODULES` §M7 fixes it, and it is implemented exactly:

```text
ingest(camera_id, track_update)  → RegistryUpdate
get(object_id)                   → VisualObject !NotFound
active(scope)                    → VisualObject[]
bind(track_id, object_id, ...)   → BindingId
merge(source, target, evidence)  → ObjectId
split(object_id, at, evidence)   → (ObjectId, ObjectId)
apply_attribute(object_id, attr) → void
expire_stale(now)                → ObjectId[]
subscribe()                      ⇢ five event types
```

`ingest` **never raises**: a registry failure may not stop tracking, which may not
stop detection, which may not stop acquisition (V9). Everything else raises on
misuse, because those are direct calls where a caller can handle the error.

### 2.3 The object model

Exactly the fields of `02_VOM` §10.6. Nothing renamed, removed, simplified,
merged in from `Track`, or invented — and `test_visual_object.py` pins the schema
in both directions, asserting each documented field is present *and* that no
`Track` or `ObjectState` field leaked in.

Three properties carry the design:

**`ObjectId` is a ULID minted from the injected clock.** Site-scoped and durable.
A ULID rather than a sequence because identity must be mintable by any partition
on any node without coordination; from the *injected* clock because identity
generation must not reintroduce hidden time (V13).

**`merged_into` is a lifecycle state, not a deletion.** An observation recorded
against the old id remains resolvable (V5). `resolve()` follows the chain.

**`last_confirmed` versus `last_seen`** is *measured* versus *believed* — the
object-level expression of V8, and the model refuses to construct an object whose
measurement is newer than its most recent update.

### 2.4 The lifecycle is a closed machine

The transition table is transcribed edge-for-edge from the `02_VOM` §10.6 state
diagram. `test_object_lifecycle.py` reads it back the same way: every documented
edge is asserted legal, and every edge *absent* from the diagram is asserted
illegal.

Read the absences carefully — `occluded → merged_into` is not in the diagram
because an occluded object is mid-claim, and `departed → active` is not because
re-entry after departure mints a *new* object plus an identity assertion linking
them, which is the registry's job rather than a lifecycle edge.

### 2.5 Ambiguity is never guessed

Section M7's failure table is unambiguous, and it is implemented literally:

> *Re-entry ambiguity (two candidates match) → Create a **new** object and emit a
> low-confidence identity assertion linking candidates. **Never guess silently**;
> let the consumer choose a confidence threshold (V1).*

The binder's most important output is not its winner but the case where it
declines to pick one **and keeps the alternatives**. `BindingDecision.candidates`
survives the refusal, becomes `IdentityAssertion.alternatives`, and reaches the
bus. A binder returning only a match would make the ambiguity unrecoverable one
function call after it was known.

---

## 3. Engine Interaction Report

### 3.1 The pipeline position

```
Frame Scheduler (M3, Flow 1)
        │  AdmittedFrameConsumer.on_admitted(frame_ref, fidelity)
        ▼
Detection Runtime (M5, Flow 2)
        │  DetectionConsumer.on_detected(outcome)
        ▼
Tracking Runtime (M6, Flow 3)
        │  TrackUpdate                       ← the Flow 4 seam
        ▼
Registry Runtime (M7, Flow 4)  — actor per camera
        │
        ▼
   RegistryUpdate  +  Event Bus
        │
        ├──▶ M8 Crop Manager (Flow 5)   — candidate objects
        └──▶ M11 Observation Builder (Flow 6) — presence, spatial, state signals
```

`01_LAYERED` §5.1 shows exactly this: `TRK->>REG: tracks[]`, then
`REG->>OBB` and `REG->>CRP`. §5.2 sizes the edge at ~2 KB on the **control**
plane — no pixels cross it, and none can: M7 never imports a frame type, which
an architecture test enforces.

### 3.2 What each engine may assume

| Direction | Guarantee |
| --- | --- |
| Tracking → Registry | Per-camera update order; tracks carry capture time. |
| Registry → Tracking | Never raises; never blocks indefinitely. |
| Registry → Flow 5/6 | Immutable `VisualObject` snapshots and six event types. |

**A tracking failure is not a registry failure.** An update that arrives with no
tracks is valid — it says nothing was measured, which moves an active object to
`occluded`. That is presence-driven and immediate. Horizon-driven aging is
`expire_stale`'s job, because an empty frame carries no capture time to age
*with* (see §11.2).

### 3.3 Failure isolation

`ingest` absorbs everything into `RegistryUpdate(failed=True, reason=...)`,
counts it, and degrades health. `test_a_failure_degrades_health` and
`test_the_registry_recovers_after_a_transient_failure` prove both halves: the
failure is visible, and the next frame works.

---

## 4. Ownership Transition Report

This is the flow that introduces **canonical ownership**, so the boundary is
stated exactly.

### 4.1 What M6 owns

| | |
| --- | --- |
| **Owns** | Per-camera tracker state: active tracks, motion filter state, epoch counter |
| **Durability** | **None.** *"The platform's most volatile state and deliberately not durable"* (§M6) |
| **Scope** | One camera, one tracker epoch |
| **Identifier** | `TrackId = (CameraId, TrackerEpoch, LocalTrackId)` — fragile by construction |
| **Confidence** | `ASSOCIATION` — P(this detection continues this track) |
| **Lifetime** | Seconds to minutes; dies on restart |

### 4.2 What M7 owns

| | |
| --- | --- |
| **Owns** | The `VisualObject` population, track↔object bindings, lifecycle states, current attribute values, region membership, dwell accumulators |
| **Durability** | **Durable.** *"An object present for 20 minutes must not become a new object because a process recycled"* (§M7) |
| **Scope** | Site-scoped identity, camera-owned partition |
| **Identifier** | `ObjectId` — a site-scoped ULID |
| **Confidence** | `IDENTITY` — P(this track is this object) |
| **Lifetime** | Minutes to the retention horizon; survives restart |

### 4.3 Exactly when ownership transfers

Ownership does **not** transfer — the two are concurrent and permanent. What
happens at the seam is a **binding**: M7 asserts that a track belongs to an
object, records the assertion with its method, confidence and evidence, and keeps
owning the object regardless of what happens to the track.

The precise moments:

| Moment | What M7 does |
| --- | --- |
| A track appears with no matching object | Mints an `ObjectId` and opens a binding with `FIRST_SIGHT` |
| A bound track continues | Records the sighting; the binding stays open (`TRACK_CONTINUITY`) |
| A track vanishes from the update | **Closes the binding** and ages the object |
| An unbound track matches a dormant object | Opens a new binding with `SPATIO_TEMPORAL` and publishes the assertion |
| Two candidates are too close | Mints a *new* object, publishes the alternatives, guesses nothing |
| A restart | Objects reload **unbound**; the next match binds with `EPOCH_REBIND` at reduced confidence |

### 4.4 Who may modify objects, and who may only read

| Actor | Rights |
| --- | --- |
| **The registry's partition actor** | **The only writer.** One per camera, serialized by the runtime's per-camera lock |
| M6 Tracking | Read nothing — it does not know objects exist |
| M8 Crop Manager (Flow 5) | **Read only** — consumes candidate objects |
| M11 Observation Builder (Flow 6) | **Read only** — consumes presence and spatial signals |
| M13 Vision State (Flow 7) | **Read only** — projects from observations, not from M7 |
| Business systems | **Read only**, and only through the Observation API |

**Structurally enforced, not documented:**

- `VisualObject` is a frozen dataclass; every mutation produces a new instance.
- `test_a_published_object_cannot_be_mutated` and
  `test_a_reader_snapshot_does_not_drift` prove a consumer's view cannot move.
- `test_no_module_outside_the_registry_writes_an_object` scans every module for
  `replace()` on a `VisualObject`.
- `test_only_the_registry_mints_object_ids` scans every module's AST for
  `ObjectId(...)` construction, excluding only decode (adapters) and fixtures
  (conformance), both by name and with a stated reason.
- `test_the_partition_holds_no_lock` — safety comes from the actor owning the
  partition, not from locks inside it. A lock would suggest concurrent writers
  are expected, licensing the design the sharding model exists to prevent.

---

## 5. Architecture Compliance Report

| | Invariant | How Flow 4 holds it |
| --- | --- | --- |
| V1 | Semantic Ceiling | The **attribute neutrality gate** rejects `is_employee`, `is_compliant`, `wait_time_excessive` and names the neutral counterpart. Region occupancy is counting only — no `is_crowded`, no `capacity`. |
| V2 | Vertical neutrality | Region `label` is opaque; no platform logic branches on it. An AST guard rejects domain vocabulary in the layer. |
| V4 | Explainability | Every binding carries method, confidence, evidence. Provenance is injected, never invented — it carries the real config revision. |
| V5 | Immutability | **Merge preserves history.** `merged_into` rather than deletion; `resolve()` follows the chain; superseded bindings are retained. |
| V6 | Single-writer | One partition per camera, one actor per partition, no locks. Readers hold immutable snapshots. |
| V8 | Blindness explicit | `last_confirmed` vs `last_seen`; `staleness()`; attributes carry validity horizons; `failed` is distinct from empty. |
| V10 | Layered identity | Track ≠ Object. The reason M7 exists, and 8 tests enforce the separation. |
| V11 | Normalized time | **Dwell is computed from capture time**, never processing time. A camera's capture clock is monotonic and an empty frame does not advance it. |
| V12 | Pixels stay local | M7 never imports a frame, buffer or crop type — asserted. |
| V13 | Deterministic replay | ULIDs minted from the injected clock; no wall-clock read; no `random` import; ties break on object id. |

### 5.1 Explicit scope confirmations

- **No identity beyond objects.** No `person_id`, no `name`, no biometric field.
  An AST guard rejects `face`, `reid`, `gallery`, `biometric` in the layer.
- **No cross-camera tracking.** `ObjectId` is site-scoped but partitions are
  camera-owned; a cross-partition merge is **refused** with a message explaining
  it must be two-phase and event-driven.
- **No re-identification.** P10 `EmbeddingPort` and P11 `IdentityResolverPort`
  both remain unbindable; no adapter ships for either.
- **No semantic understanding.** M7 *holds* attributes; it produces none.
  `test_the_registry_produces_no_attributes_itself` and an AST guard against
  `UnderstanderPort` enforce it.
- **No observation generation.** `test_the_registry_builds_no_observations`.
- **No Vision State writes.** `test_the_registry_writes_no_vision_state`.
- **No business logic.** No alert, violation, incident or threshold anywhere.

---

## 6. Dependency Graph

```
                      registry_bootstrap.py
                   (composition root — the only
                    module that selects a store)
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
      RegistryRuntime    ObjectRegistry    ObjectStorePort
      (actor per camera) (M7 public API)   (memory / file)
              │               │
              │       ┌───────┼────────┬──────────────┐
              │       ▼       ▼        ▼              ▼
              │  Lifecycle  Track   Attribute    RegionTracker
              │   Machine   Binder  Registry     (spatial index)
              │  (closed     │      (V1 gate)         │
              │   table)     │                        │
              │              ▼                        │
              └────────▶ RegistryPartition ◀──────────┘
                       (single writer, sole
                        ObjectId minting,
                        bounded everything)
                              │
                              ▼
                     VisualObject (frozen)

              P11 IdentityResolverPort ── declared, unbound, unimplemented
```

**Acyclic, and the important directions hold:**

- `perception/registry/` imports **no adapter** — asserted.
- `perception/tracking/` imports **nothing from the registry** — the dependency
  runs one way, because a tracker that knew about objects would be re-deciding
  identity.
- `perception/registry/` imports **nothing from tracking** — it consumes
  `TrackUpdate` from the object model, not M6 itself.
- `core/` imports no flow layer — asserted, with relative sibling imports
  correctly excluded.

---

## 7. Runtime Integration Report

### 7.1 Actor per camera

`08_RUNTIME` §2 lists M7 in the actor table; `07_STATE` §4.1 states the rule:
*"The camera is the partition. Each partition has exactly one writer."*

The runtime holds one `asyncio.Lock` per camera. Two updates for one camera can
never interleave; two cameras never contend. `test_one_camera_is_serialized`
fires 30 concurrent updates and asserts none fail;
`test_many_cameras_do_not_contend` drives 25 cameras concurrently.

`forget(camera_id)` releases a detached camera's lock — without it the table
grows with every camera the process has ever seen, a leak visible only on
long-lived nodes with churning camera sets.

### 7.2 Two schedules the frames do not drive

**Expiry.** A camera that goes quiet must still see its objects age. Without a
tick, a dormant object would never become departed. `expire_stale(now)` is M7's
documented API for exactly this, and the runtime calls it on
`expiry_interval_ms`.

**Persistence.** §M7 Performance: *"Durable writes are batched and asynchronous —
the hot path updates memory and enqueues persistence; it never blocks on I/O."*
The runtime marks partitions dirty and flushes on `persistence_interval_ms`.
`stop()` forces a final flush, because a clean shutdown that discarded unflushed
objects would make restart behaviour depend on whether the last flush happened to
run.

A store failure increments `OBJECT_STORE_FAILURES` and continues:
`test_a_store_failure_does_not_stop_ingestion` proves durability degrades while
the pipeline does not.

---

## 8. State Ownership Report

### 8.1 What M7's state is — and is not

M7 owns **the object population**, at L2. That is **not** the Vision State, which
`07_STATE` §2 defines as a materialized projection of the immutable observation
log, built by M13 at L6 from what M11 published.

The distinction is the single most important boundary in this flow, because the
brief asks M7 to "respect versioning, immutability, ownership, recovery,
projection, state integrity" — all of which are `07_STATE` concepts — while
`07_STATE` describes a different layer's artifact. §M7 resolves it: M7's state
*"is the primary input to the Vision State projection"*. It feeds it through
observations; it does not write it.

Building anything resembling the Vision State here would be implementing Flow 7
early, and `test_the_registry_writes_no_vision_state` prevents it.

### 8.2 Versioning

Each partition carries a monotonic `version`, incremented on every mutation and
never on a read. `test_reads_do_not_advance_the_version` pins that. Snapshots
carry the version so a reload can detect a stale write.

### 8.3 Every bound is finite

Section M7 calls unbounded history here *"the most likely long-run memory leak in
the entire platform, which is why bounding is a structural property rather than a
tuning parameter"*.

| Bound | Default | Enforced by |
| --- | --- | --- |
| Objects per camera | 512 | `RegistryCapacityError`; provisional shed first, then refuse + alarm |
| Spatial history | 64 samples | `deque(maxlen=…)` |
| Class history | 32 samples | `deque(maxlen=…)` |
| Provisional horizon | 3 s | lifecycle machine |
| Occlusion horizon | 10 s | lifecycle machine |
| Dormant horizon | 120 s | lifecycle machine |
| Retention horizon | 600 s | lifecycle machine, then eviction |

**A confirmed object is never shed.** Only `provisional` ones are, oldest first.
Withdrawing an assertion to save memory would make the platform's claims a
function of its load — `test_a_confirmed_object_is_never_shed` pins it, and the
lifecycle machine refuses `on_shed` for any other state.

### 8.4 Recovery

`07_STATE` §9.3 is implemented exactly:

| Element | Behaviour | Test |
| --- | --- | --- |
| Object identity | **Preserved** | `test_object_identity_survives_a_restart` |
| `first_seen` | Preserved | `test_a_long_lived_object_does_not_become_new` |
| Tracks | **Lost** — bindings close on reload | `test_tracks_do_not_survive_a_restart` |
| Re-binding | Explicitly reduced confidence | `test_re_binding_after_a_restart_carries_reduced_confidence` |
| Merged objects | Preserved, still resolvable | `test_merged_objects_survive_a_restart` |

**Never silently repaired.** A snapshot that fails to decode raises
`ObjectStoreError`; it is never downgraded to an empty partition, because that
presents data loss as a fresh start. `decode_failure_is_loud` is a conformance
check, and a store that swallows corruption fails it.

Attributes are deliberately **not** restored: their values live in the
observation log, which is the system of record. Restoring keys without values
would present a stale claim as current.

---

## 9. Performance Report

### 9.1 Measured

Single camera, steady state, CPU.

| Objects | Measured | Budget (`11_PERFORMANCE` §1.1) |
| --- | --- | --- |
| 1 | **0.049 ms/frame** | ~0.1 ms/frame |
| 5 | 0.154 ms/frame | scales with object count |
| 10 | 0.288 ms/frame | scales with object count |
| 20 | 0.592 ms/frame | scales with object count |
| 50 | 1.880 ms/frame | scales with object count |

The single-object case sits at **49% of budget**. Growth from 1 to 50 objects is
38× for 50× the objects — sub-linear, because the binder only scores candidates
that survive gating.

### 9.2 Region membership is not naive

Section M7 requires that polygon tests *"must not be naive at 100 objects × 20
regions"* — 2,000 ray-casts per frame. The spatial index rejects most pairs on
four float comparisons. `test_region_membership_is_not_naive` asserts 20 regions
cost under 10× one region, where naive would be 20×. `test_the_bounds_check_does_not_change_the_answer`
proves the rejection is exact rather than approximate, by comparing against
testing every polygon at 49 sample points.

### 9.3 Scaling shape

1, 10 and 100 cameras are the same code path. No cross-partition state, so
cameras are fully parallel; `test_a_hundred_cameras_sustain_the_processing_rate`
drives 500 registry calls inside 5 s against a 0.5 relative-cost budget.

### 9.4 Memory

`test_object_count_does_not_grow_across_a_long_run` asserts under 20,000 new
objects across 500 frames. `test_spatial_history_stays_bounded` runs 400 frames
and asserts the ring held while `observation_count` exceeded 300 — proving the
bound is on *memory*, not on the object's life.

---

## 10. Test Report

### 10.1 Totals

```
Plain run:     1,555 passed, 0 skipped        (41.8s)
Coverage run:  1,540 passed, 15 skipped       94% of app/vision_os
                                              (11,457 statements, 658 missed)
Ruff:          all checks passed
Wider Atlas:   2,600 tests collect cleanly; tests/cognitive_kernel 36 passed
Flow 4:        484 tests
```

### 10.2 By required category

| Required category | File | Tests |
| --- | --- | --- |
| Unit — object model | `unit/test_visual_object.py` | 47 |
| Lifecycle | `unit/test_object_lifecycle.py` | 57 |
| Boundary (the V1 gate) | `unit/test_attribute_gate.py` | 44 |
| Unit — partition, ownership | `unit/test_partition.py` | 60 |
| Unit — binding | `unit/test_binding.py` | 39 |
| Unit — regions, dwell | `unit/test_regions.py` | 37 |
| Integration | `integration/test_registry_engine.py` | 70 |
| Ownership, state, versioning, recovery, conformance | `integration/test_ownership_and_recovery.py` | 47 |
| Integration — end to end | `integration/test_end_to_end.py` | 14 |
| Architecture | `test_registry_architecture.py` | 40 |
| Concurrency, performance, stress, regression | `test_registry_performance.py` | 29 |

Deterministic-replay coverage is distributed rather than a separate file: ULID
minting from the injected clock, tie-breaking in class resolution and candidate
ordering, and the no-wall-clock / no-`random` architecture guards.

### 10.3 Coverage by area

| Module | Coverage |
| --- | --- |
| `perception/registry/attributes.py` | 100% |
| `registry_bootstrap.py` | 100% |
| `core/model/visual_object.py` | 99% |
| `perception/registry/binding.py` | 99% |
| `perception/registry/lifecycle.py` | 99% |
| `perception/registry/regions.py` | 99% |
| `perception/registry/partition.py` | 98% |
| `perception/registry/engine.py` | 96% |
| `adapters/registry/stores.py` | 95% |
| `core/ports/registry.py` | 91% |
| `conformance/registry_kits.py` | 85% |
| `perception/registry/runtime.py` | 84% |

`registry_kits.py` at 85% is the P11 kit, which has no adapter to run against —
its checks are exercised only through the fixtures that prove they reject.

### 10.4 Conformance

| Kit | Checks | Fast subset | Registered? |
| --- | --- | --- | --- |
| `OBJECT_STORE_KIT` (P21) | 13 | 12 | Yes |
| `IDENTITY_RESOLVER_KIT` (P11) | 5 | 5 | **No — deliberately** |

Obligations covered: **S1–S3** plus **A1**, **V4**, **V5** for the store; **I1**,
**I3–I5** plus **A1** for the resolver.

The P11 kit is written but **not registered**, because registering a kit for a
port with no implementations would suggest one is expected. The contract waits
for the Phase 2 adapter rather than being written after it.

**The store kit is proven to fail**: three broken stores — one that loses
identity, one that drops merged objects, one that swallows corruption — are each
asserted to fail their own check by name.

---

## 11. Architectural Discoveries

### 11.1 `ObjectState` is not `VisualObject`

`07_STATE` §3.1's `ObjectState` is a strict superset of `02_VOM` §10.6's
`VisualObject` — it adds `regions`, `trajectory`, `last_observation`,
`provenance_summary`. Reading them as one type would have pulled the L6 Vision
State projection into L2.

They are different types at different layers. M7 implements §10.6;
`test_no_projection_field_leaked_in` keeps them apart.

### 11.2 An empty frame carries no capture time

**Found by the object model refusing to be constructed.** Object timestamps must
derive from capture time, not processing time (V11) — but a frame with no tracks
has no capture time to read. The first implementation fell back to the injected
clock, which could be *earlier* than the object's `last_confirmed`, producing an
object whose measurement was newer than its most recent update.

The invariant caught it at construction. The fix is that a camera's capture clock
is **monotonic** and an empty frame does not advance it: aging a quiet camera is
`expire_stale(now)`'s job, which is precisely why that method takes a `now`.

The division that emerged is clean and worth stating: **presence-driven
transitions happen during ingest** (a track vanishing moves an object to
`occluded` immediately), **horizon-driven transitions happen during the sweep**.

### 11.3 A vanished track must release its binding

**Found by an integration test.** An object whose track disappeared kept its
binding open. The binder considers only *unbound* objects as re-entry candidates
— because a bound object already has a track — so such an object was permanently
unreachable for re-entry. Occlusion recovery silently never worked.

The fix: when a track vanishes from an update, its binding closes. The binding
history is retained (V5); only the open flag changes.

### 11.4 One sweep must advance more than one edge

**Found by an integration test.** A single `expire_stale` call advanced one
lifecycle edge, so a twenty-minute gap left an object `occluded` when it should
have expired. The result depended on how often the sweep ran rather than on
elapsed time.

The fix drives the machine to a fixed point. `test_a_large_time_jump_reaches_the_right_terminal_state`
pins it.

### 11.5 Provenance must be injected

The first implementation hardcoded a placeholder config revision. `02_VOM` §3 is
explicit that `config_revision` is mandatory and not optional: *"Without the exact
weights and the exact configuration, that question is unanswerable, and every
regression investigation becomes archaeology."* Corrected to constructor
injection, pinned by `test_provenance_carries_the_real_config_revision`.

---

## 12. Known Limitations

### 12.1 Cross-partition merge is refused, not queued

§M7 specifies merge across partitions as a *"two-phase, event-driven, eventually
consistent"* operation at the site layer. Flow 4 implements the refusal and the
message explaining why; it does **not** implement the two-phase protocol, because
the site layer that would coordinate it does not exist until Phase 2. A
cross-partition merge raises `IdentityConflictError` naming the constraint.

### 12.2 Identity resolution is spatio-temporal only

M7's native binding uses position and elapsed time. Appearance-based and
cross-camera strategies are P11, which has no implementations in Phase 1. The
practical consequence: an object that leaves and re-enters far from where it
left, or after the re-entry gap, becomes a new object. That is correct behaviour
— the registry has no basis to claim continuity it did not observe — but it is a
real limit on identity continuity in Phase 1.

### 12.3 Ground-plane containment falls back to the bounding box

`ContainmentMethod.GROUND_POINT` is declared and recorded, but projecting to the
ground plane needs a calibration homography the registry does not hold. The
implementation falls back to the bottom-centre point and **records which method
was used**, so a consumer comparing dwell across cameras can tell. Wiring the
calibration through is a small change; the honest reporting is what matters now.

### 12.4 Split divides evidence approximately

`split` partitions spatial and class history by timestamp exactly, but
`observation_count` is halved rather than recomputed, because the per-observation
record needed to count precisely lives in the observation log (Flow 6). The
counts are approximate on both sides of a split until that log exists.

### 12.5 Region occupancy is computed on demand

`RegionTracker.occupancy()` walks the membership map rather than maintaining
incremental counters. At the documented population (tens to low hundreds per
camera) this is trivially cheap, but a deployment publishing occupancy at high
frequency across many regions would want incremental maintenance.

### 12.6 Attributes are not restored across a restart

Deliberate — see §8.4 — but it does mean that after a restart an object's
attributes are empty until the next Understanding pass repopulates them. Flow 5
will produce a `FIRST_SIGHT` re-analysis for exactly this reason (`07_STATE`
§9.3 lists trigger state as lost), so the gap closes when that flow ships.

---

## 13. Future Extension Points

| Extension point | Where | For |
| --- | --- | --- |
| `RegistryUpdate` consumer | `RegistryRuntime(sink=…)` | **Flow 5.** The Crop Manager attaches here, as the registry attached to tracking. |
| `IdentityResolverPort` (P11) | `core/ports/registry.py` | Cross-camera identity, appearance-based matching, learned association — Phase 2, C2, policy-gated. The kit is written and waiting. |
| `EmbeddingPort` (P10) | `core/ports/tracking.py` | Appearance vectors for resolution. Unbindable; C2 biometric. |
| `ObjectStorePort` (P21) | `core/ports/registry.py` | Embedded KV, distributed DB. Two reference adapters ship. |
| Camera topology model | new | Which cameras are adjacent, with transit-time priors — the mitigation for cross-camera matching's O(n²) cost. |
| `ContainmentMethod.GROUND_POINT` | `perception/registry/regions.py` | Ground-plane containment once calibration is wired (§12.3). |
| `AttributeRegistry` | `perception/registry/attributes.py` | New attributes, each through the neutrality gate. |
| `LifecyclePolicy` / `BindingPolicy` | `perception/registry/` | Retuning horizons and thresholds without code change. |
| `RegistrySection` | `kernel/config/schema.py` | New resource and horizon knobs, strongly typed and validated. |

**Frontier discipline.** `BINDABLE_PORTS` is now
`FLOW1 | FLOW2 | FLOW3 | FLOW4`. Every later-flow port stays defined and
unbindable, and `test_flow_five_and_later_ports_remain_unbindable` fails if that
changes before Flow 5. `EmbeddingPort` and `IdentityResolverPort` are guarded
separately and permanently — they are not frontier ports awaiting their turn.

---

## Final Verification

✓ **Flow 1 remains unchanged except through approved extension points.** No Flow 1
module was modified; only shared vocabulary (ids, errors, config, events,
metrics, the port frontier) was extended additively.

✓ **Flow 2 remains unchanged except through approved extension points.** No Flow 2
module was touched in this flow at all.

✓ **Flow 3 remains unchanged except through approved extension points.** No Flow 3
module was touched. `test_the_tracker_port_is_untouched` and
`test_tracking_never_imports_the_registry` verify both directions.

✓ **M7 consumes only Tracking outputs.** `ingest` takes a `TrackUpdate` and
nothing else.

✓ **M7 never consumes pixels.** It imports no frame, buffer or crop type —
asserted by `test_the_registry_never_touches_pixels`.

✓ **M7 never consumes detections directly.** Asserted by
`test_the_registry_does_not_re_associate_detections`.

✓ **M7 never performs identity.** No person, face, biometric or global-identity
field or vocabulary exists; P10 and P11 are both unbindable.

✓ **M7 never performs semantic understanding.** It holds attributes; it produces
none. Asserted twice.

✓ **M7 never performs observation generation.** Asserted.

✓ **M7 never performs business reasoning.** No alert, violation, incident or
threshold anywhere; the neutrality gate rejects judgment-bearing attributes.

✓ **M7 is the sole canonical owner of Vision Objects.** Frozen objects, one writer
per partition, `ObjectId` minted in exactly one place, and four AST guards
enforcing it.

✓ **No future roadmap functionality has been implemented.** Cross-camera identity,
persistent biometric identity and federated identity are absent and structurally
prevented.

---

## Summary

Flow 4 is complete. 14 source files, 4,380 lines, 484 tests, 94% coverage, ruff
clean.

The architecture was treated as a constitution. Three ambiguities surfaced during
the mandatory review and each was resolved by reading the documents more closely
rather than by inventing an answer. Five discoveries during implementation (§11)
each corrected the code to match the architecture rather than the reverse — and
two of them were caught by the platform's own invariants refusing to be violated,
which is the strongest evidence those invariants are load-bearing rather than
decorative.

M7 owns canonical object identity and stops there. It has no memory of pixels, no
vocabulary for meaning, no notion of who anyone is, and no way for anything else
to write what it owns.
