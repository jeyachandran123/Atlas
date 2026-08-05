# Implementation Flow 6 — M9 Vision Understanding Engine

**Status:** complete. `2,218` Vision OS tests pass; `309` are new.

> **Single responsibility:** *Ask a model what is true of these pixels, and return
> only what fits the declared schema.*

04_MODULES §M9 calls this *"the platform's only semantically ambitious component,
and therefore the one most tightly constrained."* Both halves are the design: it
is the only place an open-ended question is asked, and the constraint is what
keeps the answer usable.

---

## 1. Architecture Compliance Review

Performed **before any code was written** and recorded in full at
[`FLOW_6_COMPLIANCE_REVIEW.md`](FLOW_6_COMPLIANCE_REVIEW.md). It answers the
thirteen required questions and closes with: *"No architectural change is
requested. Implementation may proceed."*

Five ambiguities were found. Each was resolved **against the architecture**:

| # | Ambiguity | Resolution |
|---|---|---|
| 12.1 | The brief names `PromptProviderPort`; the catalogue defines P17 `PromptSourcePort` owned by **M10** | There is no port between M9 and M10 — §M9's dependency list names M10 as a **module** dependency. Flow 6 defines a consumer-side `PromptProvider` protocol naming exactly M10's three calls. **P17 is not implemented and not made bindable.** |
| 12.2 | `Evidence.observation_id` is mandatory in 02_VOM §10.9, but M9 creates no observations | The field belongs to the *completed* record. M9 produces everything else; M11 stamps `observation_id` when it assembles the observation. `UnderstandingEvidence` omits it deliberately — minting an id here would be M9 identifying an object it is forbidden to create. |
| 12.3 | `raw_output_ref: BlobRef` implies a store; M13 is out of scope | Flow 5's precedent exactly: M9 **content-addresses** the bytes and carries them data-plane; `without_raw_output()` strips them. P22 stays unbindable. |
| 12.4 | §M9 enforces the registry, but `00_CHARTER` §4.3 names **M11** as the third gate | Defence in depth, not tension. M9's is a **producer-side** refusal (declines to emit, records in `rejected_fields`); M11's is the **constitutional** refusal (declines to publish). Flow 7 must still implement M11's independently. |
| 12.5 | §M9's failure table names a class — *"Data"* — that `10_RELIABILITY` §2's taxonomy does not define | Terminology gap, not conflict. `POISON` is defined as *"a specific input reliably causes failure"* with the response *"quarantine the input, continue the stream"*, which is precisely what §M9 prescribes. Recorded in the error's docstring. |

**No architectural document was modified.** The architecture remains frozen.

---

## 2. Implementation Report

**14 files, 5,055 lines of implementation.**

| File | Lines | Role |
|---|---:|---|
| `perception/understanding/engine.py` | 998 | `UnderstandingEngine` — M9's public API, verbatim |
| `core/model/understanding.py` | 636 | `UnderstandingResult`, `UnderstandingEvidence`, `Timing`, `ModelMeta`, `PromptMeta`, `RejectedField`, 6 outcomes, 8 rejection reasons, 18 decision steps |
| `conformance/understanding_kits.py` | 420 | Executable kits for P15 (U1–U7) and P16 (X1–X4) |
| `core/ports/understanding.py` | 406 | **P15** `UnderstanderPort`, **P16** `OutputCoercionPort`, the M10 `PromptProvider` seam |
| `perception/understanding/runtime.py` | 385 | `UnderstandingRuntime` — the `CropConsumer` seam, batch coordinator |
| `adapters/understanding/understanders.py` | 366 | Scripted understander, specialized attribute head, unavailable terminal |
| `perception/understanding/routing.py` | 343 | `CapabilityRouter`, `RoutingPolicy`, `CircuitBreaker` |
| `perception/understanding/cache.py` | 325 | `ResponseCache`, `ModelSemaphore`, batch grouping |
| `understanding_bootstrap.py` | 290 | Composition root — the only module that selects an adapter |
| `perception/understanding/validation.py` | 278 | `AttributeValidator` — the schema gate |
| `adapters/understanding/prompts.py` | 271 | `StaticPromptProvider` — **a marked stand-in for M10** |
| `adapters/understanding/coercion.py` | 216 | JSON, key/value and passthrough coercion strategies |
| `perception/understanding/__init__.py` | 68 | Package surface |
| `adapters/understanding/__init__.py` | 53 | Closed factory table |

Plus additive edits: `core/model/ids.py` (`RequestId`, `PromptId`, `PackId`, `BlobRef`, `EvidenceId`), `core/errors.py` (7 understanding errors), `perception/registry/attributes.py` (`AttributeSchema.accepts`), `kernel/events/events.py` (3 events), `kernel/metrics/names.py` (22 metrics), `kernel/config/schema.py` + `manager.py` (`UnderstandingSection`), `kernel/plugins/manifest.py` (`FLOW6_PORTS`).

### The public API, verbatim from §M9

```text
understand(crop, requested_attributes, context)  → UnderstandingResult !UnderstandingFailed
understand_batch(requests)                       → Map<RequestId, UnderstandingResult>
capabilities()                                   → UnderstanderCapabilities
estimate_cost(requested_attributes)              → CostEstimate
health()                                         → ComponentHealth
```

All five implemented. `understand` **never raises** — §M9's governing property is
that *"understanding failure is never pipeline failure"*, so every documented
failure returns a result whose `outcome` names it and whose `decision_path` shows
how the engine got there.

### The six outcomes

`SUCCEEDED` · `NO_ATTRIBUTES` · `REFUSED` · `TIMED_OUT` · `UNAVAILABLE` ·
`UNSUPPORTED`. Deliberately not a boolean: *"we asked and nothing fit"* and *"we
never got to ask"* are different facts, and a consumer that cannot tell them
apart reads both as "no attributes" (V8).

---

## 3. Engine Interaction Report

```
                    ┌──────────────────────────────────────────┐
                    │  M8 Crop Manager (Flow 5)                │
                    │  EvaluationResult + Crop[]               │
                    └──────────────────┬───────────────────────┘
                                       │ CropConsumer  ← the Flow 6 seam
                                       ▼
     ┌───────────────────────────────────────────────────────────────┐
     │  UnderstandingRuntime    bounded queue · drop_oldest · counted │
     │   • never raises   • batches by (model, prompt)   • drains     │
     └──────────────────┬────────────────────────────────────────────┘
                        ▼
     ┌───────────────────────────────────────────────────────────────┐
     │  UnderstandingEngine                                          │
     │                                                               │
     │  CapabilityRouter ──► RoutingDecision(selected, fallbacks,    │
     │    (declared capability,          covered, uncovered)         │
     │     cost class, residency)             │                      │
     │                                        ▼                      │
     │  PromptProvider ──────► RenderedPrompt + OutputSchema  [M10]  │
     │                                        │                      │
     │  ResponseCache ◄── key(tenant, CropId, prompt@v, model, attrs)│
     │                                        │                      │
     │  ModelSemaphore ──► P15 UnderstanderPort ──► raw output       │
     │    (per model)          │  retry → fallback → unavailable     │
     │                         ▼                                     │
     │            P16 OutputCoercionPort ──► parsed + unparsed       │
     │                         │                                     │
     │            AttributeValidator ──► Attribute[] + RejectedField[]│
     │              (Attribute Schema Registry — M7's, shared)       │
     │                         ▼                                     │
     │                 UnderstandingResult + Evidence                │
     └───────────────────────────────────────────────────────────────┘
                                       │
                                       ▼  Flow 7
                          M11 Observation Builder
```

**Why routing precedes prompting.** A prompt is rendered for a *model family*, so
the model must be chosen first. Rendering before routing would either render once
per candidate (wasteful) or bind the platform to one family (V3 breach).

**Why the cache sits after prompting and before invocation.** The key includes the
prompt version, so it cannot be computed earlier — and it must be checked before
the expensive call, which is the only reason it exists.

**Why validation is last.** Coercion turns text into fields; validation turns
fields into *registered attributes*. Merging them would let a coercion strategy
decide what counts as an attribute, which is the registry's job.

---

## 4. Understanding Ownership Report

### The ownership chain

| Artefact | Owner | Writes | Reads | May never modify |
|---|---|---|---|---|
| **Frame pixels** | M4 Frame Buffer | M2 (publish) | M5, M8 via lease | Everyone else |
| **Crop** | M8 Crop Manager | M8 only | M9 (read-only, via the seam) | **M9** — it cannot re-crop, re-pad or re-grade |
| **Crop retention policy** | M8 | M8 stamps it | M13 honours it | M9 |
| **Attribute *schema*** | Attribute Schema Registry (M7's, Flow 4) | Registration only | M9 (validate), M10 (declare), M11 (enforce) | **M9** — it consults, never registers |
| **Attribute *value*** | **M9** produces | M9 | M11, M12 | M8, M7 |
| **Attribute *storage*** | M7 Object Registry | M7 via `apply_attribute` | Everyone | **M9** — returning a value is not storing one |
| **Prompt** | M10 Prompt Manager | M10 | M9 (render, resolve) | **M9** — it consumes, never authors |
| **Model artifacts, devices** | M18 Model Manager | M18 | M9 via handle | M9 |
| **Understanding evidence** | **M9** produces | M9 | M11, evidence API | Everyone after publication (V5) |
| **`observation_id` on evidence** | M11 | M11 stamps it | Everyone | **M9** — it may not identify what it cannot create |
| **Observation** | M11 Observation Builder | M11 only | M12, M14 | **M9** |
| **Vision State** | M12 | M12 | M14 | M9 |

### Exactly where ownership transfers

**M8 → M9.** At the `CropConsumer` seam. M8 hands a `Crop` and the demand that
caused it; M9 gains **read** access to the pixels for the duration of the call
and **no** rights over the crop object. The crop's lease belongs to M8 throughout.

**M9 → M11.** At the `UnderstandingResult`. M9 hands validated attribute *values*
with complete evidence; M11 gains the right to **assemble** them into an
observation and to **refuse** them. M9 retains nothing — the result is immutable
and M9 keeps no copy beyond the response cache, which is keyed on inputs and holds
no world state.

### Who writes, who reads, who can never modify

**M9 writes exactly three things**, all ephemeral and node-local:

1. its response cache,
2. its per-model circuit-breaker state,
3. its in-flight request accounting.

§M9's own words: *"Owns no world state. Every call is a pure function of (crop,
prompt, model)."*

**M9 reads** crops (M8), prompts (M10), the attribute schema registry (M7's), and
model handles (M18).

**M9 can never modify** a crop, an attribute schema, a Vision Object, an
observation, Vision State, or a prompt. Each is enforced by a test that reads the
source tree:

| Prohibition | Enforced by |
|---|---|
| No crop generation | `test_no_crop_generation_vocabulary` |
| No object registration | `test_no_object_registration_vocabulary` + `test_the_engine_never_constructs_a_platform_object` (AST) |
| No observation building | `test_no_observation_vocabulary` + `test_the_result_carries_no_observation_id` |
| No Vision State | `test_no_vision_state_vocabulary` + `test_it_holds_no_durable_store` (import scan) |
| No prompt authoring | `test_no_prompt_text_lives_in_the_engine` (AST string-constant scan) |
| No model coupling | `test_no_model_name_appears_in_the_platform` |

---

## 5. Understanding Lifecycle Report

```
 Crop + requested attributes (from M8)
        │
        ▼
 ROUTE ──── no capable model ──────────► UNSUPPORTED + CapabilityGap event
        │                                (a gap, not a fault — V8)
        ▼
 RESOLVE PROMPT ── none suitable ──────► UNSUPPORTED + CapabilityGap
        │          (M10's NoSuitablePrompt)
        ▼
 CACHE LOOKUP ── hit ──────────────────► result reused, cost 0, fresh evidence id
        │                                 key = (tenant, CropId, prompt@v,
        │                                        model@v, attribute set)
        ▼ miss
 ACQUIRE SEMAPHORE ── full ────────────► UNAVAILABLE (shed, never queued)
        │
        ▼
 INVOKE ──── timeout ──► RETRY once ──► timeout ──┐
        │                                          │
        │──── unavailable ─────────────────────────┤
        │                                          ▼
        │                                    NEXT FALLBACK
        │                                          │  (event published —
        │                                          │   a fallback is never silent)
        │                                          ▼
        │                                    chain exhausted
        │                                          │
        │                                          ▼
        │                                    UNAVAILABLE
        ▼
 RESPONSE
        │
        ├── refused ──────────────────► REFUSED, zero attributes,
        │                                refusal recorded as evidence
        ▼
 COERCE (P16) ── nothing parses ───────► note quarantined, zero attributes
        │
        ▼
 VALIDATE against the Attribute Schema Registry
        │
        ├── unregistered key ─────────► rejected · UNREGISTERED_KEY  ← the ceiling
        ├── not in output schema ─────► rejected · NOT_IN_OUTPUT_SCHEMA (U1)
        ├── wrong type / domain ──────► rejected · WRONG_TYPE | OUT_OF_DOMAIN
        ├── wrong class ──────────────► rejected · CLASS_NOT_APPLICABLE
        └── accepted ─────────────────► Attribute(SELF_REPORTED confidence,
                                                  valid_until, evidence_ref,
                                                  producer provenance)
        │
        ▼
 OUTCOME = SUCCEEDED (≥1 attribute) | NO_ATTRIBUTES (none survived)
        │
        ▼
 CACHE STORE (answers only — never failures)
        │
        ▼
 UnderstandingResult ── without_raw_output() ──► ~3 KB to M11 (V12)
```

**Five properties this lifecycle guarantees:**

1. **Nothing is fabricated.** Every failure path emits zero attributes, and
   `UnderstandingResult.__post_init__` refuses to construct a failed result that
   carries one. The type is the last line of defence.
2. **Nothing is discarded.** Every field the model produced is an accepted
   attribute, a `RejectedField` with a reason, or text in `unstructured_note`.
3. **A judgment and a typo are the same event.** Both are unregistered keys, so
   the ceiling *"cannot be forgotten under deadline pressure."*
4. **Failures are not cached.** A timeout is a fact about this moment, not about
   this crop; caching it would extend a one-second blip for the life of the entry.
5. **A fallback is never silent.** Every fallback writes a decision step *and*
   publishes an event, so it cannot quietly become permanent.

---

## 6. Evidence Provenance Report

02_VOM §10.9's whole argument is that a claim without its receipt is unusable.
Every field below exists because omitting it produces a failure nobody detects.

| Field | What it defends | Failure if absent |
|---|---|---|
| `trigger_reason` | **Why this was computed at all** | Six months on, a result is a number with no story. Inherited from the crop, never re-derived. |
| `input_hash` | Reproducibility | Two results with the same input and different answers prove non-determinism — a claim worth being able to *make* rather than suspect. |
| `crop_ref` | Subject | A claim that cannot name the pixels behind it is not evidence. Enforced: a result with an object and no crop reference cannot be constructed. |
| `frame_ref` | Temporal anchor | The instant the claim is about. |
| `raw_output_ref` | Verbatim record (U3) | Without the model's own words, V4 is theoretical and no future learning pipeline has training data. |
| `unstructured_note` | Diagnosability | 02_VOM §9.3: *"the practical difference between a diagnosable platform and one where model behaviour is a black box."* |
| `decision_path` | Explainability | *"That the primary model timed out, the fallback ran... six months later, that is the difference between explaining a result and guessing at it."* |
| `timing` | Cost and latency attribution | A p99 that is really a cold start is a different problem from one that is really a queue. |
| `model_used` (id + version + **artifact hash**) | Which weights answered | A version string is a label a human chose; the hash is what actually ran. |
| `prompt_used` (id + version + content hash) | Which instruction was given | *"Provenance is worthless if `prompt@3.2.0` means different things on different days."* |
| `provenance` (config revision) | Reproducibility of the platform, not just the model | Without it no result is reproducible (V4). |

### Confidence provenance

Every attribute M9 produces carries `SELF_REPORTED` confidence, labelled at the
moment of creation. 02_VOM §7.2 rule 3: it *"is a language model's opinion about
itself and is not a probability."* Two consequences are tested:

* a model that offers no confidence does **not** get 1.0 — that would manufacture
  certainty the platform never received;
* an out-of-range score is clamped for `value` but **not** preserved as
  `raw_score`, because preserving an invalid number as if it were valid is worse
  than not preserving it.

### The chain, end to end

```
Crop.trigger_reason      ──► Evidence.trigger_reason      (why we looked)
Crop.crop_id             ──► Evidence.crop_ref            (which pixels)
Crop.source_frame        ──► Evidence.frame_ref           (which instant)
Crop.t_capture           ──► Attribute.observed_at        (world time, V11)
RenderedPrompt.pinned    ──► PromptMeta.pinned            (which question)
ModelMeta.artifact_hash  ──► Provenance.model_artifact_hash (which weights)
sha256(raw output)       ──► Evidence.raw_output_ref      (what it said)
DecisionRecord[]         ──► Evidence.decision_path       (how we got there)
AttributeSchema.version  ──► Attribute.schema_version     (what it means)
```

Verified end to end by `test_the_result_is_fully_traceable`, which asserts all
six traceability targets the brief requires — camera, frame, track (through the
object), object, crop, prompt version and model version — on one result.

---

## 7. Dependency Graph

```
core/model/understanding.py ──► confidence, crop (TriggerReason), ids,
                                 provenance, timebase, visual_object (Attribute)
core/ports/understanding.py ──► model/{ids, timebase, understanding}

perception/understanding/validation.py ──► core/{model, ports}, registry/attributes
perception/understanding/routing.py    ──► core/model/ids, core/ports/understanding
perception/understanding/cache.py      ──► core/model/{ids, timebase, understanding}
perception/understanding/engine.py     ──► the three above
                                            + core/ports/{clock, understanding}
                                            + kernel/{config, events, metrics}
                                            + registry/attributes
perception/understanding/runtime.py    ──► engine + core/model/crop
                                            + kernel/{config, health, metrics}

adapters/understanding/* ──► core only. No adapter imports another adapter.

understanding_bootstrap.py ──► adapters + conformance + perception
                                + cropping_bootstrap
```

**Direction, verified mechanically:**

* `perception/understanding/` imports **no adapter**.
* `acquisition/`, `kernel/`, `perception/{detection,tracking,registry,cropping}/`
  import **nothing** from understanding — the dependency runs one way and M8 holds
  a callable it never types.
* `core/` remains stdlib-only; the two new core modules import only `dataclasses`,
  `enum`, `typing`, `collections.abc` and (for content addressing) `hashlib`.
* Understanding imports the **Attribute Schema Registry** from
  `perception/registry/attributes.py`. That is deliberate and is *not* a layer
  violation: the registry is the ceiling's first gate and a shared vocabulary, and
  a second copy would drift. Verified by
  `test_the_registry_attribute_vocabulary_is_shared_not_copied`, which asserts
  identity rather than equality.

---

## 8. Runtime Integration Report

08_RUNTIME §1 assigns M9 a **batch coordinator + device worker**, and §M9 explains
why its shape differs from every other module's: *"VLM calls are long (100 ms – 2
s), so the module is concurrency-bound rather than throughput-bound."*

**Batching by `(model, prompt_version)`.** Only compatible requests batch together
— two prompts are two questions, and answering one while attributing it to both
is fabrication with extra steps. Composition is a pure function of input, which
08_RUNTIME §4.3 requires of deterministic mode and which makes a replay batch
identically.

**A semaphore per model, not one globally.** A remote API's rate limit and a local
GPU's memory are different constraints with different numbers. Remote adapters get
their own, tighter budget. 08_RUNTIME §4.4: *"Long VLM calls are not preempted;
instead concurrency is capped so that the detector's latency budget is
protected."* Verified under 8 threads.

**Shedding, not queueing, at the semaphore.** A blocked call outlives the frame it
describes. 08_RUNTIME §5.2 gives this edge `drop_oldest` because *"losing an
enrichment is acceptable"* — and §5.1 requires the drop be counted, never silent.

**The seam.** `UnderstandingRuntime.on_crops` attaches at
`CropRuntime(sink=…)` — the extension point the Flow 5 report declared. M8 remains
unaware of M9: it holds a callable and never learns what implements it. The
bootstrap schedules rather than awaits, so a 2-second model call never sits on the
critical path of a layer whose budget is measured in microseconds.

**No global mutable state.** Every counter is an instance attribute; the cache and
semaphores are owned by the engine; the circuit breakers are per model, per engine.

---

## 9. Performance Report

11_PERFORMANCE §1.1 puts a VLM call at **~200 ms** against a detection's 15 ms and
a crop's microseconds — and §1.2 states the consequence: *"understanding dominates
or is negligible, with nothing in between."*

| Lever | Architecture's claim | Implementation |
|---|---|---|
| **Attribute batching in one prompt** | *"3–5× saving"* | `RoutingPolicy.prefer_coverage` — one understander covering the whole request beats a cheaper one covering part |
| **Request batching across objects** | Local VLMs batch well | `group_for_batching`, bounded by `max_batch_size`, grouped by `(model, prompt)` |
| **Content-addressed caching** | *"Free correctness on repeated crops"* | `ResponseCache`, key = `(tenant, CropId, prompt@v, model@v, attribute set)` |
| **Model tiering / specialized heads** | *"~100× cheaper"* | Cost-class routing. `test_a_specialized_head_beats_a_vlm_on_cost` is 11_PERFORMANCE §7's migration, executable |
| **Constrained decoding** | Cuts output tokens, guarantees conformance | `supports_structured_output` capability; the engine skips coercion when an adapter has already parsed |
| **Cost estimation before spend** | M8's budget decides | `estimate_cost` (U7) — answers the question, never acts on it |

### Measurements

Every metric §M9 and 11_PERFORMANCE ask for is emitted:

| Measurement | Metric |
|---|---|
| Latency | `understanding.latency_ms`, labelled by model |
| Batch efficiency | `understanding.batch_size` — stuck at 1 means the lever is disengaged |
| Cache hit ratio | `understanding.cache_hits` / `cache_misses`, and `health().metrics["cache_hit_rate"]` |
| Throughput | `understanding.results`, labelled by outcome |
| Queue depth | `understanding.queue_depth`, with an `overflow` label on drops |
| Model utilization | `understanding.in_flight`, `concurrency_rejected`, `ModelSemaphore.peak` |
| Cost estimation | `understanding.cost_units` — the number 11_PERFORMANCE §7's migration is measured in |
| Reliability | `timeouts`, `retries`, `fallbacks`, `circuit_open`, `refusals`, `adapter_errors` |
| Ceiling health | `attributes_rejected` labelled by reason; `schema_drift_alarms` |

### Bounded resources, verified under load

| Resource | Bound | Test |
|---|---|---|
| Response cache | LRU + TTL, tenant-keyed | `test_the_cache_stays_bounded_under_load` (5,000 inserts) |
| Circuit breakers | One per **model**, not per request | `test_a_flood_of_failures_does_not_leak_breakers` (100 failures) |
| Drift window | Rolling | `test_the_drift_window_stays_bounded` (500 results) |
| Unstructured note | 4,096 chars, truncation **marked** | `test_a_long_note_is_bounded_and_marked` |
| Rejected value | 256 chars | validation module constant |
| Coercion scan | 64,000 chars | `test_a_runaway_generation_is_preserved_not_scanned` |

---

## 10. Test Report

**309 new tests**, all passing. Total Vision OS suite: **2,218 passing**.

| File | Tests | Category |
|---|---:|---|
| `unit/test_engine.py` | 49 | Public API, schema gate, reliability ladder, cache, cost, batching, health, drift alarm |
| `unit/test_adapters.py` | 47 | Coercion strategies, prompt provider, reference understanders |
| `unit/test_validation.py` | 37 | The ceiling, value validation, applicability, confidence, staleness, accounting |
| `unit/test_cache_and_concurrency.py` | 36 | Cache key correctness, batching, bounded concurrency |
| `test_understanding_architecture.py` | 35 | Boundaries, no model coupling, no prompt authoring, ceiling, biometrics, flow scope |
| `unit/test_routing.py` | 28 | Capability routing, fallback chains, circuit breaker |
| `integration/test_end_to_end.py` | 23 | Flows 1–6, real modules, composition root, seam |
| `test_understanding_determinism.py` | 19 | Replay, time independence, stress, concurrency, evidence completeness |
| `unit/test_conformance.py` | 18 | Kits pass shipped adapters, **fail broken ones** |
| `unit/test_runtime.py` | 17 | Seam, firewall, queue, output, concurrent delivery |

Every category the brief lists is covered: unit, integration, architecture,
boundary, capability routing, cache, retry, fallback, schema validation,
confidence, concurrency, stress, replay, conformance, broken adapter, regression
(the 1,909 pre-existing tests).

### Coverage of the Flow 6 surface

| Module | Coverage |
|---|---:|
| `perception/understanding/validation.py` | 97% |
| `adapters/understanding/coercion.py` | 97% |
| `perception/understanding/routing.py` | 96% |
| `adapters/understanding/understanders.py` | 94% |
| `perception/understanding/runtime.py` | 93% |
| `perception/understanding/engine.py` | 92% |
| `perception/understanding/cache.py` | 92% |
| `core/model/understanding.py` | 91% |
| `adapters/understanding/prompts.py` | 91% |
| `core/ports/understanding.py` | 90% |
| `understanding_bootstrap.py` | 90% |
| `conformance/understanding_kits.py` | 85% |

### The kits are tested against broken adapters

Eleven deliberately non-conforming adapters ship in the test suite:
`_LeakingUnderstander` (U1), **`_FabricatingUnderstander` (U2)**,
`_AmnesiacUnderstander` (U3), `_StatefulUnderstander` (U5),
`_DroppingUnderstander`, `_MuteUnderstander`, `_InventingCoercion` (X1),
`_DiscardingCoercion` (X2), `_RaisingCoercion` (X4), `_PromotingCoercion` (X1),
and `LeakyUnderstander` in the fixtures.

`test_the_fabrication_check_is_in_the_fast_subset` asserts that the U2 check runs
at **plugin load**, not only in a full suite — an adapter that fabricates must be
refused before a single real crop is processed.

---

## 11. Architectural Discoveries

Six defects were found during implementation. Four were caught by the platform's
own invariants rather than by an assertion written for the occasion.

**1. A vector attribute could never be accepted.** `AttributeSchema.accepts`
applied the cardinality check structurally, and a `VECTOR` value *is* a list — so
at the default `SINGLE` cardinality every vector looked like a multi-value and was
refused. A whole value type was unusable. Fixed by special-casing `VECTOR`, whose
single value is itself a sequence.

**2. A circuit breaker opening at monotonic time zero never reported open.**
`opened_at_ns` used `0` as its closed sentinel, and a virtual clock starts at
zero — so every deterministic test silently exercised the circuit-*closed* path,
and a breaker that tripped on the first call at boot would never have engaged.
Fixed with `None`.

**3. A relation domain violation was misattributed.** The schema's message said
*"is not a declared referent class"* while the reason mapper looked for *"outside
the declared domain"*, so a real domain violation was recorded as
`UNPARSEABLE_VALUE`. An operator would have gone looking for a formatting bug
instead of a vocabulary gap.

**4. `prompt_provider or build_prompts()` discarded an empty provider.**
`StaticPromptProvider` defines `__len__`, so an *empty* one is falsy — and a test
deliberately passing an empty catalogue silently got the full one, meaning the
no-prompt path was never exercised. This is the third flow in which the
truthiness trap has appeared on an object with `__len__`; the production code
already used `is None`, and the test helper now does too.

**5. §M9's failure table names a class the taxonomy does not define.** *"Data"* is
not one of `10_RELIABILITY` §2's six. Mapped to `POISON` — whose documented
response, *"quarantine the input, continue the stream"*, is exactly what §M9
prescribes — and recorded in the error docstring so the next reader need not
re-derive it.

**6. A U1-compliant adapter cannot test the platform's ceiling.** The shipped
`ScriptedUnderstander` filters undeclared fields itself, correctly. That meant
every schema-gate test passed without the gate doing anything. A deliberately
non-conforming `LeakyUnderstander` was added to the fixtures, because a defence
can only be tested against the attack — and a real VLM volunteering
`{"posture": "standing", "is_violation": true}` is exactly that attack.

### What went right

Three of the six were caught by construction-time validation in the platform's own
types — `UnderstandingResult` refusing a failed result with attributes,
`UnderstandingEvidence` refusing an unhashed input, `Confidence` refusing an
out-of-range raw score. That is the fourth flow in a row where the invariants have
been load-bearing rather than decorative.

---

## 12. Known Limitations

Stated plainly rather than papered over.

**No VLM ships.** 06_PORTS lists Qwen2.5-VL, GPT-4.1 Vision and the rest as
adapter *examples*; binding one needs weights, a runtime and a device — M18's
concern and a deployment's choice. What ships is a scripted understander, a
specialized attribute head and an always-unavailable terminal. The platform is
therefore fully testable and produces no real attributes until an adapter is
bound. This is deliberate, and `test_no_vlm_ships_as_an_adapter` keeps it true.

**The prompt provider is a marked stand-in for M10.** It serves versioned,
pinned, registry-validated prompts — enough for M9 to run and be tested — and
explicitly **not** prompt packs, A/B or shadow variants, model-family resolution,
hot reload, or the full neutrality gate on declarations. Those are M10's, and
building them here would be implementing a module out of scope. The seam is
narrow (three calls) precisely so M10 replaces it without touching M9.

**The conformance kits cannot measure correctness.** No check can tell whether a
model's answers are *right*. That needs a labelled corpus — 06_PORTS §5.1's
"golden data" section — which is a per-deployment asset. The kits verify
contracts: the structural properties whose violation is silent. Stated in the kit
module's own docstring so nobody mistakes a green kit for a quality guarantee.

**Retry backoff is not slept.** `retry_backoff_ms` is configured and recorded but
the engine does not block between attempts — sleeping inside a synchronous engine
call would hold a semaphore slot while doing nothing. A production deployment
running a batch worker should apply the backoff at the worker level; the
configuration key exists so that change needs no schema edit.

**Temporal understanding is contract-only.** `UnderstandingRequest.crop_ids` and
`UnderstandingPortRequest.crops` are sequences, matching P15, so 15_ROADMAP §4's
Phase 3 needs *"no contract change"*. No shipped adapter declares
`supports_temporal`, and a guard asserts it — an adapter that quietly accepted a
sequence and read one frame would produce an answer about an instant labelled as
an answer about a span.

**Cost estimation is capability-declared, not measured.** `estimate_cost` returns
the adapter's declared cost class. A deployment wanting real token-level costing
binds an adapter that computes it; the port already asks for it (U7).

**One Flow 4 file was extended.** `AttributeSchema` gained `accepts` — a pure
method on the schema, with no behaviour change to any existing call. Value
validation lives with the schema that declares the values, because a second
implementation of "fits" would drift and the drift would surface as attributes
the registry considers illegal sitting in the observation log.

**The wider Atlas suite has 82 pre-existing failures** in `tests/unit`,
`tests/integration` and `tests/vision`. None reference `vision_os` or
understanding; none were introduced by this flow.

---

## 13. Future Extension Points

| Extension point | Where | For |
|---|---|---|
| `UnderstandingResult` consumer | `UnderstandingRuntime(sink=…)` | **Flow 7.** The Observation Builder attaches here, as M9 attached to M8. |
| `UnderstanderPort` (P15) | `core/ports/understanding.py` | Qwen2.5-VL, Gemma Vision, InternVL, GPT-4.1V, Claude Vision — **and specialized non-generative models**: classifiers, pose estimators, OCR, attribute heads. |
| `understander.router` composite | a P15 adapter | Routes each attribute to the cheapest capable adapter behind one port. The migration path 11_PERFORMANCE §7 describes, attribute by attribute, in production. |
| `OutputCoercionPort` (P16) | `core/ports/understanding.py` | JSON-schema constrained decoding, grammar-constrained generation, logit-biased classification. |
| `PromptProvider` seam | `core/ports/understanding.py` | **M10 Prompt Manager**, which replaces the stand-in. Three calls, unchanged. |
| `PromptSourcePort` (P17) | catalogue | M10's own port — file, git, object store, service. Not bindable until M10 ships. |
| `RoutingPolicy` | `perception/understanding/routing.py` | Cost-optimizing, accuracy-tiered, A/B, shadow. |
| Temporal crops | `UnderstandingPortRequest.crops` | Phase 3. The contract already accepts sequences. |
| Multi-modal fusion | `UnderstandingPortRequest` | Phase 5. Additive input fields — audio, depth, thermal alongside the crop. |
| `EvidenceStorePort` (P22) | `core/ports/` | Persisting `raw_output`. M9 content-addresses it; M13 stores it. |
| Calibration profiles | M18 Model Manager | `SELF_REPORTED` becomes `ATTRIBUTE` with `calibrated: true` — a platform capability, not a model one (02_VOM §7.2 rule 4). |
| `UnderstandingSection` | `kernel/config/schema.py` | New reliability and concurrency knobs, strongly typed and validated. |

**Frontier discipline.** `BINDABLE_PORTS` is now
`FLOW1 | … | FLOW6`. Every later-flow port stays defined and unbindable, and
`test_synthesis_and_state_ports_remain_unbindable` fails if that changes before
Flow 7. `EmbeddingPort` (P10) and `IdentityResolverPort` (P11) are guarded
**separately and permanently** — they are the biometric and cross-camera-identity
capabilities, C2 and policy-gated.

---

## Final Verification

✓ **Flow 1 unchanged.** No acquisition or kernel module was modified except
additively: five id types, seven errors, three events, twenty-two metric names,
one config section, one repaired `Event.payload` shape. All Flow 1 tests pass.

✓ **Flow 2 unchanged.** No detection module was touched. All Flow 2 tests pass.

✓ **Flow 3 unchanged.** No tracking module was touched. All Flow 3 tests pass.

✓ **Flow 4 unchanged except through an additive extension.**
`AttributeSchema.accepts` was added — a pure method, no behaviour change to any
existing call. All Flow 4 tests pass.

✓ **Flow 5 unchanged.** M8 gained a consumer at its declared `sink` extension
point and learned nothing about M9. All Flow 5 tests pass.

✓ **M9 consumes only Canonical Crops.** The runtime builds every request from a
`Crop` plus the `CropRequest` that caused it, and never from anything else.

✓ **M9 never performs detection.** No detection vocabulary exists in the module;
enforced by AST scan.

✓ **M9 never performs tracking.** Same guard, same scan.

✓ **M9 never performs object registration.** It cannot construct `VisualObject`,
`ObjectId`, `Track`, `Detection` or `Crop` — enforced by AST call-site scan.

✓ **M9 never performs observation generation.** No observation vocabulary; the
evidence deliberately carries no `observation_id`, because M9 may not identify
what it cannot create.

✓ **M9 never updates Vision State.** It imports no filesystem, database or
serialization module, and names no store port.

✓ **M9 never performs business reasoning.** No business vocabulary; the result
carries no judgment field; a model volunteering one has it rejected by the same
mechanism as a typo.

✓ **Every attribute is schema validated.** Registered key, declared by the
prompt, applicable to the class, and a value inside its declared domain — four
checks, in that order, each with its own rejection reason.

✓ **Every result preserves evidence.** Input hash, crop reference, frame
reference, raw-output reference, decision path and timing — on success and on
failure alike.

✓ **Every result preserves provenance.** Model id, version and artifact hash;
prompt id, version and content hash; config revision.

✓ **Every model remains replaceable.** No model name appears anywhere above an
adapter. Routing reads declared capability and cost class. Two conformance kits
gate activation.

✓ **A future Observation Builder can consume Understanding Results without
modification.** The result is immutable, self-describing, control-plane sized
(~3 KB after `without_raw_output()`), and carries everything M11 needs to build
an observation — including the gap where `observation_id` will be stamped.

✓ **No future roadmap functionality has been implemented.** No M10 packs, no M11,
no M12, no M13, no M14, no temporal adapter, no cross-camera reasoning, no
learning. Guarded by directory-existence and port-bindability tests in four
separate suites.

---

## Summary

| Metric | Value |
|---|---:|
| Implementation files | 14 |
| Implementation lines | 5,055 |
| Test files | 11 |
| Test lines | 4,521 |
| New tests | 309 |
| Vision OS tests passing | 2,218 |
| Flow 6 coverage | 85–100% |
| Ports implemented | 2 (P15, P16) + 1 module seam |
| Conformance obligations | 11 (U1–U7, X1–X4) |
| Broken adapters proving the kits work | 11 |
| Architecture documents modified | **0** |
| Defects found and fixed during implementation | 6 |
