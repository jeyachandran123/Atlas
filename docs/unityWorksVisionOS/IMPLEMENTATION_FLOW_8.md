# Implementation Flow 8 — M13 Storage Interfaces + M14 Observation API

**Status:** Complete — **Phase 1 is complete**
**Modules:** M13 Storage Interfaces (L6), M14 Observation API (L7)
**Ports realized:** P22 `EvidenceStorePort`, P31 `AuthorizationPort`, P32 `ApiTransportPort`; P20 completed with `tail`
**Compliance review:** [`FLOW_8_COMPLIANCE_REVIEW.md`](FLOW_8_COMPLIANCE_REVIEW.md) — completed before any code

---

## 1. Architecture Compliance Review

The full review is a separate document, completed **before** implementation as the
brief required. It answers the nineteen constitutional questions and resolves five
ambiguities, each from the architecture's own text:

| § | Ambiguity | Resolution |
|---|---|---|
| 20.1 | P20 lacks `tail`, which §M13 specifies | P20 is **M13's port**, and M13 is Flow 8's module. Flow 7 implemented the subset M12 needed; Flow 8 implements the subset M14 needs. Additive; Flow 7's behaviour unchanged. |
| 20.2 | P21 has two shapes for one port id | Flow 7 §14.2 already ruled: one contract, two consumers. And M13's StateStore has **no consumer** in Phase 1 — §M13 makes the projection *"rebuildable from log"*, which M12 already does. Implementing it would be implementing a contract nothing calls. |
| 20.3 | Who owns the demand registry — M14 or L3? | `01_LAYERED` §3.1: *"the API accepts demand contracts, which the Configuration/demand registry publishes as an event that the Crop Manager's trigger policy reads."* One registry, two roles. M14 owns intake and lifecycle; M8 reads. |
| 20.4 | Does §M14's evidence contract require binding P22? | P22 is **M13's port**. Flows 5–7 each deferred it as *"not this flow's job"*, never *"never"* — Flow 6's note reads *"persisting them is M13's job."* Flow 8 is M13. |
| 20.5 | `register_demand` is inbound — does that break read-only? | 09_API §1.1 lists five contracts and a sixth that *"does not exist"*. A demand changes **what the platform chooses to compute**, never a published fact. §M14: *"accept no writes to state."* |

**Conclusion: no architectural change was requested, and none was made.**

---

## 2. Implementation Report

### Files created

| File | Lines | Purpose |
|---|---:|---|
| `core/ports/persistence.py` | 438 | P22 with obligations E1–E7; erasure scopes, tombstones, retention policy |
| `core/ports/exposure.py` | 260 | P31 (Z1–Z6), P32 (T1–T6), audit sink, rate limits |
| `core/model/api.py` | 743 | 09_API's contract types — scope, filters, views, `Gap`, error envelope |
| `exposure/api.py` | 743 | M14 — query, subscribe, coverage, capability, evidence, demand |
| `exposure/subscriptions.py` | 499 | Fan-out, backpressure, the `Gap` contract |
| `exposure/demands.py` | 452 | Demand intake, durability, tenant ownership |
| `exposure/audit.py` | 206 | Who read what, with purpose binding |
| `adapters/persistence/evidence.py` | 465 | `evidence.memory`, `evidence.file`, `evidence.null` |
| `adapters/exposure/authorization.py` | 300 | `authz.static`, `authz.deny_all`, `authz.tenant_reads` |
| `adapters/exposure/transport.py` | 277 | `transport.in_process`, `transport.recording`, error rendering |
| `conformance/exposure_kits.py` | 516 | Three kits, 20 checks |
| `state/replay.py` | 304 | Replay verification and structural divergence reporting |
| `exposure_bootstrap.py` | 276 | The composition root for M13 + M14 |
| `system.py` | 356 | Whole-platform assembly, boot order, replay verification |

**Total: 5,835 lines of implementation.**

### Files modified

* `core/ports/synthesis.py` — P20 gains `tail` (obligation L7)
* `adapters/synthesis/stores.py` — `tail` on both log adapters
* `conformance/synthesis_kits.py` — L7 check; both adapters pass
* `state/manager.py` — `observations_in`, the L6→L7 read seam
* `core/errors.py` — 14 typed errors with stable API codes
* `kernel/config/schema.py` — `StorageSection`, `ApiSection`
* `kernel/plugins/manifest.py` — `FLOW8_PORTS`; 28 of 32 ports now bindable
* `kernel/metrics/names.py` — ~30 storage, API and replay metric names

### What was deliberately not built

Detection, tracking, identity resolution, crop generation, understanding, VLM
inference, semantic reasoning, alert generation, business logic, analytics,
learning, prediction, cross-camera identity, roadmap functionality. Each is
asserted mechanically in `test_exposure_architecture.py`.

**M13's StateStore ships no adapter**, because §M13 says *"implement none of it"*
and nothing in Phase 1 consumes one — see §12.2.

---

## 3. Module Interaction Report

```
L1 Acquisition → L2 Detection → Tracking → Registry → L3 Cropping
                                     │                     │
                                     ├──────────────┐      ↓
                                     ↓              │  L4 Understanding
                              L5 Observation Builder ←─────┘
                                     ↓
                              L6 Vision State ──→ ObservationLog (P20)
                                     ↓                EvidenceStore (P22)
                              L7 Observation API ──→ AuthorizationPort (P31)
                                     ↓                ApiTransportPort (P32)
                                 Consumer
```

**M14 reads exactly one collaborator: M12.** §M14's Dependencies name the Vision
State Manager, and the API is constructed with it plus an authorizer, an audit
trail, an optional evidence store and an optional camera directory. It never
receives the log, the builder, or any perception module —
`test_the_api_holds_no_write_capable_collaborator` asserts the slots.

| Seam | Direction | Mechanism | Added by |
|---|---|---|---|
| M12 → M14 | read | direct call on the state manager | Flow 8 |
| M11 → M14 | fan-out | a P19 sink, appended to M11's existing sinks | Flow 8 |
| M14 → demand registry | write | a record M8 reads at trigger time | Flow 8 |
| M13 ← M12 | durability | P20, P22 | Flows 7–8 |

**The demand path is the one edge that looks backwards, and it is not a call.**
`01_LAYERED` §3.2: *"the API writes a demand record; the Crop Manager reads demand
state at trigger time. **No call ever returns through the pipeline it entered.**"*
`test_the_demand_path_is_declarative_not_a_call` reads `exposure/demands.py` and
asserts no M8 symbol appears.

**The API fan-out is not a write path.** The observations already exist and are
already recorded; the hub delivers copies to subscribers. Its sink declares itself
**not durable** (obligation K5), because a connected dashboard must never be
mistaken for a system of record.

---

## 4. Observation API Ownership Report

| Artefact | Owner (sole writer) | Readers | May never modify |
|---|---|---|---|
| `Observation` | M11 | M12, M14, subscribers | **everyone**, including M14 |
| Observation log | M12 (append-only) | M12 rebuild, M14 history | everyone |
| `CameraPartition` | M12, one writer per camera | M14 through snapshots | M14 |
| `StateSnapshot` | M12 produces; nobody owns | consumers | frozen — nobody |
| Subscription session | **M14** | its own consumer | anyone else |
| Cursor | **M14** (per subscription) | the consumer holding it | another consumer |
| Rate-limit bucket | **M14** | — | anyone |
| Demand record | **M14** writes; M8 reads | M8's trigger policy | M8 never writes |
| Demand tenancy | **M14** | — | nothing below L7 |
| Audit record | **M14** | an external audit sink | M14, after writing |
| `Principal` | the transport establishes | M14 | anything below L7 |

### What M14 owns, and what it does not

§M14 State Ownership: *"Owns: subscription sessions, cursors, rate-limit buckets,
the demand registry, version negotiation state. **Owns no visual state.**"*

That last sentence is the whole report. M14 holds no object, no observation, no
partition — only the machinery of serving them. Everything it returns is
constructed at request time from an immutable snapshot it did not create.

### Where ownership does *not* transfer

Nowhere. **Flow 8 adds no ownership transfer**, which is the point of an exposure
layer. A consumer receives *views* — `ObjectView`, `Page`, `EvidenceView` — that are
constructed from state and own nothing. `object_view_of` is the single place the
internal and external representations meet, so a field added to `ObjectState` is
invisible until somebody deliberately exposes it. That is `01_LAYERED` §1.2's
*"internal representation evolve[s] while the contract holds"* made mechanical.

### Who may never modify what

* **M14 may never write to Vision State.** No method exists;
  `test_no_exposure_module_calls_a_state_mutator` parses the AST for calls to
  `append`, `rebuild`, `forget`, `resume` and `retention_sweep` on a state object.
* **M14 may never construct an observation.** It would become a second producer,
  and V4's provenance chain would terminate in *"a consumer asked for it"*.
* **A consumer may never modify anything.** Every contract type is frozen.
* **M8 may never write a demand.** It reads demand state; intake is M14's.
* **A transport may never interpret** (T2). It translates shapes, not meanings.

### Where external identity exists

Exactly one place. 12_SECURITY §5.1: *"External identity exists only at the
Observation API... There is no ambient user context inside the pipeline, which
means no pipeline component can accidentally make an authorization decision."*
`Principal` is constructed by the transport, used by M14, and travels nowhere
downward.

---

## 5. Persistence Ownership Report

| Contract | Port | Owner of the data | Owner of the contract | Bound in |
|---|---|---|---|---|
| ObservationLog | P20 | the adapter | M13 | Flow 7, completed Flow 8 |
| StateStore | P21 | the adapter | M13 | Flow 4 (object population); **no projection adapter** |
| EvidenceStore | P22 | the adapter | M13 | **Flow 8** |
| ConfigStore | P23 | the adapter | M13 | Flow 1 |
| ArtifactStore | P25 | the adapter | M13 | Flow 2 |

**M13 owns no state.** §M13: *"Owns no state — it is a set of contracts. Adapters
own their own storage."* Nothing in `core/ports/persistence.py` writes a byte.

### The five contracts stay separate

§M13: *"Conflating them is the reason storage becomes un-portable."*
`test_storage_contracts_stay_separate` asserts an evidence store has no `append`,
`read`, `position` or `truncate`, and a log has no `erase`, `expire` or `exists`.

The retention consequence is the sharpest reason: 07_STATE §8.1 gives evidence
24–72 hours and the log 7 days to years, so a shared store would force imagery to
inherit the log's retention. `test_evidence_and_log_retention_are_separately_configurable`
asserts the two configured defaults differ.

### Evidence: four absence states, never three

| State | Meaning | Operator's response |
|---|---|---|
| `STORED` | present | — |
| `NOT_FOUND` | never written | **a bug** in whatever minted the reference |
| `EXPIRED` | retention ran | normal; nothing to do |
| `ERASED` | a subject exercised a right | audit answers *by whom, under what authority* |

§M13: *"Collapsing these two is how retention behaviour becomes indistinguishable
from data loss."* The type enforces it: `EvidenceFetch` refuses to report `STORED`
with no payload, and refuses to carry a payload with any other status.

### Erasure tombstones, never rewrites

07_STATE §8.2's resolution of V5 versus regulation:

> *"erasure removes evidence blobs and redacts identifying content, while
> retaining an immutable tombstone record that an observation existed and was
> erased, by whom and under what authority. The audit trail survives; the content
> does not."*

`EvidenceTombstone` refuses to be constructed without an authority — an anonymous
erasure is not an audit trail. `EraseScope` refuses to be constructed without a
tenant, and without at least one of objects, cameras or a time window: *"erase
everything for this tenant"* is a deployment decision, not an API call.

**Erasure by subject is not expressible**, and that is deliberate. §8.2: *"by
default UWV holds no persistent biometric identity, which is a deliberate privacy
posture, not a limitation."* There is no field on `EraseScope` that could name a
person, because there is nothing in the platform to name them with.

### `never_persist` stores nothing

12_SECURITY §2.3's no-evidence mode is a hard guarantee. Every shipped adapter
honours it by **not writing**, and the conformance kit checks it — including that
a file store leaves no file on disk. An adapter that stored it anyway would void a
deployment's privacy posture invisibly.

---

## 6. Replay Verification Report

**Every partition rebuilds identically from the log, and the comparison is strong
enough to notice if it did not.**

### No shortcut exists, structurally

`replay_partition` calls **the same `project` function** the live write path calls,
over the same log, into a fresh partition. `test_replay_calls_the_same_projection_the_live_path_calls`
asserts it; `test_there_is_exactly_one_projection_function` asserts there is only
one to call. A faster path that approximated the projection would be a second
definition of what an observation means to state, and two definitions diverge —
quietly, because the projection is the only other copy.

`test_replay_reads_the_log_and_nothing_else` asserts the replay never touches live
state: validating state against itself proves nothing.

### What the comparison checks

| Compared | Why |
|---|---|
| object set | a missing or extra object is the loudest failure |
| `class_id`, `lifecycle` | what the thing is, and whether it is present |
| `first_seen`, `last_seen` | when it was known |
| **`last_confirmed`** | measured versus believed (V8) |
| `observation_count`, `measurement_basis` | provenance of the current value |
| attribute keys **and values** | the semantic payload |
| region membership | spatial state |
| observability status | including *absence* of one |

### What it deliberately does not check

`version` and `log_position`. A replay performs a different number of writes and
may start partway through the log. Reporting those would make every successful
replay look like a failure, and a test that always fails is a test that gets
deleted. `test_bookkeeping_differences_are_not_reported` pins that decision.

### Proof the comparator works

Four tests damage a partition deliberately — remove an object, drift a timestamp
by one nanosecond, change an attribute value, empty the projection — and assert
the divergence is found and **named down to the field**. A verifier that could not
detect a divergence would prove nothing.

### Recovery scenarios exercised

| 07_STATE §9.1 scenario | Test | Result |
|---|---|---|
| State store corruption | `test_state_store_corruption_rebuilds_with_no_loss` | no loss |
| Projection bug | `test_a_projection_bug_is_fixed_by_a_rebuild` | no loss |
| Partition writer crash | `test_replay_from_a_watermark_resumes_rather_than_restarting` | resumes |
| Cold start | `test_an_empty_partition_replays_to_an_empty_projection` | distinguishable from failure |

### End to end

`test_state_replays_identically_after_a_full_run` boots the whole platform, runs
real frames through all eight layers, and replays the resulting log. Not synthetic
observations — the real log, the real projection.

### Auditability

`deterministic_digest` fingerprints a log's semantic content and **excludes
`t_published`**: when the platform said something is not part of what it said, and
a replay legitimately publishes at a different wall time. It detects a changed
class; it ignores a re-publication.

---

## 7. Dependency Graph

```
              core/model/{api, observation, vision_state, ids}
                                   │
        core/ports/{persistence (P22), exposure (P31,P32), synthesis (P20)}
                                   │
      ┌────────────────────────────┼────────────────────────────┐
      │                            │                            │
  exposure/                    state/                   adapters/
  ├── api.py                   ├── projection.py        ├── persistence/evidence.py
  ├── subscriptions.py         ├── manager.py           └── exposure/{authorization,transport}.py
  ├── demands.py               └── replay.py                        │
  └── audit.py                      │                               │
      │                             │                               │
      └──────── exposure_bootstrap.py ───────────────────────────────┘
                          │
                      system.py   ← the only module that knows the whole shape
```

**Verified mechanically:**

* `exposure/` imports no perception module, no acquisition module, and not even
  `synthesis` — only `state`, `core` and `kernel`.
* No lower layer imports `exposure`. The guard parses **imports**, not the word:
  `reject_extreme_exposure` is a photographic quality grade in M8's crop gate, and
  a substring guard flagged it (§12.5).
* `state/` imports no adapter. Which store satisfies P20 is the composition root's
  call.
* `exposure/demands.py` imports `DemandRegistry` as a **type** and calls no M8
  method.

**New external dependencies: none.** Standard library only.

---

## 8. Runtime Integration Report

### Boot order, implemented literally

08_RUNTIME §7.1 steps 9–11, in `VisionSystem.boot`:

1. synthesis runtime starts
2. understanding, cropping, registry, tracking runtimes start
3. **the API is serving** — step 9
4. cameras attach — step 10

> §7.1: *"Step 9 precedes step 10: the API serves recovered state before cameras
> attach, so consumers reconnecting after a deployment get valid (if briefly
> stale) answers rather than errors."*

`test_the_api_serves_before_cameras_attach` queries between boot and the first
frame and asserts the result is an **answer** — empty, with coverage — rather than
an error.

**Shutdown drains in reverse:** cameras first, the API last. A consumer should keep
receiving answers while there is state to answer from.

### The restart gap

07_STATE §9.3 requires the restart window be *"recorded as a coverage observation,
so consumers see the discontinuity as data rather than inferring it from a
suspicious silence."* `record_restart_gap` publishes `BLIND` / `RESTART`, and is
called by an operator rather than automatically — a first-ever start is not a
restart, and recording a gap before there was anything to interrupt would put a
fiction in the log.

### Backpressure

09_API §3.4 forbids three things, and each is **unrepresentable** rather than
merely avoided:

| Forbidden | Why it cannot happen |
|---|---|
| Unbounded buffering | every queue has a capacity checked at construction; `queue_capacity=0` raises |
| Silent drop | every drop path constructs a `Gap` before discarding |
| Stalling the platform | `publish` never blocks and never awaits a consumer |

`OverflowPolicy` has exactly three members — conflate, drop-with-gap, disconnect —
so an unbounded option cannot be configured.

### Concurrency

Subscriptions hold per-connection locks; the hub holds one lock for its index.
**No cross-camera synchronisation** is introduced: the API reads immutable
snapshots, so §M14's *"no locking exists on the read path at all"* holds. Rate-limit
buckets are per principal, per bucket.

### Health

`VisionSystem.health()` reports one line per layer plus `layers`, naming which
layers `boot` actually started — see §12.4.

---

## 9. Performance Report

Measured as **shape**, not wall-clock: an absolute budget on a shared CI box
measures the box.

| Property | Result | Where |
|---|---|---|
| Query path | snapshot-based; no lock on the read path | §M14 Thread Safety, by construction |
| Snapshot cost | O(1) — inherited from Flow 7's structural sharing | Flow 7 §10 |
| Subscription fan-out | filters evaluated once per observation against an index keyed by type and camera | `SubscriptionHub._candidates` |
| Subscriber queue | bounded at configured capacity under 100× overload | `test_a_slow_subscriber_never_grows_past_its_capacity` |
| Gap merging | 50 dropped messages produce **one** gap | `test_consecutive_drops_merge_into_one_gap` |
| Evidence dedup | identical bytes stored once per tenant | `test_evidence_deduplicates` |
| Evidence quota | write refused at the bound, systemically | `test_a_store_refuses_beyond_its_quota` |
| Audit buffer | bounded ring; total counted separately from retained | `CountingAuditSink` |
| Recording transport | bounded history | `test_a_recording_transport_keeps_a_bounded_history` |
| Replay | real 8-layer log replayed and compared field by field | `test_state_replays_identically_after_a_full_run` |

**Every unbounded structure that could exist here is bounded**: subscription
queues, audit rings, transport recordings, evidence blobs and bytes, page sizes,
query windows, subscriptions per principal. §M14's failure table requires it —
*"Reject with a bound and a cursor rather than degrading the service for
everyone"* — and an unbounded buffer in a long-running process grows fastest
exactly when the platform is busiest.

### Rate limits, by design asymmetric

Evidence gets a tighter budget than queries (60/min against 600/min) because
09_API §6 calls evidence payloads *"large and sensitive"*: a consumer able to pull
imagery as fast as facts has effectively been granted bulk imagery export.

---

## 10. Test Report

**200 Flow 8 tests, all passing. 86% coverage of Flow 8 modules.**
**2,647 Vision OS tests total, 0 failures, 0 skips.**

| File | Lines | Tests | Categories |
|---|---:|---:|---|
| `test_observation_api.py` | 534 | 35 | API, Unit, Integration |
| `test_exposure_architecture.py` | 493 | 35 | Architecture, Conformance |
| `test_storage.py` | 365 | 34 | Storage, Unit |
| `test_demands_and_transport.py` | 435 | 31 | API, Integration, Recovery |
| `test_replay.py` | 339 | 22 | Replay, Snapshot, Recovery |
| `test_subscriptions.py` | 295 | 22 | Subscription, Concurrency, Stress |
| `integration/test_full_system.py` | 460 | 21 | End-to-end, Integration |

All fifteen required categories are covered: Unit, Integration, Architecture,
Replay, Snapshot, Recovery, Storage, API, Subscription, Concurrency, Stress,
Performance, Conformance, Regression, End-to-End.

### Coverage by module

| Module | Coverage |
|---|---:|
| `exposure/demands.py` | 95% |
| `core/ports/exposure.py` | 94% |
| `state/replay.py` | 93% |
| `core/ports/persistence.py` | 90% |
| `core/model/api.py` | 89% |
| `system.py` | 87% |
| `exposure/audit.py` | 86% |
| `exposure/subscriptions.py` | 86% |
| `conformance/exposure_kits.py` | 86% |
| `exposure/api.py` | 85% |
| `adapters/exposure/transport.py` | 85% |
| `exposure_bootstrap.py` | 85% |
| `adapters/exposure/authorization.py` | 74% |
| `adapters/persistence/evidence.py` | 68% |

The two lowest are reference adapters whose uncovered branches are alternate
storage backends and grant shapes a deployment would replace; both pass their
conformance kits in full.

### Conformance results

All eight shipped Flow 8 adapters pass, and P20's new L7 check passes on both log
adapters:

```
evidence.memory        PASS      authz.static           PASS
evidence.file          PASS      authz.deny_all         PASS
evidence.null          PASS      authz.tenant_reads     PASS
transport.in_process   PASS      transport.recording    PASS
log.memory (L7)        PASS      log.file (L7)          PASS
```

### The wider Atlas suite

933 non-Vision-OS tests pass; 82 failures and 32 errors exist in unrelated
subsystems (auth, git API, chat, memory, chunker, vision service). **None touches
Vision OS** — verified by matching every failing node id. Identical to the
pre-Flow-8 baseline.

---

## 11. Architectural Discoveries

Six defects were found by tests during this flow. Each is recorded with what it
would have cost.

### 11.1 A real tenant leak in `query_state`

`_matches` took a `tenant_id` parameter **and never used it**, and `_cameras_in`
fell back to *every partition on the node* when a scope named no cameras. A
multi-tenant deployment would have served one tenant's objects to another.

The fix was not to add a filter — that would be exactly the post-filtering
12_SECURITY §4.2 forbids. §4.1 says *"Partitions are tenant-scoped"*, so the camera
list a query is **built from** is the tenant boundary. `_cameras_in` now resolves
the tenant's cameras from the Camera Manager (§M14's declared dependency), and
`_matches` does content filtering only, with a comment saying why a tenant check
there would be a defect rather than a safeguard.

**Cost if shipped:** cross-tenant data disclosure — the single worst failure in
12_SECURITY's threat model.

### 11.2 `record_restart_gap` claimed the opposite of what it meant

It published `OBSERVING` with reason `RESTART`. The coverage model refused to
construct it: *"a camera that is observing has no observability problem to name."*
A restart is a window during which the platform **could not see**, so the status is
`BLIND`.

**Cost if shipped:** the model caught it, so nothing. Worth recording because the
type system rejected a sentence that read perfectly well in English — an invariant
enforced in a constructor caught an error a reviewer would likely have passed.

### 11.3 Demand reconstruction silently restored nothing

`_demand_of` omitted `subject_filter`, a required field, and the `except
(TypeError, ValueError): return None` swallowed it. Every restart would have come
up with an **empty** demand registry, and §M14 warns exactly what that costs:
*"attribute coverage would silently lapse in the interval."*

The broad catch is still correct — one unreadable demand should cost one consumer a
re-registration, not cost every consumer theirs — but it is also a hiding place,
and the code now says so. Only a test asserting the **count** found it.

**Cost if shipped:** every deployment would quietly stop enriching attributes
after a restart, and the platform would look like it was working.

### 11.4 A demand could be registered in another subscriber's name

`register` never checked that `demand.subscriber` matched the registering
principal. `list_demands` would have shown a consumer demands it never made, and
`_require_owner` — the check guarding revocation — would have guarded nothing,
since anyone could claim any subscriber id.

### 11.5 An omitted layer was silently inert

`VisionSystem.boot` starts whatever layers it was given, and `assemble` takes each
as optional so a deployment can run L1–L5 without exposure. The cost of that
flexibility is that omitting one **by accident** looks exactly like omitting it on
purpose: a test that forgot to pass `tracking` produced a platform that booted
cleanly, reported healthy, and published nothing.

`boot` now records what it started, and `health()` reports it. The flexibility is
kept; the silence is not.

### 11.6 A property that raised made the object un-introspectable

`ObservationApi.demands` raised when no registry was configured. `dir()`, a
debugger and a pytest repr all evaluate properties, so one missing optional
collaborator turned every inspection into an exception. The property now returns
`None`; the four §M14 demand methods raise a typed error at the point of use.

### 11.7 Two architecture guards were too crude

`"exposure" in text` flagged `reject_extreme_exposure` — a photographic quality
grade. `"REST"` matched `restart` and `restoring`. Both were sharpened to parse
imports and match whole identifiers. A guard with false positives is one people
learn to work around, which is worse than not having it.

---

## 12. Known Limitations

Recorded rather than hidden.

1. **M13's StateStore has no projection adapter, deliberately.** §M13 says
   *"implement none of it"*, its own table makes the projection *"rebuildable from
   log"*, and 07_STATE §9.1 makes state-store corruption a no-data-loss scenario
   *because* rebuild is the recovery. M12 holds its projection in memory and
   rebuilds from the log — the architecture's own path, complete. Shipping an
   adapter would be implementing a contract nothing calls. A deployment wanting a
   warm-start cache binds one; the contract is documented.

2. **`ObservationApi` needs a Camera Manager for multi-tenant scoping.** Without
   one it falls back to every partition, which is correct for the single-tenant
   embedded case and **not** safe on a multi-tenant node. `build_exposure_layer`
   does not require one today. A multi-tenant deployment must pass
   `cameras=platform.cameras`; this should become mandatory when a multi-tenant
   profile exists.

3. **`resume_from` is honoured at subscription setup, not replayed from the log.**
   §3.2 promises a reconnecting consumer *"receives everything since that cursor,
   bounded by log retention"*. P20 now has `tail` to make that possible, but the
   subscription hub does not yet backfill on reconnect — a consumer must call
   `query_observations` over the gap window. The `Gap` message reports
   `recoverable: true` precisely so it can.

4. **Version negotiation serves one major.** §7.1 requires *"two adjacent majors
   concurrently"* during a migration. `SUPPORTED_MAJORS` is a frozenset so the
   second costs nothing to add, but no v2 exists and no dual-serving path is
   exercised.

5. **A false durability claim is still not mechanically detectable** — carried
   forward from Flow 7, and now also true of P22. An adapter declaring
   `durable = True` while keeping nothing passes its kit. Verifying it needs a
   power cut.

6. **The audit sink is bounded and in-memory by default.** `CountingAuditSink`
   keeps 1,000 records with a separately-reported total. A deployment with real
   audit obligations binds an append-only external sink; `NullAuditSink` exists so
   *"no audit"* is a stated choice rather than an empty tuple nobody noticed.

7. **`FileEvidenceStore` rebuilds its index by scanning on first touch.** A
   one-time O(n) startup cost. A production adapter would keep an index; this one
   derives it from the records rather than from a sidecar that could disagree.

8. **Rate limiting is per-process.** A clustered deployment needs a shared bucket
   store; the current implementation would allow N× the configured rate across N
   nodes.

9. **The demand lifecycle notifications of §4.4 are not wired to subscribers.**
   The registry supports throttle, restore and mark-unsatisfiable, but a consumer
   learns of a transition by polling `list_demands` rather than by being told.

---

## 13. Future Extension Points

| Extension | Seam | Notes |
|---|---|---|
| **HTTP / gRPC / message-bus transport** | P32 `ApiTransportPort` | Implement three members and a route table. §M14: *"adopting a new transport in 2031 will not be a platform change."* |
| **RBAC / ABAC authorization** | P31 `AuthorizationPort` | 12_SECURITY §5.2's `(action, resource_scope, conditions)` — conditions are where a policy engine earns its place. |
| **Encrypted / tiered evidence** | P22 `EvidenceStorePort` | §M13: *"tiered storage (hot local → warm object store → cold archive); encryption at rest per privacy class; regional pinning."* |
| **Replicated observation log** | P20 `ObservationLogPort` | §9.1: *"log replication is mandatory in any deployment claiming durability."* |
| **Projection-backing StateStore** | P21 | Contract documented; no consumer in Phase 1. |
| **Subscription backfill on reconnect** | P20 `tail` | The port method exists; the hub needs to call it. |
| **Two concurrent API majors** | `SUPPORTED_MAJORS` | A frozenset, not a constant. |
| **Richer query languages** | §M14 Extension Points | *"structured filters today; richer spatial-temporal query later."* |
| **M10 Prompt Manager** | P17 `PromptSourcePort` | Unimplemented across all eight flows; M9 consumes prompts through a module seam. |
| **Cross-camera identity** | P11 `IdentityResolverPort` | Phase 2, C2, policy-gated. Permanently guarded. |
| **Learning pipeline** | P19 `ObservationSinkPort` | 15_ROADMAP §2: *"Evidence retention (V4) is exactly the training data."* |

---

## 14. Final Verification

| Requirement | Status | Evidence |
|---|---|---|
| Flow 1 unchanged | ✅ | 2,647 tests pass; no acquisition or kernel module touched except additive config sections and metric names |
| Flow 2 unchanged | ✅ | detection untouched |
| Flow 3 unchanged | ✅ | tracking untouched |
| Flow 4 unchanged | ✅ | registry untouched; `ObjectStorePort` unchanged |
| Flow 5 unchanged | ✅ | cropping untouched; the demand registry gained a writer, not an edit |
| Flow 6 unchanged | ✅ | understanding untouched |
| Flow 7 unchanged | ✅ | additive only: P20 gained `tail` (M13's port, Flow 8's module) and M12 gained one read method, both asserted non-writing |
| Observation Log remains the system of record | ✅ | `test_observations_are_recorded_before_they_are_served` |
| Vision State remains a projection | ✅ | rebuilt from the log in every recovery test |
| Observation remains the only write path | ✅ | `test_no_exposure_module_calls_a_state_mutator` |
| Replay reconstructs identical state | ✅ | field-by-field comparison, end to end |
| API is read-only | ✅ | structurally and behaviourally |
| Storage remains replaceable | ✅ | three evidence adapters, all kit-gated |
| No perception logic in the API | ✅ | `test_exposure_performs_no_perception` |
| No business logic | ✅ | `test_exposure_performs_no_business_reasoning` |
| No analytics | ✅ | `test_exposure_computes_no_analytics` |
| No roadmap functionality | ✅ | four ports permanently unbindable |
| Every adapter satisfies its kit | ✅ | 8 Flow 8 adapters + 2 log adapters on L7 |
| Every invariant intact | ✅ | V1–V13, mechanically guarded |
| `ruff check` clean | ✅ | All checks passed |

---

## 15. Summary — Phase 1 Complete

Flow 8 implements M13 Storage Interfaces and M14 Observation API, assembles every
module into one deployable platform, and proves the guarantee everything else
rests on.

**M13 defines and implements none of it.** Five durability contracts stay
separate because conflating them is what makes storage un-portable — most sharply
for evidence, whose 24–72 hour retention is a privacy decision that must never
inherit the log's years.

**M14 serves facts and produces nothing.** There is no write path into Vision
State — not guarded, but absent. Scope is constructed rather than post-filtered,
coverage accompanies every answer unconditionally, and a subscriber is never
silently skipped.

**Replay reproduces the world.** The same projection, the same log, compared field
by field — and the comparator is proved able to detect a one-nanosecond drift.

Six defects were found by tests, including a real cross-tenant leak and a restart
gap that claimed the platform could see while it could not. Each was fixed at its
cause.

**5,835 lines of implementation. 200 tests across all fifteen required
categories. 86% coverage. 2,647 Vision OS tests passing. 28 of 32 ports bound;
the four that remain are what Phase 1 deliberately omits.**
