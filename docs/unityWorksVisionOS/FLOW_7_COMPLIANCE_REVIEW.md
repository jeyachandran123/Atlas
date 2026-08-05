# Flow 7 — Constitutional / Architecture Compliance Review

**Performed before any code was written**, as required.

Documents reviewed: `04_MODULES_UNDERSTANDING_AND_STATE` (M11 and M12 in full, M9
and M13 for the boundaries on either side), `02_VOM` (§7 confidence, §9
attributes, §10.9 evidence, §11 the observation envelope, §12 schema evolution),
`07_STATE_ARCHITECTURE` (all ten sections), `01_LAYERED` (§1.1 layer ownership,
§1.2 why L4/L5 and L6/L7 are not collapsed, §2 dependency law, §3.1 the dotted
edges, §8 cross-cutting placement). Secondary: `06_PORTS`, `08_RUNTIME`,
`09_API_CONTRACTS`, `10_RELIABILITY`, `11_PERFORMANCE`, `12_SECURITY`,
`14_TESTING`. `00_CHARTER` §4.3 for the ceiling's three gates. `15_ROADMAP` only
to confirm nothing future is built.

---

## 1. Why M11 exists

`04_MODULES` §M11 states it in one line:

> Assemble complete, explainable, ceiling-compliant `Observation` objects — **the
> single choke point through which every published fact must pass.**

Two words carry the module: **single** and **choke point**. `01_LAYERED` §8 gives
the reason directly:

> *Schema & ceiling enforcement — L5 Observation Builder. One choke point through
> which every fact must pass. **Enforcement distributed across producers is
> enforcement that will be bypassed.***

Every layer beneath M11 produces signals: detections, tracks, bindings, crops,
attribute claims. None of them is a published fact. M11 exists so that the
transformation from *signal* to *fact* happens exactly once, in one place, under
one set of rules — and so that the rules can be enforced by a single body of code
rather than by the discipline of five different producers.

## 2. Why Vision State exists

`07_STATE` §1 states the question it answers:

> ***what is visible right now, where, since when, and how confident are we?***
> — plus the honest admission of where it cannot see.

The log is the system of record; state is *what the log means at this instant*.
§1 is explicit that state exists because *"recomputing it per query would be
absurd"* — it is a performance structure over an authoritative record, not an
authority in itself.

Its three defining properties (§1.1) are **Owned** (the platform is the sole
writer), **Derived** (everything traces to an observation), and **Honest** (V8:
uncertainty, staleness and blindness are explicit).

## 3. Why Understanding cannot publish observations

`01_LAYERED` §1.2 names L4/L5 as one of three boundaries systems habitually
collapse, and states the consequence:

> *Systems that let the model output become the output publish whatever the VLM
> said, including hallucinated fields and business-flavored prose. A synthesis
> layer that owns schema and ceiling enforcement is the only durable defense of
> V1 and V4.*

Three structural reasons, each sufficient:

**A producer cannot be its own gate.** `00_CHARTER` §4.3 makes M11 the *third and
final* ceiling gate. M9 already applies a producer-side check (Flow 6's
`AttributeValidator`), but a choke point that also produces what it checks is
checking itself — worth nothing the first time someone is under deadline pressure.

**Understanding is optional; observations are not.** `01_LAYERED` §3.1's dotted
edges: *"detection, tracking, and registry results become observations without
passing through understanding. Understanding is enrichment, not a toll gate."* If
M9 published, a presence observation would wait on a VLM.

**Envelope completeness is not M9's information.** An observation needs
calibration-projected spatial data, taxonomy version, lifecycle state, coverage
context and lineage. M9 sees a crop and a prompt. It cannot assemble an envelope
it does not have the inputs for.

## 4. Why the Registry cannot own observations

M7 owns *objects* — the durable answer to "is this the same thing". An
observation is a *statement about a moment*, and the two have opposite lifetimes:
an object is mutable and long-lived; an observation is immutable and instantaneous
(V5).

Three consequences of merging them:

**Mutability would leak.** M7 revises an object every frame. If observations lived
there, the natural implementation would update them — and V5 would be gone.

**Derivability would invert.** `07_STATE` §1.1 requires state to be derived from
the log. If the registry owned observations, the registry's mutable objects would
be the source and the log a byproduct — exactly backwards, and rebuild would
produce a different world.

**The ceiling would move to L2.** M7 sits below understanding. Making it the
publication point would put the final semantic gate beneath the layer that
produces the semantics.

## 5. Why Vision State cannot perform synthesis

`04_MODULES` §M12's single responsibility is *"Be the single writer of visual
truth, and never interpret it."* And §M12's Dependencies is emphatic:

> **No dependency on any perception module** — it consumes observations and knows
> nothing of how they were made, **which is what allows the entire perception
> stack to be replaced beneath it.**

That is the whole argument. M12 knowing how to *build* an observation would mean
M12 knowing what a detection, a track, a crop and an understanding result are —
and the perception stack could then never be replaced without rewriting state.

There is a second reason in `01_LAYERED` §1.2: the L6/L7 split exists so internal
representation can evolve while the contract holds. Synthesis inside state would
couple the projection's shape to the producers' shapes, and both would freeze.

## 6. Why observations must be immutable

`07_STATE` §2.1 gives the reason V5 is not an imposition:

> *V5 is not a constraint imposed to enable event sourcing; it is the natural
> nature of the data. An observation is a statement about a moment that has passed
> and cannot become untrue.*

And §2.2 gives the operational consequence:

> *A consumer that acted on `obs-A` at the time acted correctly on the information
> then available — and can prove it, which matters enormously in regulated
> contexts.*

Mutation would destroy four properties at once: auditability (the record of what
was reported at 09:14 would change), derivability (rebuild would produce a
different world), replayability (V13), and the correction trail (a superseded
observation is *evidence about how understanding evolved*, not garbage).

Corrections are therefore **new observations carrying `supersedes`** — never
edits.

## 7. Why Vision State is a projection, not a database

`07_STATE` §1: *"It is a **materialized projection**, not a database of record."*
§2.1 gives four concrete reasons event sourcing is genuinely correct here rather
than fashionable:

| Reason | Consequence for Flow 7 |
|---|---|
| Observations are already immutable facts | The log is the natural storage shape, not an imposition |
| Auditability is a deployment requirement | *"What did the system report at 09:14 and why"* must be answerable years later |
| The state schema will change | *"With a log, that is a rebuild. Without one, it is a migration with irrecoverable loss of fidelity."* |
| Reprocessing enables the future | A learning pipeline needs the raw record; the log is what makes Phase N possible without building it |

The strongest single argument, from §9.1: a **projection bug** is fixed by
rebuilding into a shadow projection and swapping atomically — *"None — this is the
strongest argument for event sourcing here."* A database of record has no such
recovery.

## 8. Why the Observation Builder is the final semantic gate

`00_CHARTER` §4.3 names three enforcement points, and M11 is the third:

> *It refuses to emit an observation containing an attribute absent from the
> registry. Free-text model output that does not coerce to a registered schema is
> preserved as `unstructured_note` **evidence** — inspectable, never promoted to a
> typed attribute, never queryable as fact.*

It is *final* in the literal sense: nothing downstream re-checks. `07_STATE` §1.1
says state is derived from observations and has no other write path; M14 serves
state read-only. So an attribute that passes M11 is a platform fact forever.

That is why §M11's failure table distinguishes two responses sharply:

* **an unregistered attribute** → drop the attribute, keep the observation, count,
  alarm on a sustained rate;
* **an incomplete envelope** → reject the observation entirely, and alarm, because
  *"an unexplainable observation is worse than no observation — it is a fact
  nobody can audit (V4)."*

## 9. Where M11 begins and ends

**Begins** when a signal arrives that might be a fact: a `VisualObject` from M7, a
`TrackUpdate`, an `UnderstandingResult` from M9, a lifecycle transition, a region
transition, or a coverage change. Not before — M11 never asks for a signal, never
triggers analysis, never asks the AI another question.

**Ends** the moment a validated `Observation` is handed to a sink. Not after: M11
does not store it, does not project it, does not serve it, does not decide what it
means.

The two boundaries in one line: **M11 turns signals into facts and refuses
anything that is not one. What happens to a fact belongs to someone else.**

## 10. Where Vision State begins and ends

**Begins** at `append(observations)`. `07_STATE` is unambiguous that this is the
*only* entry: state is derived, and *"nothing is in state that was not first a
published fact."*

**Ends** at `snapshot(scope)`, `object_state`, `history`, `coverage` and
`subscribe` — all read-only, all immutable. M12 does not interpret, does not
aggregate for business purposes, does not alert, does not predict.

`07_STATE` §10 gives the test for any proposed state field: *"would this field
mean the same thing in a hospital, a warehouse, and a city street?"*

## 11. Who feeds M11, who consumes Vision State

**Feeds M11:** M5 detections, M6 tracks, M7 objects and lifecycle/identity/region
transitions, M9 understanding results, M1 calibration, the Attribute Schema
Registry and Taxonomy, M18's confidence calibration profiles.

**Feeds M12:** M11's observations. Coverage signals from M2 (stream events), M3
(drop alarms) and M8 (budget alarms) — which reach M12 as *coverage observations*,
not as direct writes.

**Consumes M12:** M14 Observation API (Flow 8) via snapshots and log range reads;
`ObservationSinkPort` (P19) consumers — a message bus, a data lake, a future
learning pipeline.

## 12. Invariants constraining both modules

| Invariant | M11 | M12 |
|---|---|---|
| **V1 Semantic Ceiling** | The final gate. Unregistered attribute → dropped, counted, alarmed | `07_STATE` §3.3: `occupancy` is a count; there is no `is_crowded` |
| **V2 Vertical neutrality** | No domain vocabulary in the envelope | §10: business entities, thresholds, alerts and aggregations are all excluded |
| **V3 Ports over implementations** | P18 suppression, P19 sinks | P20 log, P21 state store |
| **V4 Explainability** | Envelope completeness is mandatory: no provenance → reject | The log *is* the audit trail |
| **V5 Immutability** | Corrections are new observations with `supersedes` | Append-only log; never rewrite |
| **V6 Single-writer state** | Per-camera single-writer for suppression state | *"The camera is the partition. Each partition has exactly one writer."* |
| **V7 Perceptual economy** | Change suppression: 10–50× reduction, *"a correctness feature too"* | Bounded history by count **and** time |
| **V8 Blindness explicit** | `coverage` observations; honest `measurement_basis` | `ObservabilityState`; `staleness`; `incomplete` on snapshots |
| **V9 Degrade never die** | Calibration unavailable → emit normalized only. *"Degrade the content, never the observation"* | State ladder §4.4; a stuck partition affects one camera |
| **V11 Normalized time** | `t_capture` + `t_capture_unc` + `clock_quality` | *"The platform never fabricates a global instant"* |
| **V12 Pixels stay local** | `evidence_ref`, never pixels | No imagery in state |
| **V13 Deterministic replay** | Building is a pure function of inputs | *"Replaying observations by `observation_id` produces the same state"* |

## 13. Implementation shortcuts that must be rejected

| Tempting | Why it is forbidden |
|---|---|
| Mutate an observation to fix a value | V5. Corrections are new observations carrying `supersedes`. |
| Let M12 update state from a track or an object directly | `07_STATE` §1.1: state is *derived*. A non-observation write makes rebuild produce a different world. |
| Drop the whole observation when one attribute is unregistered | §M11's table is explicit: **drop the attribute**, keep the rest. Losing a valid presence fact because one attribute was bad is over-reaction. |
| Emit an observation with missing provenance "to avoid losing data" | The opposite of the rule: *"an unexplainable observation is worse than no observation."* |
| Convert a missing attribute into `false` | R1 and V8. Missing understanding must never become a negative fact. |
| Suppress an unchanged observation forever | Heartbeat cadence is mandatory: *"a consumer must be able to distinguish 'unchanged' from 'stopped observing.'"* |
| Take a cross-partition lock for a merge | §4.4: *"A distributed transaction across camera partitions would reintroduce global coordination precisely where the architecture removed it."* |
| Let a storage outage silently drop observations | §4.4 step 4: **stop accepting and mark the partition degraded**. *"Losing observations invisibly is a V8 violation of the worst kind."* |
| Copy state on snapshot | §5.1: structural sharing, O(1). Copying makes heavy query load slow perception, which M14's contract forbids. |
| Keep unbounded history "for analytics" | §6.1: *"History exists for perception, not for analytics."* |
| Fabricate a global instant for a multi-partition read | §5.2: report per-partition versions and a lag bound instead. |
| Rewrite history to satisfy an erasure request | §8.2: tombstone, do not rewrite. *"Rewriting history... would destroy the property that makes the log trustworthy."* |

---

## 14. Ambiguities found — five, all resolved without inference

### 14.1 M12 depends on M13 Storage Interfaces, which is out of scope

**The conflict.** §M12's dependency list names *"Storage Interfaces (M13)"*, and
M12 cannot function without an observation log — the log is its system of record,
not an optional durability layer. But the mission says *"Implement ONLY M11 and
M12."*

**Resolution — M13 has nothing to implement.** §M13's single responsibility is
*"Describe what must persist and with what guarantees; **implement none of it**."*
It owns **no state** and is *"a set of contracts."* So realizing P20
`ObservationLogPort` as a protocol plus a reference adapter is not implementing
M13 — it is implementing an **adapter behind a contract M13 already defines**.

The precedent is established twice: Flow 2 shipped adapters for P25/P26/P27
(M18's ports) to serve detection, and Flow 4 shipped `InMemoryObjectStore` and
`FileObjectStore` for P21 without claiming to implement M13. Flow 7 does the same
for P20.

### 14.2 P21 `StateStorePort` is already bindable, bound in Flow 4 for a different purpose

**The conflict.** Flow 4 made `STATE_STORE` bindable and used it to persist the
*object population* so identity survives restart (`07_STATE` §9.3). Flow 4's own
manifest comment says: *"It is not the Vision State projection, which is M13 at
L6."* Flow 7 now needs P21 for the actual Vision State projection.

**Resolution.** The port is one contract with two legitimate consumers, exactly as
`ObservationLogPort` will have several. §M13's table describes StateStore as
holding *"Current projection... Random read/write, snapshot"* — which covers both
uses. Flow 7 introduces no new port and changes no binding; it adds a second
adapter *use*. The Flow 4 comment is updated to record that the second consumer
has now arrived, which is documentation catching up rather than a design change.

### 14.3 The observation envelope requires signals from five modules; only some are available at any one seam

**The conflict.** `02_VOM` §11's envelope carries detector, tracker *and*
understander provenance, plus taxonomy version, lifecycle state, quality grades
and calibration. No single upstream seam carries all of it: M7's `RegistryUpdate`
has objects and lifecycle; M9's `UnderstandingResult` has attributes and model
provenance; neither has both.

**Resolution — this is what §M11's API shape already says.** The public API is
*six distinct builders*, not one: `build_presence`, `build_spatial`,
`build_attribute`, `build_identity`, `build_lifecycle`, `build_coverage`. Each
takes exactly the signals available where it is called, and each produces the
observation *type* that those signals support (`02_VOM` §11.2). An `attribute`
observation carries understander provenance; a `presence` observation carries
detector provenance. Requiring every envelope to carry every producer would make
most observations unconstructible, which is plainly not the intent of a table that
assigns different content to different types.

### 14.4 `Evidence.observation_id` — the field Flow 6 deliberately left unstamped

**Carried forward from Flow 6 §12.2.** `02_VOM` §10.9 declares
`Evidence.observation_id`, and Flow 6's `UnderstandingEvidence` omits it because
M9 may not mint an identifier for an object it cannot create.

**Resolution.** Flow 7 completes it. M11 mints the `ObservationId` and stamps it
onto the evidence record as it assembles the observation, producing the complete
`Evidence` of §10.9. This is the promised half of a two-part construction, and a
test asserts the field is populated on every published observation.

### 14.5 M11 both *emits* coverage observations and M12 *holds* coverage state

**The conflict.** §M11 responsibility 9 is *"Emit `coverage` observations when the
platform's observability changes."* `07_STATE` §7 gives M12 an `ObservabilityState`
and a `CoverageMap`. Two modules appear to own coverage.

**Resolution — §7.3 answers it directly.** Coverage is *"both **live state** and
**historical observations**"*:

* **Live** — `SiteContext.coverage` answers "can we see right now?" That is M12's
  projection, derived like everything else.
* **Historical** — `coverage`-type observations are appended to the log on every
  transition, so a query over any past window can reconstruct what was observable.

So M11 emits the *observation*; M12 projects it into the *state*. That is the same
producer/projector split as every other observation type, and it means coverage
obeys the same "observation is the only write path" rule as everything else.

---

## 15. Scope confirmation against `15_ROADMAP`

Confirmed **not** implemented:

| Deferred | Phase | Flow 7 posture |
|---|---|---|
| Observation API (M14) | Flow 8 | State exposes read methods; no transport, no authz, no query language. P32 stays unbindable. |
| Cross-camera identity merge | 2 | §4.4 names it as a cross-partition operation; the *observation type* `identity` ships, the resolver does not. P11 stays unbindable. |
| Federated multi-site state | 2+ | Snapshot already reports per-partition consistency, so federation adds no new semantics — and no federation code. |
| Learning pipeline | 4 | P19 `ObservationSinkPort` is the designed hook; no training code exists. |
| Full temporal index projection | later | §Extension Points lists it; Flow 7 ships current + bounded history. |
| Analytics, alerts, business rules | never (V1) | Structurally inexpressible. |

Also **not** implemented, because they are other modules: M10 Prompt Manager
(Flow 6 shipped a marked stand-in), M13 as a module (see §14.1), M14 Observation
API.

---

## 16. Compliance conclusion

M11 and M12 as specified are implementable exactly as written. Five ambiguities
were found; all five resolve in favour of the architecture, and none requires an
architectural change.

**No architectural change is requested. Implementation may proceed.**
