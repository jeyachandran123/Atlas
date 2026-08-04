# Flow 4 — Constitutional / Architecture Compliance Review

**Performed before any code was written**, as required.

Documents reviewed: `03_MODULES` (M7, M6 boundary, M8 handoff), `02_VOM` (§4 identity,
§9 attributes, §10.6 VisualObject), `01_LAYERED` (§2 dependency law, §5 data flow,
§8 cross-cutting placement). Secondary: `06_PORTS`, `07_STATE`, `08_RUNTIME`,
`09_API_CONTRACTS`, `10_RELIABILITY`, `11_PERFORMANCE`, `12_SECURITY`,
`14_TESTING`. `00_CHARTER` for constitutional clarification; `15_ROADMAP` only to
confirm nothing future is built.

---

## 1. Why M7 exists

`03_MODULES` §M7 states it directly:

> *This module exists because invariant V10 requires that track ≠ object. It is
> the seam where cross-camera re-identification will plug in years from now
> without touching any tracker.*

The platform has four notions of identity (`02_VOM` §4), never conflated:

| Layer | Identifier | Scope | Stability | Who mints it |
| --- | --- | --- | --- | --- |
| Detection | none | one frame | n/a | Detection Engine |
| Track | `TrackId` | one camera, one tracker epoch | **fragile** | Tracking Engine |
| Object | `ObjectId` | one site | **durable** | **Object Registry — sole authority** |
| Global | assertion | cross-site | asserted, revisable | Phase 2+ |

M6 produces a handle that breaks on every occlusion and dies on every restart.
Something must convert that into a thing that survives both. That is M7, and
`01_LAYERED` §8 assigns it exclusively:

> **Identity of things | L2 Object Registry | Exactly one module may mint or
> retire an object identity. Diffusing this is how ID chaos begins.**

---

## 2. What M7 owns

`03_MODULES` §M7 State Ownership:

> **Owns:** the `VisualObject` population, track↔object bindings, lifecycle
> states, current attribute values, region membership state, dwell accumulators.

Plus the eight responsibilities:

1. Mint, bind, and retire `ObjectId`s — **sole authority**.
2. Bind tracks to objects with method and confidence; re-bind after breaks.
3. Own the `VisualObject` lifecycle state machine.
4. Resolve class flapping using the retained class distribution.
5. Compute region membership, entry/exit, and dwell — **as pure geometry**.
6. Hold current attribute values as produced, and mark them stale on schedule.
7. Emit identity assertions as revisable claims with evidence.
8. Provide merge/split operations that correct identity errors **without
   rewriting history**.

**This is the platform's first durable, semantically meaningful state.** Unlike
tracker state it *must* survive restart: "an object that has been present for 20
minutes must not become a new object because a process recycled."

---

## 3. What M7 absolutely does NOT own

| Not owned | Belongs to | Constitutional basis |
| --- | --- | --- |
| Pixels, frames, crops | M4 buffer / M8 | V12; M7 consumes control-plane only |
| Detections | M5 | `01_LAYERED` §5.2 — the Registry edge carries **tracks**, not detections |
| Track association | M6 | V10; M7 consumes `TrackUpdate`, never re-associates detections |
| Attribute *extraction* | M9 Understanding | M7 responsibility 6 says "hold as they are produced" — hold, not produce |
| Observation assembly | M11 Observation Builder | `01_LAYERED` §8: schema and ceiling enforcement is M11's choke point |
| The Vision State projection | M13 | `07_STATE` §2 — state is projected from the observation **log**, not written by M7 |
| Cross-camera identity | Phase 2 via P11 | `15_ROADMAP` §3 |
| Any business meaning | Consumers | V1 |

### 3.1 The two subtle ones

**M7 does not write Vision State.** `07_STATE` is emphatic that Vision State is a
*materialized projection of the immutable observation log*, produced by M13 from
what M11 published. M7's own durable object population is a **different thing at a
different layer** — M7 is L2, Vision State is L6. §M7 says M7's state "is the
primary input to the Vision State projection", i.e. it feeds it via observations,
not by writing it.

Implementing anything resembling the Vision State in Flow 4 would be implementing
Flow 7 early. It is out of scope.

**`ObjectState` (07_STATE §3.1) is not `VisualObject` (02_VOM §10.6).**
`ObjectState` is the L6 projection and is a strict superset — it carries
`last_observation: ObservationId`, `provenance_summary`, `regions`, `trajectory`.
`VisualObject` is what M7 owns. The brief says *"Implement the Object model exactly
as defined in 02_VISION_OBJECT_MODEL"*, so §10.6 is the target and the extra
`ObjectState` fields are **not** to be added.

---

## 4. Why Tracking cannot own Object Registry responsibilities

Four independent reasons, each sufficient:

1. **Lifetime.** `03_MODULES` §M6 calls tracker state "the platform's most
   *volatile* state and deliberately **not durable**". Object identity must
   survive restart (`07_STATE` §9.3: *"object identity survives, tracks do
   not"*). One module cannot own both a state that must be discarded on restart
   and a state that must not.

2. **Scope.** A tracker is per-camera and per-epoch by contract (T7: *"no
   cross-camera state exists in this port"*). `ObjectId` is **site-scoped**. A
   module forbidden from holding cross-camera state cannot own a site-scoped
   identifier.

3. **Confidence semantics.** A track carries `ASSOCIATION` confidence — *"P(this
   detection continues this track)"*. An object carries `IDENTITY` confidence —
   *"P(this track is this object)"*. These measure different things and
   `02_VOM` §7 forbids conflating them.

4. **Revision.** `02_VOM` §4.2 requires identity links be revisable: merge, split,
   supersede, with lineage. A tracker that could merge two tracks retroactively
   would be rewriting history, which V5 forbids. M7 does it by **superseding**,
   which requires durable records a tracker does not have.

The payoff is named in §M7's extension points: cross-camera re-ID *"plugs in
here… No tracker, detector, or pipeline module changes. This is the concrete
payoff of separating M6 from M7."*

---

## 5. Why Object Registry cannot own Understanding responsibilities

1. **Layer.** M7 is L2 Perception (*"what things exist and which are the same
   thing over time"*). Understanding is L4 (*"what those things are like"*).
   `01_LAYERED` §1.2 names L2/L3 fusion as a boundary that systems collapse "always
   with the same consequences": *"Systems that fuse these end up invoking heavy
   models from inside the tracker, which makes cost proportional to frame rate and
   makes both components untestable."*

2. **Cost.** Understanding is ~200 ms/call versus the registry's ~0.1 ms/frame
   (`11_PERFORMANCE` §1.1). Putting a VLM behind the registry makes cost
   proportional to `cameras × fps × objects`, which `03_MODULES` §M8 identifies as
   the difference between an affordable deployment and an unaffordable one.

3. **The ceiling choke point.** `01_LAYERED` §8 places schema and ceiling
   enforcement at **M11 Observation Builder** — "one choke point through which
   every fact must pass. Enforcement distributed across producers is enforcement
   that will be bypassed." A registry that produced attributes would be a second,
   unenforced producer.

M7 **holds** attribute values (responsibility 6) and marks them stale. Holding is
storage; producing is inference. The distinction is the whole of L2/L4.

---

## 6. Where M7 begins and ends

**Begins:** on receipt of a `TrackUpdate` from M6 for one camera
(`01_LAYERED` §5.1: `TRK->>REG: tracks[]`; §5.2: the edge payload is "Tracks
(+ association metadata), ~2 KB, Control plane").

**Ends:** when canonical `VisualObject` records and their lifecycle transitions
are emitted (`03_MODULES` §M7 Outputs). Specifically it ends at:

- `RegistryUpdate` returned from `ingest`
- registry events on the bus
- `active(scope)` / `get(object_id)` reads for consumers

It does **not** extend to crop selection (M8 consumes "candidate objects" — M7
supplies the objects, M8 decides), nor to observation assembly (M11).

---

## 7. Who feeds M7, who consumes M7

| Direction | Module | Payload | Status |
| --- | --- | --- | --- |
| **Feeds** | M6 Tracking Engine | `TrackUpdate` | ✅ Flow 3, exists |
| **Feeds** | M1 Camera Manager | Region definitions, calibration | ✅ Flow 1, exists |
| **Feeds** | M9/M11 path | Attributes via `apply_attribute` | ⏳ Flow 5/6 — API exposed, no caller yet |
| **Feeds** | P10 EmbeddingPort | Optional appearance embeddings | ⛔ unbindable (C2 biometric) |
| **Feeds** | P11 IdentityResolverPort | Optional identity assertions | ⛔ no implementations in Phase 1 |
| **Consumes** | M8 Crop Manager | Candidate objects | ⏳ Flow 5 |
| **Consumes** | M11 Observation Builder | Presence, spatial, state signals | ⏳ Flow 6 |
| **Consumes** | M13 Vision State | Projection input, via observations | ⏳ Flow 7 |

`apply_attribute` is in M7's documented public API, so it is implemented. That it
has no caller until Flow 5 is expected, not a gap — the same posture Flow 2 took
with capability declarations for classes no detector produced yet.

---

## 8. Invariants constraining M7

| | Invariant | Binding on M7 |
| --- | --- | --- |
| **V1** | Semantic Ceiling | Region membership and dwell are **pure geometry**. `14_TESTING` §283 names a "Registry gate": registering a judgment-bearing attribute must be rejected. No `is_crowded`, no `queue_forming`. |
| **V2** | Vertical neutrality | Region `label` is opaque; no platform logic may branch on it. |
| **V4** | Explainability | Every binding carries method, confidence, evidence. Every identity assertion is a claim, not a truth. |
| **V5** | Immutability | **Merge preserves history.** `merged_into` rather than deletion; prior observations stay resolvable. History is never rewritten — corrections are new facts with lineage. |
| **V6** | Single-writer | One actor per camera partition. Readers get immutable snapshots. No cross-partition locks. |
| **V8** | Blindness explicit | `last_confirmed` vs `last_seen` is *measured* vs *believed*. Attributes carry staleness. |
| **V10** | Layered identity | Track ≠ Object. The reason this module exists. |
| **V11** | Normalized time | Dwell computed from `t_capture`, **never** processing time (`14_TESTING` §4). |
| **V12** | Pixels stay local | M7 never touches a frame. |
| **V13** | Deterministic replay | Injected clock. `ObjectId` is a ULID minted from the injected clock, not wall time. |

---

## 9. Implementation temptations that must be rejected

Each of these is plausible, locally convenient, and forbidden.

| Temptation | Why it is wrong |
| --- | --- |
| Delete an object on merge | V5. `merged_into(ObjectId)` is a lifecycle **state**; observations referencing the old id must stay resolvable. |
| Let a consumer mutate a `VisualObject` | V6 and the brief's canonical-ownership rule. Objects are frozen; only the registry writes. |
| Add `regions` to `VisualObject` | `02_VOM` §10.6 has no such field, and the brief forbids inventing fields. Membership is separate partition state that M7 owns. |
| Guess between two re-entry candidates | §M7 failure table: *"Create a new object and emit a low-confidence identity assertion… **Never guess silently**."* |
| Silently rewrite a past class assertion | §M7: *"never silently rewrite past class assertions"* — publish `class_history`. |
| Take a lock across camera partitions for merge | §M7 Thread Safety: merge is **two-phase, event-driven, eventually consistent**. Locks here "reintroduce, at the worst possible place, exactly the global contention the sharding model was designed to eliminate." |
| Unbounded spatial history or attribute maps | §M7 Performance: *"Unbounded history here is the most likely long-run memory leak in the entire platform, which is why bounding is a structural property rather than a tuning parameter."* |
| Block the hot path on durable writes | §M7: durable writes are *"batched and asynchronous"*. |
| Let the object population grow without limit | §M7: cap per camera; shed `provisional` first; alarm. *"A runaway registry is a memory leak with a face."* |
| Compute dwell from processing time | V11 and `14_TESTING` §4: dwell is computed from `t_capture`. |
| Implement a P11 resolver adapter | `15_ROADMAP` §3: *"already specified, **no implementations in Phase 1**"*. |
| Naive polygon tests per object per region | §M7: *"must not be naive at 100 objects × 20 regions"* — precomputed spatial index. |
| Repair a corrupted object silently | `10_RELIABILITY`; the brief. Unknown beats fabricated. |

---

## 10. Ambiguities found — resolved without inference

Three points required care. None is an architectural conflict; each is resolved by
reading the constitution more precisely.

### 10.1 `VisualObject` has no `regions` field, yet M7 owns region membership

`02_VOM` §10.6 lists no `regions` field. §M7 State Ownership explicitly includes
"region membership state, dwell accumulators". `07_STATE` §3.1's `ObjectState`
*does* have `regions`, but that is the L6 projection.

**Resolution:** M7 owns region membership as **partition state keyed by object**,
not as a field on the `VisualObject` record. This satisfies both documents and
obeys the brief's "do not invent new fields". Region occupancy is expressed
through `RegionState` (`07_STATE` §3.3), which M7 maintains and publishes.

### 10.2 P11 is both "an M7 port" and "unimplemented in Phase 1"

`06_PORTS` §2 assigns P11 to M7. `03_MODULES` §M7 extension points list
"spatio-temporal only" among resolver strategies. But `15_ROADMAP` §3 says
"**no implementations in Phase 1**".

**Resolution:** M7's responsibility 2 — "bind tracks to objects with method and
confidence; re-bind after breaks" — is *mandatory native M7 behaviour*, not an
extension. It must work with nothing bound. P11 is the seam for **replacing or
augmenting** it (appearance, cross-camera, learned), and ships with **no
implementations** and remains **unbindable**, exactly as `EmbeddingPort` did in
Flow 3. `15_ROADMAP` §3 confirms the shape: *"M7 already accepts identity
assertions from a resolver."*

### 10.3 Durable state without a Storage Interfaces module

§M7 Dependencies lists "Storage Interfaces (durable object state)". That is M12,
which belongs to Flow 6/7. `07_STATE` §9.3 nonetheless requires object identity to
survive restart.

**Resolution:** M7 defines its persistence needs behind a **port** and ships an
in-memory reference adapter plus a durable file-backed one, both dependency-free.
This is the same pattern Flow 1 used for `ConfigSourcePort` before any config
service existed. It does **not** implement M12, the observation log, or the Vision
State projection — only the narrow "persist and reload this partition's objects"
contract §M7 requires.

---

## 11. Compliance conclusion

The architecture specifies M7 completely enough to implement without inference.
Three ambiguities were found and each resolved by closer reading rather than by
invention. **No architectural conflict exists. No architectural change is
requested. Implementation may proceed.**
