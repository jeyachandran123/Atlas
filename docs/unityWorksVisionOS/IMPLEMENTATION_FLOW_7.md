# Implementation Flow 7 — M11 Observation Builder + M12 Vision State

**Status:** Complete
**Modules:** M11 Observation Builder (L5 Synthesis), M12 Vision State (L6 State)
**Ports realized:** P18 `SuppressionPolicyPort`, P19 `ObservationSinkPort`, P20 `ObservationLogPort`
**Compliance review:** [`FLOW_7_COMPLIANCE_REVIEW.md`](FLOW_7_COMPLIANCE_REVIEW.md) — completed before any code was written

---

## 1. Architecture Compliance Review

The full review is a separate document, as the brief required it be completed
**before** implementation. It answers the sixteen constitutional questions and
resolves five ambiguities, each in favour of the architecture and using the
architecture's own words:

| § | Ambiguity | Resolution |
|---|---|---|
| 14.1 | M12 depends on M13, which is out of scope | §M13's own words: *"Describe what must persist and with what guarantees; **implement none of it**."* It owns no state and is *"a set of contracts"*. Realizing P20 as a protocol plus a reference adapter is not implementing M13. Precedent: Flow 2 (P25–P27), Flow 4 (P21). |
| 14.2 | P21 has been bindable since Flow 4 for the object store | One contract, two legitimate consumers. No new port, no changed binding. |
| 14.3 | The envelope needs signals from five modules and no seam has all of them | §M11's API is **six distinct builders**, and 02_VOM §11.2 assigns different content to different types. The shape of the API is the answer. |
| 14.4 | `Evidence.observation_id` was deliberately omitted in Flow 6 | M9 may not mint an id for an object it is forbidden to create. M11 mints it and stamps it — the promised half of a two-part construction. |
| 14.5 | M11 emits coverage observations while M12 holds coverage state | §7.3: coverage is *"both live state and historical observations"*. M11 emits, M12 projects. |

**Conclusion: no architectural change was requested, and none was made.**

---

## 2. Implementation Report

### Files created

| File | Lines | Purpose |
|---|---:|---|
| `core/model/observation.py` | 675 | The Observation Envelope (02_VOM §11): seven types, violation taxonomy, evidence, coverage windows |
| `core/model/vision_state.py` | 564 | 07_STATE §3's projection types: `ObjectState`, `RegionState`, `CameraPartition`, `StateSnapshot` |
| `core/ports/synthesis.py` | 250 | P18, P19, P20 with obligations S1–S7, K1–K5, L1–L6 |
| `synthesis/builder/engine.py` | 764 | M11 — the seven builders, envelope assembly, evidence completion |
| `synthesis/builder/validation.py` | 297 | The final ceiling gate; the two-response asymmetry |
| `synthesis/builder/suppression.py` | 170 | Bounded per-camera suppression state |
| `synthesis/runtime.py` | 512 | Both seams; per-camera serialization; block-not-drop commit |
| `state/projection.py` | 531 | The pure fold: `(partition, observation) -> partition` |
| `state/manager.py` | 840 | M12 — log-then-project, snapshots, rebuild, the durability ladder |
| `adapters/synthesis/stores.py` | 513 | `InMemoryObservationLog`, `FileObservationLog`, `CollectingSink`, `NullSink` |
| `adapters/synthesis/suppression.py` | 233 | `ExactSuppression`, `ThresholdSuppression`, `AlwaysPublish` |
| `adapters/synthesis/decode.py` | 250 | Log rehydration, with its losses documented in one place |
| `conformance/synthesis_kits.py` | 545 | Three kits, 22 checks |
| `synthesis_bootstrap.py` | 329 | The composition root — the only module that selects an adapter |

**Total: 6,473 lines of implementation.**

### Files modified

* `core/model/ids.py` — added `ObservationId` (time-sortable ULID), `LogPosition`, `PartitionVersion`
* `core/errors.py` — added nine typed errors from `ObservationError` and `StateError`
* `kernel/config/schema.py` — added `SynthesisSection` and `StateSection`
* `kernel/config/manager.py` — accessors and effective-config wiring
* `kernel/events/events.py` — six events including `ObservationRejected`, `PartitionDegraded`
* `kernel/metrics/names.py` — ~25 metric names
* `kernel/plugins/manifest.py` — `FLOW7_PORTS`; `BINDABLE_PORTS` extended
* `core/model/understanding.py` — additive: `demand_ids` on `UnderstandingResult`
* `perception/understanding/engine.py` — populates `demand_ids` from the request

### What was deliberately not built

Detection, tracking, cropping, understanding, prompt generation, model selection,
inference, business reasoning, alert generation, prediction, learning, executive
decisions, cross-camera identity, analytics, reporting. Each is asserted
mechanically in `test_synthesis_architecture.py`, not merely avoided.

---

## 3. Engine Interaction Report

```
M7 Object Registry ──(RegistryUpdate)──┐
                                        ├──> SynthesisRuntime ──> ObservationBuilder ──> VisionStateManager
M9 Understanding ──(UnderstandingResult)┘         (M11)                  (M11)                  (M12)
                                                                            │
                                                                            └──> ObservationSinkPort (P19)
```

**Two seams, and the difference is architectural.** `01_LAYERED` §3.1's dotted
edges say registry results become observations *without passing through
understanding* — *"Understanding is enrichment, not a toll gate."* Wiring
synthesis only to M9's output would have made presence depend on inference. The
end-to-end test proves the consequence: a stack with **no understander bound at
all** still records what it saw.

| Seam | Producer | Payload | Observation types |
|---|---|---|---|
| `on_registered` | M7 | `RegistryUpdate` | presence, spatial, lifecycle, quality |
| `on_understood` | M9 | `UnderstandingResult[]` | attribute |
| `publish_coverage` | runtime supervisor | observability change | coverage |

Neither producer knows M11 exists. Each holds a callable assigned by the
composition root; `test_earlier_flows_never_learn_synthesis_exists` reads the
registry runtime's own source and asserts the words are absent.

**Both seams are firewalls.** V9 says a failure at L5 may not stop L2, so
`on_registered` and `on_understood` never raise: an unhandled exception degrades
health and returns.

---

## 4. Observation Ownership Report

The brief asked this to be documented explicitly. Ownership means: who may
create it, who may read it, who may never modify it.

| Artefact | Owner (sole writer) | Readers | May never modify |
|---|---|---|---|
| `UnderstandingResult` | **M9** | M11 | M11, M12, everyone downstream |
| `UnderstandingEvidence` | **M9** (all fields except `observation_id`) | M11 | anyone |
| `Evidence` (complete) | **M11** (stamps `observation_id` only) | M12, M14 | M12, M14 |
| `Observation` | **M11** | M12, P19 sinks, M14 | everyone, including M11 after publication |
| Observation log (P20) | **M12** (append-only) | M12 rebuild, history queries | everyone; no deletion path exists |
| `CameraPartition` | **M12**, one writer per camera | any reader, through snapshots | everyone else |
| `StateSnapshot` | **M12** produces; nobody owns | consumers | it is frozen — nobody |
| Suppression state | **M11**, per camera | nobody | M12 never sees it |

### Where ownership transfers

There are exactly **three** transfer points.

1. **M9 → M11**, at `SynthesisRuntime.on_understood`. M9's result becomes M11's
   input. M11 never writes back; the result is frozen. The evidence record is
   *completed* here rather than modified: `_complete_evidence` constructs a new
   `Evidence` carrying M9's fields plus the freshly minted `ObservationId`. M9
   could not have filled that field — it may not mint an identifier for an object
   it is forbidden to create — so this is the second half of a construction the
   architecture split deliberately.

2. **M11 → M12**, at `VisionStateManager.append`. The observation becomes part of
   the permanent record. M11 retains no reference it could mutate; the type is
   frozen and slotted, so it could not mutate one if it did.

3. **M12 → the log**, at `ObservationLogPort.append`. After this the record is
   outside the process. Nothing in the platform can edit it: P20 has `append`,
   `read`, `position` and `truncate`, and `truncate` removes a time-bounded
   *prefix* under a retention policy — it cannot target a record.

### Who may never modify what

* **M11 may never modify an observation after publishing it.** A correction is a
  new observation carrying `supersedes`.
* **M12 may never modify an observation at all.** It appends and projects. The
  projection is a *derived* value; changing it changes nothing about the record.
* **No module may modify Vision State except through an observation.** The
  manager's only public mutator is `append`; `test_appending_observations_is_the_only_public_mutator`
  enumerates the public surface and asserts it.
* **M11 may never mint an `ObjectId`.** The architecture guard on `ObjectId(...)`
  call sites (Flow 4's, still enforced) covers the synthesis package. Attribute
  observations name the id M7 minted, which travelled through the crop and the
  request.

---

## 5. Observation Lifecycle Report

```
   signals arrive          assembled           validated          suppressed?         committed
  ┌───────────────┐    ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
  │ RegistryUpdate│───>│  _envelope   │──>│ CeilingGate  │──>│ P18 policy   │──>│ log → project│
  │ or M9 result  │    │              │   │  .validate   │   │              │   │              │
  └───────────────┘    └──────────────┘   └──────┬───────┘   └──────┬───────┘   └──────────────┘
                                                 │                  │
                                    envelope violation      nothing new
                                                 │                  │
                                                 v                  v
                                      raise + ObservationRejected   return None
                                          (loud, counted)           (success, counted)
```

1. **Assembly.** `_envelope` builds one candidate from the signals available at
   this seam. `taxonomy_version` comes from the *context*, never from the
   producer — the point of the mismatch check is to catch a producer that
   believes something different from the site.

2. **Validation, then suppression, in that order.** A rejected observation must
   not update the suppression signature: if it did, the next *valid* observation
   of the same content would be suppressed against a fact that was never
   published, and the subject would go silent for a reason nobody could find.

3. **Two failures, two responses** (§M11's failure table):
   * *Attribute not in the registry* → drop the attribute, keep the observation.
   * *Envelope incomplete* → reject entirely, raise, alarm.

   An attribute observation whose every attribute was dropped returns `None` — the
   ceiling working, not the platform breaking. Conflating these was a real defect
   found during testing; see §12.

4. **Suppression.** `None` means *nothing changed*, which is a success. §M11 puts
   the reduction at 10–50×; the heartbeat is what makes it safe (V8), and
   coverage, lifecycle and identity observations are never suppressible by any
   policy.

5. **Publication.** The observation is appended to the log, then projected, then
   fanned out to sinks. It is now permanent.

6. **Correction.** Never an edit. A new observation carries `supersedes`; the
   original stays readable. `Observation` refuses to supersede itself and refuses
   a lineage cycle, because a graph that cannot be walked to an origin is not an
   audit trail.

7. **Expiry.** Retention is a time policy applied to the log by `truncate`. No
   content-based deletion exists — choosing which facts matter is a business
   judgement the platform may not make.

---

## 6. Vision State Lifecycle Report

```
  append(observations)
        │
        ├─ 1. log.append(camera, batch)      ← the log is authoritative (§9.1)
        │        └─ on failure: buffer, then HALT (10_RELIABILITY §4.4 step 4)
        │
        ├─ 2. project(partition, observation) → new partition   ← pure fold
        │        └─ on ProjectionError: quarantine one, continue, alarm
        │
        ├─ 3. atomic swap of the partition value
        │
        └─ 4. notify subscribers with a StateDelta
```

**Log first, project second.** A projection that ran before a failed append would
leave state holding something the log does not, and §9.1 makes the log
authoritative — a rebuild would then silently produce a different world.

**Structural sharing.** Every partition is a frozen value, so a snapshot is a
pointer, not a copy. `test_a_snapshot_is_constant_time` measures the ratio rather
than a millisecond budget: 64× the objects must not cost 8× the snapshot.
`test_an_unchanged_object_is_shared_rather_than_copied` asserts object *identity*,
which is the mechanism behind the claim.

**Rebuild.** A shadow partition is built from the log and swapped atomically. A
reader holding a snapshot across a rebuild sees the old world whole — a partial
swap would expose a state that never existed.

**Degradation ladder** (10_RELIABILITY §4.4):

| Step | Condition | Response |
|---|---|---|
| 1 | store slow | batch larger |
| 2 | store slower | buffer locally |
| 3 | buffer filling | `PartitionDegraded` event, metrics |
| 4 | buffer full | **stop accepting observations** |

Step 4 halts loudly rather than dropping, because *"losing observations invisibly
is a V8 violation of the worst kind."* Resume is a manual operator decision: a
partition that halted because durability was at risk should not resume on a
hopeful retry, since a second halt would lose the buffered facts it is holding.

**Partitions are independent.** A batch spanning cameras commits per partition,
never transactionally — §4.4's *"neither takes a cross-partition lock"*. One
camera's storage failure leaves the other 199 recording.

---

## 7. Evidence Provenance Report

The audit chain, and where each link is forged:

```
Crop (M8) ──> UnderstandingRequest ──> UnderstandingResult ──> Observation
  crop_id         request_id            evidence_id              observation_id
  trigger_reason  prompt_id             input_hash               provenance
  frame_ref       model_id              raw_output_ref           t_capture / t_published
```

| Field | Produced by | Why there and not elsewhere |
|---|---|---|
| `trigger_reason` | M8 | Why the platform looked at all — part of why the answer exists |
| `input_hash` | M9 | Two results with the same input and different answers proves non-determinism |
| `raw_output_ref` | M9 | Content-addressed; the verbatim model output |
| `prompt_id` + version + hash | M9 | The question that produced this answer |
| `model` | M9 | Which weights said it |
| `timing` | M9 | A p99 that is really a cold start is a different problem from a queue |
| **`observation_id`** | **M11** | M9 may not mint an id for an object it cannot create |

**`EvidenceRef.status`** carries `stored` / `pending` / `unavailable`, because
§M11's failure table wants honesty about a failed evidence write: *"mark
`evidence_unavailable` — **honest rather than silent**."* The three states mean
different things to a consumer trying to retrieve it, and collapsing them to a
boolean would lose the distinction between "not yet" and "never".

**Envelope provenance names M11; attribute provenance names M9.** An auditor
asking *"who said this"* and *"who packaged it"* is asking two questions, and both
answers are recorded, in different places.

**Attribute observations carry no envelope-level confidence.** The understanding
seam reconstructs its subject from the result and does not know how sure M7 is
that this track is this object. Stamping a number there would publish a certainty
nobody measured. Each attribute carries its own confidence, which M9 did measure.

---

## 8. Dependency Graph

```
                    core/model/{observation, vision_state, ids}
                                      │
                       core/ports/synthesis (P18, P19, P20)
                                      │
             ┌────────────────────────┼────────────────────────┐
             │                        │                        │
      synthesis/builder          state/                 adapters/synthesis
      ├── validation.py          ├── projection.py      ├── suppression.py
      ├── suppression.py         └── manager.py         ├── stores.py
      └── engine.py                                     └── decode.py
             │                        │                        │
      synthesis/runtime.py ───────────┘                        │
             │                                                 │
             └──────────── synthesis_bootstrap.py ─────────────┘
                          (the only module that selects)
```

**Dependency direction, verified mechanically:**

* `state/` never imports `synthesis/`. It imports `core/ports/synthesis`, which is
  a contract owned by neither side — the whole reason it is a port. The guard
  parses imports rather than matching the word, so it distinguishes them.
* `synthesis/builder/engine.py` never imports `VisionStateManager`. A builder
  holding the manager could read state to decide what to publish, and suppression
  would silently become a state query.
* Neither package imports any lower-layer runtime — no acquisition, detection,
  tracking, cropping or understanding *machinery*, only its types.
* `perception/` and `acquisition/` contain no reference to synthesis or state.

**New external dependencies: none.** Standard library only (`json`, `threading`,
`pathlib`).

---

## 9. Runtime Integration Report

**Queue asymmetry** (08_RUNTIME §5.2) is the architecture's own answer to the
question this layer raises:

| Edge | Policy | Why |
|---|---|---|
| `Crop → Understanding` | `drop_oldest` | Dropping a crop costs one enrichment |
| **`Builder → State`** | **`block`** | Dropping an observation deletes a fact the platform already decided was worth publishing |

`_commit` never sheds. A commit failure is surfaced, counted and reported to
health — never silently discarded.

**Per-camera serialization.** The runtime holds one `asyncio.Lock` per camera.
Without it, two coroutines feeding one camera could read the same suppression
signature and both publish, or both suppress.
`test_concurrent_seams_for_one_camera_serialize` runs three concurrent feeders
and asserts the exact expected count.

**No cross-partition synchronisation.** Two cameras never wait on each other —
the property that lets a 200-camera node degrade one stream without stalling the
rest.

**Health.** `SynthesisRuntime.health()` degrades on unhandled seam exceptions,
sustained commit failures, or a schema-violation spike. The runtime reports
rather than dies (V9).

---

## 10. Performance Report

Measured as **shape**, not wall-clock: an absolute millisecond budget on a shared
CI box measures the box. What matters architecturally is that cost stays flat as
the partition grows and that bounded things stay bounded.

| Property | Result | Test |
|---|---|---|
| Snapshot cost vs. partition size | 64× objects costs < 8× (asserted); observed near-constant | `test_a_snapshot_is_constant_time` |
| Unchanged object across a write | **identical object**, not a copy | `test_an_unchanged_object_is_shared_rather_than_copied` |
| Suppression, stationary subject | ≤ 10 of 100 republish | `test_suppression_keeps_the_common_case_cheap` |
| Projection cost vs. history depth | 5,000 observations in costs < 10× the first 100 | `test_projection_cost_does_not_grow_with_history` |
| Suppression state, 1,000 subjects | bounded at configured capacity (32) | `test_the_builder_does_not_grow_without_bound` |
| Partition under 2,000 observations | bounded objects, bounded trajectories | `test_a_long_run_stays_bounded` |
| 64 cameras on one node | 64 independent partitions | `test_many_cameras_on_one_node` |

**Every dimension is bounded structurally**, per 07_STATE §6.3: *"a structural
property of the ring buffers rather than a tunable that might be misconfigured to
infinity."* Trajectory points, attribute history, class history, objects per
partition, tracked suppression subjects, and log buffer depth all have hard
limits, so a node's steady-state memory is calculable before deployment.

---

## 11. Test Report

**225 Flow 7 tests, all passing. 87% coverage of Flow 7 modules.**
**2,446 Vision OS tests total, 0 failures, 0 skips.**

| File | Tests | Categories |
|---|---:|---|
| `test_observation_envelope.py` | 30 | Observation, Unit |
| `test_vision_state.py` | 30 | State transition, Replay, Failure |
| `test_synthesis_architecture.py` | 29 | Architecture, Boundary |
| `test_projection.py` | 25 | Projection, Unit |
| `test_suppression.py` | 22 | Unit, Regression |
| `test_conformance_and_security.py` | 22 | Conformance, Security |
| `test_semantic_ceiling.py` | 19 | Boundary, Observation |
| `test_determinism_and_load.py` | 18 | Replay, Performance, Concurrency, Stress |
| `test_integration.py` | 16 | Integration |
| `integration/test_end_to_end.py` | 14 | Integration, Conformance |

All fourteen required categories are covered: Unit, Integration, Architecture,
Boundary, Observation, Projection, State Transition, Replay, Performance,
Concurrency, Stress, Failure, Conformance, Regression.

### Coverage by module

| Module | Coverage |
|---|---:|
| `synthesis/builder/engine.py` | 94% |
| `conformance/synthesis_kits.py` | 93% |
| `synthesis/builder/suppression.py` | 91% |
| `adapters/synthesis/suppression.py` | 98% |
| `synthesis/builder/validation.py` | 87% |
| `state/manager.py` | 85% |
| `synthesis_bootstrap.py` | 85% |
| `synthesis/runtime.py` | 84% |
| `state/projection.py` | 83% |
| `adapters/synthesis/decode.py` | 84% |
| `adapters/synthesis/stores.py` | 78% |

### Conformance results

All seven shipped adapters pass their kits:

```
log.memory               PASS      sink.collecting          PASS
log.file                 PASS      sink.null                PASS
suppression.exact        PASS      suppression.threshold    PASS
suppression.always       PASS
```

**The kits are shown to catch things.** Six deliberately broken adapters are
built and run against them — a non-idempotent log, an unordered log, a log that
leaks across partitions, a policy that silences coverage, a policy with an
unstable signature, and a sink that omits its durability declaration. Each fails,
and the test asserts *which* obligation caught it. A kit no adapter has ever
failed proves nothing.

### The wider Atlas suite

454 non-Vision-OS tests pass; 82 failures and 32 errors exist in unrelated
subsystems (auth, git API, chat, memory, chunker, vision service). **None touches
Vision OS** — verified by matching every failing node id. These are pre-existing
and outside Flow 7's scope.

---

## 12. Architectural Discoveries

Four defects were found by tests during this flow. Each is recorded with what it
would have cost, because the value is in the pattern, not the fix.

### 12.1 The ceiling's two responses were conflated in `_finish`

`validation.py`'s own module docstring sets out §M11's failure table — *drop the
attribute* versus *reject the envelope* — and the model carries the split as
`ViolationKind.rejects_the_envelope`. But `_finish` raised `ValidationFailedError`
on **any** rejection, so a model that volunteered one unregistered attribute
raised a constitutional failure.

The gate was working; the engine was mistranslating it. `_finish` now raises only
on `envelope_violations`, and an attribute observation whose every attribute was
dropped returns `None` — the same signal as suppression, because in both cases the
correct outcome is that no fact is published and nothing is wrong.

**Cost if shipped:** every deployment whose model occasionally volunteers an
extra field would see the exception path on the hot publication route, and an
operator would read the platform's most alarming error for the platform working
exactly as designed.

### 12.2 `FileObservationLog` read back empty, silently

The decoder deliberately dropped the spatial payload, on the stated grounds that
a serializer *"claiming a fidelity this adapter does not have"* would make a
rebuild produce a different world. But 02_VOM requires a presence observation to
carry a position, so `Observation.__post_init__` refused every reconstructed
record — `decode_observation` returned `None` for each, and the whole log read
back as nothing.

The conservative choice produced the exact failure it was trying to prevent. A
normalized box is four floats; there was never a size argument. Spatial payload,
coverage windows and lifecycle transitions are now encoded and decoded, and the
module docstring records both what survives and why the earlier reasoning was
wrong.

**Cost if shipped:** a site binding the durable adapter would have a log that
appended correctly and restored nothing. The failure would surface only during a
recovery — the one moment it must not.

**Why it was not caught earlier:** the kit had only ever been run against
`log.memory`. Gating `log.file` through the same kit in the bootstrap is what
exposed it.

### 12.3 The understanding seam fabricated an identity confidence

`_object_for` reconstructs a subject from an `UnderstandingResult` — correct, and
correctly reasoned: reaching into M7 would give L5 a read dependency on L2. But it
stamped `Confidence.uncalibrated(1.0, IDENTITY)`, and `build_attribute` copied
that onto the envelope. The platform was publishing *complete certainty* that a
track was an object, from a module with no basis for the claim.

`build_attribute` now takes an optional envelope confidence, and the seam passes
none. Attribute confidence lives on each attribute, where M9 measured it.

**Cost if shipped:** every attribute observation in the permanent record would
assert identity certainty of 1.0. A downstream consumer weighting by confidence
would treat the least-grounded claims as the most reliable.

### 12.4 A config key named `violation_threshold` looked exactly like a business rule

The architecture guard `test_no_config_section_admits_a_business_threshold`
rejected `synthesis.violation_window` and `synthesis.violation_threshold`. The
fields counted *schema* violations — the platform's own V1 enforcement, the
opposite of a business rule — but the guard could not tell them apart, and neither
could a reader.

Renamed to `rejection_window` and `rejection_alarm_rate`. The guard was right for
a reason worth keeping: a key reading `violation_threshold` is indistinguishable
from the tuning knob for *"how many safety violations before we alert"*.

### 12.5 A guard that had been passing vacuously

`test_no_later_flow_object_kinds_exist` asserted `not hasattr(core.model, "Crop")`.
`core/model/__init__.py` never re-exported those names, so the assertion held
whether or not the kind existed — it had been green since Flow 2 for the wrong
reason. It now checks the module files, and the forbidden list is the names the
ceiling forbids outright (`alert.py`, `incident.py`, `rule.py`, `person.py`),
which no flow may ever add.

---

## 13. Known Limitations

Recorded rather than hidden. Each is a real constraint a future flow may lift.

1. **A false durability claim is not mechanically detectable.** `ObservationSinkPort`
   obligation K5 requires a sink to declare whether it is durable. The kit checks
   the declaration is *made*; it cannot check it is *true* — that needs a power
   cut, as the kit's own docstring says. A sink returning `durable = True` while
   keeping nothing passes. `test_a_false_durability_claim_is_not_mechanically_detectable`
   asserts this explicitly so nobody later reads the passing kit as proof.

2. **The file log's round trip remains lossy on four things**: `QualityGrades`, the
   decision path, the identity assertion, and the evidence body. None is required
   for an observation to be constructed, so unlike the spatial payload their
   absence fails no invariant — but a rebuild from a file log produces observations
   without them. A deployment needing full fidelity binds a richer P20 adapter;
   the port is where that choice belongs.

3. **The conformance kit writes real records into the live adapter.** A store can
   only be shown to store by storing. The kit uses reserved `kit-*` partitions
   that no camera read will ever touch, and `_purge_kit_traces` resets adapters
   that expose a `reset`. A durable adapter with no per-partition deletion path
   retains a handful of fixture records under partitions no camera will use.

4. **`FileObservationLog` rebuilds its idempotency set by scanning the partition
   file** on first touch. For a large log this is a one-time O(n) cost at startup.
   A production adapter would keep an index; this one derives it from the record
   itself rather than from a sidecar that could disagree.

5. **`site_context` is eventually consistent by design** (07_STATE §4.4). A
   multi-partition snapshot reports `SNAPSHOT_SET`, never `STRONG`, because there
   is no cross-partition lock and therefore no global instant. This is the
   architecture's choice, not an implementation shortfall, but a consumer expecting
   a site-wide instant will not get one.

6. **Retention sweeps by age only.** No content-based deletion exists, which means
   a deployment cannot express *"delete observations about X"*. That is deliberate:
   choosing which facts matter is a business judgement (V1).

7. **`_attach` schedules the hand-off rather than awaiting it.** The registry's
   sink is synchronous and `on_registered` is a coroutine, so the task is created
   and not awaited. Awaiting would put synthesis latency on L2's critical path
   (V9), but it means a synthesis failure is observed through health and metrics
   rather than at the call site.

---

## 14. Future Extension Points

Each is a seam that already exists, not work to be done.

| Extension | Seam | Notes |
|---|---|---|
| **M13 Persistence** | P20 `ObservationLogPort` | The contract is realized; M13 supplies replicated, tiered or archived implementations. §M13 implements none of it by design. |
| **M14 Exposure** | `VisionStateManager` read methods | `snapshot`, `object_state`, `history`, `coverage`, `coverage_report`, `site_context`, `subscribe`. All read-only, all O(1) or log-backed. P32 stays unbindable until Flow 8. |
| **Richer suppression** | P18 `SuppressionPolicyPort` | The policy owns its own signature, so a policy with a completely different notion of "changed" needs no builder change. |
| **Observation fan-out** | P19 `ObservationSinkPort` | A webhook, a message bus, a dashboard tee. Multiple sinks already supported. |
| **Evidence persistence** | P22 `EvidenceStorePort` | Defined, deliberately unbound. `EvidenceRef.status` already models `pending` and `unavailable` for the day a store exists. |
| **Splitting attribute observations** | `build_attribute` returns a **list** | §M11's signature. Today one observation carries a result's attributes; a future policy could split by privacy class or retention with no contract change. |
| **Cross-camera identity** | P11 `IdentityResolverPort` | Phase 2, classified C2, policy-gated. Deliberately unbindable; guarded permanently. |
| **Temporal / multi-frame synthesis** | `MeasurementBasis.INTERPOLATED` | The basis vocabulary already distinguishes measured, predicted and interpolated facts. |

---

## 15. Final Verification

| Requirement | Status | Evidence |
|---|---|---|
| Flows 1–6 remain unchanged in behaviour | ✅ | 2,446 Vision OS tests pass. The only Flow 6 change is additive (`demand_ids`), required by 02_VOM §11's envelope. |
| M11 consumes only validated Understanding Results | ✅ | `on_understood` takes `UnderstandingResult`; a non-`SUCCEEDED` outcome produces no observation. |
| M11 performs no AI inference | ✅ | `test_synthesis_performs_no_inference` — code-only scan for model calls |
| M11 performs no detection, tracking, understanding | ✅ | `test_synthesis_performs_no_detection_or_tracking` |
| M11 performs no business reasoning | ✅ | `test_synthesis_performs_no_business_reasoning` — 12 forbidden terms |
| Every Observation is immutable | ✅ | Frozen, slotted, no `__dict__`; `test_an_observation_cannot_be_mutated` |
| Every Observation preserves evidence | ✅ | `MISSING_EVIDENCE` rejects an attribute envelope entirely |
| Every Observation preserves provenance | ✅ | Construction refuses a missing producer, config revision or provenance |
| Every Observation preserves confidence | ✅ | Attribute confidence is carried unmodified; envelope confidence is never invented |
| Vision State is updated only through Observations | ✅ | `append` is the only public mutator |
| Vision State is deterministic | ✅ | `project` takes no clock; signature asserted |
| Vision State is replayable | ✅ | Rebuild reproduces objects, timestamps and counts; batch shape is irrelevant |
| No future roadmap functionality implemented | ✅ | Flow 8 frontier guards in six suites; `api/` and `exposure/` asserted absent |
| No biometric persistence, no cross-camera identity | ✅ | `test_no_biometric_persistence`, `test_synthesis_does_no_cross_camera_identity`; P10/P11 permanently unbindable |
| Vision State contains no identities or business labels | ✅ | Field-name scan across every `vision_state` type |
| `ruff check` clean | ✅ | All checks passed across `app/vision_os` and `tests/vision_os` |

---

## 16. Summary

Flow 7 implements M11 Observation Builder and M12 Vision State, and nothing else.

M11 is the **final constitutional enforcement point**: the last of the ceiling's
three gates, and the only one nothing downstream re-checks. An attribute that
passes it is a platform fact forever, which is why the gate re-checks what the
earlier gates checked and why every test here attacks it rather than exercising
it.

M12 is a **projection, not a database**. The immutable observation log is the
system of record; state is a derived, bounded, structurally-shared view that can
be thrown away and rebuilt. Observation is the only write path. Correction never
edits.

Four real defects were found by tests — a conflated failure response, a durable
log that read back empty, a fabricated certainty, and a config key that read as a
business rule. Each was fixed at its cause rather than at its symptom, and each is
recorded above with what it would have cost.

**6,473 lines of implementation. 225 tests across all fourteen required
categories. 87% coverage. 2,446 Vision OS tests passing.**
