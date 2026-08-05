# Flow 6 — Constitutional / Architecture Compliance Review

**Performed before any code was written**, as required.

Documents reviewed: `04_MODULES_UNDERSTANDING_AND_STATE` (M9 in full, M10 and M11
for the boundaries on either side), `02_VOM` (§7 confidence, §9 attribute registry
and unstructured output, §10.9 evidence, §11 observation envelope), `06_PORTS`
(P15 `UnderstanderPort` with obligations U1–U7, P16 `OutputCoercionPort`, P17
`PromptSourcePort`, §5 conformance kits), `01_LAYERED` (§1.1 layer ownership,
§1.2 why L4/L5 is not collapsed, §2 dependency law, §3.1 the dotted edges, §7.1
queues). Secondary: `07_STATE`, `08_RUNTIME`, `09_API_CONTRACTS`,
`10_RELIABILITY`, `11_PERFORMANCE`, `12_SECURITY`, `14_TESTING`.
`00_CHARTER` §4.3 for constitutional clarification of the ceiling's three
enforcement points. `15_ROADMAP` only to confirm nothing future is built.

---

## 1. Why M9 exists

`04_MODULES` §M9 states it in one sentence:

> *Convert a region of pixels into **structured, schema-conformant claims** — the
> platform's only semantically ambitious component, and therefore the one most
> tightly constrained.*

That second clause is the whole design. Every other module in the platform makes
claims a human can verify by looking: a box is here, this track is that object,
this crop is 264 pixels tall. M9 is the only module that asks an open-ended
question of a model whose output space is unbounded natural language, and it is
therefore the only place where the platform's vocabulary could grow without
anyone deciding it should.

`01_LAYERED` §1.2 names the failure directly:

> *Systems that let the model output become the output publish whatever the VLM
> said, including hallucinated fields and business-flavored prose.*

M9 exists so that the unbounded thing happens **once, in one place, behind one
schema gate**, rather than in every consumer that wanted an attribute.

## 2. What problem M9 solves

Three, each fatal alone.

**Unbounded output meeting a typed contract.** A VLM asked for `posture` may
return `"standing"`, `{"posture": "standing"}`, or three paragraphs of prose about
what it thinks is happening. `02_VOM` §9.3 is explicit that the third case is
preserved rather than discarded — inspectable, never promoted. Without a coercion
layer, every consumer writes its own parser and they disagree.

**Fabrication indistinguishable from truth.** `06_PORTS` U2 calls this *"the
single most dangerous failure mode for a VLM-based system, because fabricated
output is indistinguishable from real output downstream."* A model that times out
and returns a plausible default poisons the observation log silently and forever.
M9's answer is that failure is always an explicit result and never a value.

**Model churn against a stable contract.** `11_PERFORMANCE` §7 describes replacing
a general VLM with a specialized head for a high-volume attribute — ~100× cheaper,
attribute by attribute, in production. That migration is only a configuration
change if understanding sits behind a port. `06_PORTS` §P15 puts it plainly:
*"Designing for this migration is the main reason understanding is a port rather
than a hardcoded VLM call."*

## 3. What M9 owns

`04_MODULES` §M9 State Ownership, verbatim:

> **Owns:** in-flight request tracking, batch accumulation, per-model circuit
> breaker state, response cache keyed by `(CropId, prompt_version, model_version,
> attribute_set)`.
>
> Owns no world state. Every call is a pure function of (crop, prompt, model).

The cache key deserves the emphasis the document gives it:

> *Because `CropId` is a content hash and prompt/model versions are explicit, the
> cache is **correct by construction** — a cache hit is guaranteed to be the
> answer the current configuration would produce. Caches keyed on object id or
> timestamp instead are the usual source of stale-attribute bugs.*

Beyond that, M9 owns the **act of understanding**: model selection for a
requested attribute set, coercion into the declared schema, quarantine of what
does not fit, confidence semantics, and the retry/fallback ladder.

## 4. What M9 absolutely does NOT own

| Not owned | Owner | Why the separation is load-bearing |
|---|---|---|
| Whether the analysis was worth doing | M8 (L3) | §M9 says this explicitly under *"Explicitly not responsible for"*. Fusing them makes cost policy untestable and puts a budget decision inside a model call. |
| The published observation | M11 (L5) | `01_LAYERED` §1.2: a synthesis layer that owns schema and ceiling enforcement *"is the only durable defense of V1 and V4"*. |
| The attribute **registry** | The Attribute Schema Registry (Flow 4) | The first of the ceiling's three gates (`00_CHARTER` §4.3). M9 consults it; it does not define it. |
| Prompts | M10 | `00_CHARTER` §4.3 gate 2. Prompts are versioned assets with declared output schemas; owning them inside the engine would make prompt evolution a code release. |
| Model artifacts, devices, calibration | M18 Model Manager (L0) | `01_LAYERED` §8: *"Detection and Understanding use models; they never load, version, place, or evict them."* |
| Vision State | M12 (L6) | State is a projection of the observation log. M9 produces neither. |
| Vision Objects and attribute **storage** | M7 (L2) | Flow 4 established M7 as the only writer. M9 produces attribute *values*; M7 holds them, via `apply_attribute`, called by M11's path — never by M9. |
| Identity | M7 / P11 | No re-identification, no galleries, no biometrics. |
| Crops | M8 (L3) | M9 reads a crop it did not make and cannot re-make. |

## 5. Why the Crop Manager cannot perform Understanding

Four independent reasons, each sufficient.

**Cost shape.** `11_PERFORMANCE` §1.1 puts a crop at microseconds and a VLM call
at ~200 ms — four orders of magnitude apart. M8 runs per candidate per frame; M9
runs per *demanded change*. A module doing both is scheduled by whichever
constraint is louder, and the answer must be M8's, because the whole point of L3
is that it decides.

**The layer boundary is a decision boundary.** `01_LAYERED` §1.1 gives L3 *"whether
the claim was worth making"* and gives L4 *"whether the claim was worth making"*
as its explicit **non**-responsibility. Merging them means the module that pays
the cost also decides the cost is justified, which is not a check at all.

**Concurrency shape.** `08_RUNTIME` §1 assigns M8 a *worker pool* (stateless, pure
functions, scales with cores) and M9 a *batch coordinator + device worker* (GPU
contention, semaphore per model, 100 ms–2 s calls). These are different machines.
Fusing them either starves the GPU or blocks the pool.

**Failure semantics.** §M9's most important property: *"understanding failure is
never pipeline failure."* M8's failure costs one crop; M9's failure costs one
enrichment; neither may cost a frame. If M9 lived inside M8, a circuit-broken VLM
would take crop extraction down with it, and with it the evidence that would have
explained the outage.

## 6. Why the Observation Builder cannot perform Understanding

`01_LAYERED` §1.2 names L4/L5 as one of the three boundaries systems collapse, and
states the consequence: publishing *"whatever the VLM said, including hallucinated
fields and business-flavored prose."*

The structural reason is that M11 is a **choke point** and M9 is a **producer**.
`00_CHARTER` §4.3 gate 3 makes M11 the last line: it refuses to emit an
observation containing an unregistered attribute. A choke point that also produces
the thing it is checking is checking itself, and the check is worth exactly
nothing the first time someone is under deadline pressure.

There is a second reason, visible in `01_LAYERED` §3.1's **dotted edges**:

> *Detection, tracking, and registry results become observations without passing
> through understanding. Understanding is enrichment, not a toll gate.*

M11 must be able to build a presence observation with no understanding involved
at all. If understanding lived inside it, every observation would wait on a VLM.

## 7. Why semantic understanding must be centralized

Because `06_PORTS` U1–U7 are only enforceable at one place.

If three consumers each call a vision model directly, there are three coercion
implementations, three confidence conventions, three raw-output retention
policies, and three answers to "what did the model actually say". The
`03_MODULES`-level guarantee that *every* claim carries its model, its prompt
version, its artifact hash and its decision path becomes three guarantees of
varying quality.

Centralizing gives four properties named across the architecture:

* **Consistency** — one coercion path, one confidence vocabulary (`02_VOM` §7).
* **Traceability** — `02_VOM` §10.9's `decision_path` is complete because one
  module made every decision in it.
* **Replaceability** — `11_PERFORMANCE` §7's VLM-to-specialized-head migration is
  a configuration change *only* because consumers never named a model.
* **Cost control** — `11_PERFORMANCE` §1.2's reduction is only achievable if one
  module can be metered, budgeted and cached.

The response cache alone justifies centralization: it is correct by construction
*because* the key includes the prompt and model versions, and no consumer-side
cache could know those.

## 8. Where M9 begins and ends

**Begins** the moment a `Crop` and a requested attribute set arrive from M8. Not
before: M9 never asks whether the crop should exist, never re-crops, never
re-grades quality.

**Ends** the moment an `UnderstandingResult` is returned. Not after: M9 does not
write the attribute into M7, does not build an observation, does not publish, does
not update state, does not notify a consumer.

The two boundaries in one line: **M9 turns pixels into candidate claims with
evidence. Everything about what to do with those claims belongs to someone else.**

## 9. Who feeds M9, who consumes M9

**Feeds:** M8 Crop Manager (crop + requested attributes + object context), M10
Prompt Manager (rendered prompt + declared output schema), M18 Model Manager
(loaded model handles), the Attribute Schema Registry (what may be emitted).

**Consumes:** M11 Observation Builder (Flow 7). Nothing else, and nothing before
it. `01_LAYERED` §3.2 sizes the edge at ~3 KB and classifies it **Control** —
structured claims plus a raw-output *reference*, never the raw pixels.

## 10. Invariants constraining M9

| Invariant | How it binds M9 |
|---|---|
| **V1 Semantic Ceiling** | Only registered attribute keys may be emitted. A model that volunteers `is_violation` has the field rejected by the same mechanism as any typo — `04_MODULES` §M9: *"This is why the ceiling is a schema property rather than a review process — it cannot be forgotten under deadline pressure."* |
| **V2 Vertical neutrality** | No domain vocabulary in the engine. Prompts are assets; attribute schemas are registry entries. |
| **V3 Ports over implementations** | P15 and P16 with executable conformance kits. No model name may appear above an adapter. |
| **V4 Explainability** | `raw_output` verbatim (U3), prompt version, model version + artifact hash, timing, decision path. Every one is mandatory, not optional. |
| **V5 Immutability** | Results are frozen values. A revision is a new result carrying `supersedes`, never an edit. |
| **V6 Single-writer state** | M9 owns no world state at all, which makes this trivially true — and is why the document says *"horizontally scalable"*. |
| **V7 Perceptual economy** | M9 is *"governed by M8 rather than by itself"*. M9 provides `estimate_cost` so M8 can decide; it never decides. |
| **V8 Blindness explicit** | `producible_attributes` is published *"so capability gaps are visible"*. A failed understanding emits **zero** attributes and says why — never a guess. |
| **V9 Degrade never die** | The understanding ladder (`10_RELIABILITY` §4.3) ends at *"attributes stop; presence/spatial CONTINUE"*. |
| **V11 Normalized time** | Attributes are stamped with the crop's capture time, not inference time. |
| **V12 Pixels stay local** | The crop's pixels are data-plane. The result carries a `raw_output_ref` and the reference travels. |
| **V13 Deterministic replay** | Cache key correctness; adapters declare `deterministic`; the decision path records which branch was taken. |

## 11. Implementation shortcuts that must be rejected

| Tempting | Why it is forbidden |
|---|---|
| Let an unregistered field through "just this once, it's obviously useful" | The ceiling is a schema property precisely so this is not a judgment call. Reject, count, record in `rejected_fields`. |
| Return a default value on timeout | U2. Fabricated output is indistinguishable from real output downstream. Emit zero attributes. |
| Convert `UNKNOWN` to `false` | A boolean attribute that was never determined is not a negative determination. `02_VOM` §7 keeps them distinct and the brief names this explicitly. |
| Present VLM self-confidence as calibrated | U4 and `02_VOM` §7.2 rule 3: `SELF_REPORTED` *"is a language model's opinion about itself and is not a probability."* |
| Cache on `(object_id, attribute)` | The documented key is `(CropId, prompt_version, model_version, attribute_set)`. Any other key produces stale attributes when a prompt or model changes. |
| Hard-code a prompt string in the engine | Gate 2 of the ceiling lives in M10. A prompt in code is a prompt with no version, no declared schema, and no validation. |
| Hard-code a model name in the engine | V3. `understander.router` exists so routing is data. |
| Keep conversation history for "better answers" | U5. Two identical requests must be independently answerable, *"or caching and replay both break."* |
| Retry forever on a systemic failure | `10_RELIABILITY` §2: systemic failures get worse with retry. Circuit-break. |
| Silently discard model output that did not parse | §9.3. It goes to `unstructured_note` — inspectable, never promoted. |
| Write the attribute straight into M7 | M7 is the only writer, and its write path is driven by M11's observation. M9 returning a value is not the same as M9 storing one. |

---

## 12. Ambiguities found — five, all resolved without inference

### 12.1 The brief names `PromptProviderPort`; the catalogue names P17 `PromptSourcePort`, owned by M10

**The conflict.** The task brief's document list says *"PromptProviderPort"*.
`06_PORTS` line 81 defines **P17 `PromptSourcePort`, owner M10**, adapters *"File,
git, object store, service"* — that is M10's port for loading prompt *assets*, not
M9's route to a *rendered* prompt.

**Resolution — the architecture wins.** There is no port between M9 and M10.
`04_MODULES` §M9 Dependencies lists *"Prompt Manager (M10)"* as a **module
dependency**, and §M10's Public API (`render`, `resolve`, `schema_of`) is the
interface M9 calls. So Flow 6 defines a narrow **consumer-side protocol** naming
exactly those three calls, which M10 will satisfy in a later flow. P17 is **not**
implemented and **not** made bindable — it belongs to M10.

Because M10 is out of scope, Flow 6 ships one reference provider in `adapters/`
serving prompts declared in configuration. It implements only what M9 needs to
run and explicitly **not** M10's responsibilities: no packs, no A/B, no shadow
variants, no hot reload, no model-family resolution. It is a stand-in, marked as
one, replaced in Flow 7.

### 12.2 `Evidence.observation_id` is mandatory, but M9 creates no observations

**The conflict.** `02_VOM` §10.9 declares `Evidence.observation_id:
ObservationId`. M9 must attach evidence (§M9 responsibility 5) and must never
build an observation.

**Resolution.** The two are compatible because the *field* belongs to the
completed evidence record, not to M9's contribution. M9 produces everything else
— `trigger_reason`, `input_hash`, `crop_ref`, `frame_ref`, `raw_output_ref`,
`unstructured_note`, `decision_path`, `timing` — and M11 stamps `observation_id`
when it assembles the observation that the evidence explains. Flow 6 therefore
models `UnderstandingEvidence` **without** `observation_id`, and the Flow 7 report
must show M11 completing it. Inventing an id here would be M9 minting an
identifier for an object it is forbidden to create.

### 12.3 `raw_output_ref: BlobRef` implies a blob store; M13 Storage is out of scope

**The conflict.** §M9's dependency list includes *"Storage (raw output blobs)"*
and the result declares `raw_output_ref: BlobRef`. M13 Storage Interfaces and P22
`EvidenceStorePort` belong to a later flow.

**Resolution — Flow 5's precedent, exactly.** M8 decides retention *policy* and
stamps it on the crop; it never writes. M9 does the same: it computes a
**content-addressed** `BlobRef` over the verbatim bytes and carries the bytes on
the result as a data-plane field that `without_raw_output()` strips. Persisting
them is M13's job through P22, which stays unbindable. Content addressing means
the reference is valid the moment the store exists, and identical output stored
twice is one blob — the same property that makes `CropId` work.

### 12.4 M9 enforces the registry, but `00_CHARTER` §4.3 names M11 as the third gate

**The conflict.** §M9 responsibility 8: *"Never emit an attribute key absent from
the Attribute Schema Registry."* `00_CHARTER` §4.3 names the three gates as the
Registry, the Prompt Manager, and the **Observation Builder** — not M9.

**Resolution.** These are not in tension; they are defence in depth, and the
charter names the *last* gate because it is the one that cannot be bypassed. M9's
check is a **producer-side** refusal: it declines to emit, records the field in
`rejected_fields`, and counts it. M11's check is the **constitutional** refusal:
it declines to publish. Flow 6 implements M9's; Flow 7 must still implement
M11's independently, and a test in Flow 7 should prove M11 rejects an unregistered
attribute even when handed one directly.

### 12.5 §M9's failure table names a class the taxonomy does not define

**The conflict.** §M9's failure table classifies *"Malformed / unparseable
output"* and *"Model refuses / safety-filters"* as **Data**. `10_RELIABILITY` §2
defines exactly six classes — Transient, Persistent, Poison, Systemic, Silent,
Byzantine — and *Data* is not among them.

**Resolution.** The mapping is unambiguous, so this is a terminology gap rather
than a conflict. `POISON` is defined as *"a specific input reliably causes
failure"* with the response *"quarantine the input, continue the stream"* — which
is precisely and completely what §M9 prescribes for both rows: quarantine to
`unstructured_note`, emit zero attributes, keep every other request running. Flow
6 classifies both as `POISON` and records the mapping in the error's docstring so
the next reader does not have to re-derive it.

---

## 13. Scope confirmation against `15_ROADMAP`

Confirmed **not** implemented:

| Deferred | Phase | Flow 6 posture |
|---|---|---|
| Temporal / action understanding | 3 | P15 takes `crops: CropView[]`; single-frame is *"the degenerate case"* and `15_ROADMAP` §4 says the module change is **None**. The contract shape ships; **no temporal adapter is bound**, and a guard asserts it. |
| Cross-camera reasoning, identity | 2 | P10/P11 remain unbindable, standing guards unchanged. |
| Learning pipeline | 4 | Evidence retention *is* the enabler and it ships; no training code exists. |
| Audio / depth / thermal fusion | 5 | Additive input fields, not added. |
| Automatic prompt optimization | later | M10's extension point, and M10 is not implemented. |
| Analytics, alerts, business rules | never (V1) | Nothing in M9 can express them. |

Also **not** implemented, because they are other modules: M10 Prompt Manager
(beyond a marked stand-in adapter), M11 Observation Builder, M12 Vision State,
M13 Storage Interfaces, M14 Observation API.

---

## 14. Compliance conclusion

M9 as specified is implementable exactly as written. Five ambiguities were found;
all five resolve in favour of the architecture, and none requires an architectural
change.

**No architectural change is requested. Implementation may proceed.**
