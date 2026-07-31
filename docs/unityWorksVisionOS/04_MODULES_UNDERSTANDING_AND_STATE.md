# UnityWorks Vision OS (UWV)

## Phase 1 — Module Specifications II: Understanding, Synthesis, State & Exposure

| | |
|---|---|
| **Status** | Architecture Blueprint — Phase 1 (Design Only) |
| **Prerequisite** | `00`–`03` |
| **Covers** | Vision Understanding Engine · Prompt Manager · Observation Builder · Vision State Manager · Storage Interfaces · Observation API |

---

## Table of Contents

- [M9 · Vision Understanding Engine](#m9--vision-understanding-engine)
- [M10 · Prompt Manager](#m10--prompt-manager)
- [M11 · Observation Builder](#m11--observation-builder)
- [M12 · Vision State Manager](#m12--vision-state-manager)
- [M13 · Storage Interfaces](#m13--storage-interfaces)
- [M14 · Observation API](#m14--observation-api)

---

# M9 · Vision Understanding Engine

### Purpose

Convert a region of pixels into **structured, schema-conformant claims** — the platform's only
semantically ambitious component, and therefore the one most tightly constrained.

> **Single responsibility:** *Ask a model what is true of these pixels, and return only what fits the
> declared schema.*

### Responsibilities

1. Select the appropriate understander model for a requested attribute set (capability + cost + policy).
2. Obtain the rendered prompt and its declared output schema from the Prompt Manager (M10).
3. Invoke the understander adapter, batching where the adapter supports it.
4. **Coerce raw model output into the declared schema**, and quarantine what does not fit.
5. Attach raw output as evidence (`02_VOM` §9.3).
6. Apply per-attribute confidence semantics, marking VLM self-reports as `SELF_REPORTED`.
7. Enforce timeouts, retries, and fallback model chains.
8. Never emit an attribute key absent from the Attribute Schema Registry.

**Explicitly not responsible for:** deciding whether the analysis was worth doing (M8), or assembling
the published observation (M11).

### Public API

```text
understand(crop, requested_attributes, context) → UnderstandingResult !UnderstandingFailed
understand_batch(requests)                      → Map<RequestId, UnderstandingResult>
capabilities()                                  → UnderstanderCapabilities
estimate_cost(requested_attributes)             → CostEstimate
health()                                        → ComponentHealth
```

```text
UnderstandingResult:
  attributes        : Attribute[]          # schema-conformant only
  rejected_fields   : [(field, reason)]    # model said it; schema refused it
  unstructured_note : text?                # preserved as evidence, never promoted
  raw_output_ref    : BlobRef
  model_used        : ModelId + version + artifact_hash
  prompt_used       : PromptId + version
  timing            : Timing
  decision_path     : DecisionStep[]
```

```text
UnderstanderCapabilities:
  producible_attributes : AttributeKey[]     # published so capability gaps are visible (V8)
  input_constraints     : resolution, aspect, colour, max batch
  supports_structured_output : bool          # constrained decoding available?
  supports_batching     : bool
  cost_class            : relative cost unit
  deterministic         : bool
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| `Crop` + requested attribute set (M8) | `Attribute[]`, schema-validated |
| Rendered prompt + output schema (M10) | Raw output reference (evidence) |
| Model handle (Model Manager) | Rejection records, timing, decision path |
| Object context (class, prior attributes, quality) | Cost telemetry |

### Dependencies

Crop Manager (M8), Prompt Manager (M10), Model Manager, Understander port (adapter), Attribute Schema
Registry, Storage (raw output blobs), Metrics, Event Bus.

### State Ownership

**Owns:** in-flight request tracking, batch accumulation, per-model circuit breaker state, response
cache keyed by `(CropId, prompt_version, model_version, attribute_set)`.

The cache key is worth noting: because `CropId` is a content hash and prompt/model versions are
explicit, the cache is **correct by construction** — a cache hit is guaranteed to be the answer the
current configuration would produce. Caches keyed on object id or timestamp instead are the usual
source of stale-attribute bugs.

Owns no world state. Every call is a pure function of (crop, prompt, model).

### Thread Safety

**Batching coordinator + bounded concurrency per model.** VLM calls are long (100 ms – 2 s), so the
module is concurrency-bound rather than throughput-bound. Design:

- Requests are grouped by `(model, prompt_version)` — only compatible requests batch together.
- A **semaphore per model** caps in-flight requests to what the device or remote endpoint sustains.
- Remote adapters (cloud vision APIs) use a separate concurrency budget and their own rate limiter.
- All state is per-request; the module is otherwise stateless and horizontally scalable.

### Failure Handling

| Failure | Classification | Response |
|---|---|---|
| Timeout | Transient | Retry once with backoff; then fallback model; then fail the request. **Never block the pipeline** — the object simply has no attribute this round, and the skip is recorded |
| Malformed / unparseable output | Data | Attempt structured re-parse; then a single constrained re-ask; then quarantine to `unstructured_note` and emit **zero** attributes |
| Model emits an unregistered attribute key | **Ceiling violation** | Reject the field, count, record in `rejected_fields`. If the rate is sustained, alarm — this means a prompt has drifted beyond its declared schema |
| Model emits a judgment ("this is a violation") | **Ceiling violation** | Rejected by the same mechanism; it is simply an unregistered key. **This is why the ceiling is a schema property rather than a review process** — it cannot be forgotten under deadline pressure |
| Model refuses / safety-filters | Data | Record refusal as evidence; emit no attributes; count |
| Device OOM | Transient→Systemic | Reduce batch and concurrency; notify Model Manager |
| Remote endpoint rate-limited | Transient | Respect backoff, shed load to budget, inform M8 to reduce trigger rate |
| Model consistently low quality on a class | Persistent | Surfaced through metrics; the correct response is a model or prompt change, not a platform change |
| Adapter crash | Systemic | Circuit-break; fall back; if no fallback, attributes stop while detection/tracking continue (V9) |

**The most important property:** understanding failure is **never** pipeline failure. Detection,
tracking, identity, and spatial observations continue unaffected; only enrichment is lost. This is the
direct benefit of the dotted edges in `01_LAYERED` §3.

### Performance

The most expensive component per invocation, and therefore governed by M8 rather than by itself.

| Lever | Effect |
|---|---|
| **Attribute batching in one prompt** | Ask for 5 attributes in one call rather than 5 calls — usually a 3–5× saving |
| **Request batching across objects** | Local VLMs batch well; remote APIs usually do not |
| **Quantization (INT8/INT4)** | 2–4× throughput and much smaller residency, at measurable accuracy cost |
| **Model tiering** | A small VLM for routine attributes; a large one for ambiguity |
| **Specialized heads instead of a VLM** | A dedicated classifier for `headwear_present` is ~100× cheaper than a general VLM. **The port makes this a configuration choice, not a rewrite** |
| **Constrained decoding** | Guarantees schema conformance and cuts output tokens |
| **Content-addressed caching** | Free correctness on repeated crops |

> **The strategic point.** Today a VLM answers everything because it is flexible and no training is
> required. Over five years, high-volume attributes migrate to cheap specialized models while rare and
> novel ones stay on the VLM. Because both sit behind the same port and produce the same registered
> attributes, **that migration is a configuration change and consumers never notice.** Designing for
> this migration is the main reason understanding is a port rather than a hardcoded VLM call.

### Extension Points

- **Understander adapters** (port): Qwen2.5-VL, Gemma Vision, InternVL, LLaVA-family, GPT-4.1 Vision,
  Claude Vision, Gemini Vision, future frontier models, **and specialized non-generative models**
  (classifiers, pose estimators, OCR, attribute heads).
- **Output coercion strategies** (port): JSON-schema constrained decoding, grammar-constrained
  generation, regex extraction, logit-biased classification.
- **Model selection policies** (port): capability-based, cost-optimizing, accuracy-tiered, A/B, shadow.
- **Multi-frame understanding**: temporal crops for motion-dependent attributes. The port takes a crop
  *sequence*; single-frame is the degenerate case, so this needs no contract change.
- **Multi-modal fusion**: audio, depth, thermal alongside the crop — additive input fields.

---

# M10 · Prompt Manager

### Purpose

Own prompts as **versioned, validated, deployable assets** bound to declared output schemas — so that
prompt evolution is a governed asset change rather than an edit buried in code.

> **Single responsibility:** *Produce the exact instruction for a model, and guarantee its declared
> output schema is legal.*

### Responsibilities

1. Store and version prompt templates, organized into **prompt packs**.
2. Bind each prompt to a **declared output schema** referencing registered attribute keys.
3. **Validate prompts at load**: every declared output key must exist in the Attribute Schema Registry,
   and pass the neutrality gate — the second of the three ceiling enforcement points
   (`00_CHARTER` §4.3).
4. Render templates with context (object class, requested attributes, quality hints, prior values).
5. Resolve model-specific variants — the same logical prompt phrased for different model families.
6. Support A/B and shadow prompt variants for evaluation.
7. Provide immutable `prompt_id@version` for provenance on every observation.

### Public API

```text
render(prompt_id, version, context)   → RenderedPrompt !NotFound !RenderError
resolve(attribute_set, model_family)  → (PromptId, version) !NoSuitablePrompt
schema_of(prompt_id, version)         → OutputSchema
list_pack(pack_id)                    → PromptDescriptor[]
load_pack(pack, source)               → LoadResult !ValidationFailed
variants(prompt_id)                   → Variant[]        # A/B and shadow
```

```text
Prompt:
  prompt_id       : PromptId
  version         : SemVer               # immutable once published
  pack_id         : PackId
  template        : parameterized text
  output_schema   : OutputSchema          # keys MUST be registry-registered
  applies_to      : ClassId[]
  model_families  : [family → variant template]
  input_expectations : crop size, padding, colour
  eval_reference  : evaluation set + last measured scores
  status          : draft | published | deprecated
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| Prompt pack assets (files, object storage, config repo) | Rendered prompts with declared schemas |
| Attribute Schema Registry (validation) | Prompt provenance identifiers |
| Rendering context from M9 | Validation results |
| Model family declarations | Variant assignments |

### Dependencies

Attribute Schema Registry, Configuration Manager, Storage Interfaces (pack assets), Metrics, Event Bus.
**No dependency on any model** — prompts are assets, not inference.

### State Ownership

**Owns:** the loaded prompt catalogue, compiled templates, variant assignment state, validation
results. Read-mostly, snapshot-versioned, hot-reloadable.

### Thread Safety

Copy-on-write catalogue with atomic swap on reload. Rendering is a pure function over an immutable
template and is trivially parallel. A hot reload never affects in-flight renders, and every rendered
prompt records the exact version used — so an observation made during a reload is still explicable.

### Failure Handling

| Failure | Response |
|---|---|
| Prompt references an unregistered attribute | **Load rejected.** The pack does not load. This is the ceiling's second gate and it fails at deploy time rather than at inference time |
| Declared output key fails the neutrality gate | **Load rejected** with the specific key named |
| Template render error (missing context) | Fail the single request, count, fall back to the previous prompt version; never crash the engine |
| Prompt pack unavailable at startup | Fail startup loudly. Running with no prompts is worse than not running — it silently produces a platform with no attributes |
| Prompt pack unavailable at hot reload | Keep the current catalogue, alarm. Never degrade a running system for a failed reload |
| No prompt for a requested attribute set | Return `NoSuitablePrompt`; M8 records a **capability gap** so the consumer learns the demand is unsatisfiable (V8) |
| A published version is mutated in the asset store | Detected by content hash; rejected. **Published versions are immutable** — provenance is worthless if `prompt@3.2.0` means different things on different days |

### Performance

Rendering is microseconds and off the critical path relative to a 200 ms model call. Templates are
compiled once at load. The only real performance consideration is **prompt length**, which directly
drives VLM cost — prompt packs are evaluated on token count as well as accuracy, because a 30% longer
prompt is a 30% larger bill at 15 calls/second, forever.

### Extension Points

- **Prompt sources** (port): filesystem, git repository, object storage, config service, a future
  prompt-management service.
- **Template engines** (port).
- **Variant/experiment strategies** (port): fixed, A/B by hash, shadow (evaluated but not published),
  contextual bandit (future).
- **Automatic prompt optimization** (future): because prompts are versioned assets with evaluation
  references and every observation records the prompt that produced it, an optimization loop has
  everything it needs — built later, enabled now.
- **Domain prompt packs**: a restaurant pack, a warehouse pack, a hospital pack. **These are assets,
  not code**, and are the fourth and last channel by which a vertical enters the platform
  (`00_CHARTER` §8).

---

# M11 · Observation Builder

### Purpose

Assemble complete, explainable, ceiling-compliant `Observation` objects — **the single choke point
through which every published fact must pass.**

> **Single responsibility:** *Turn internal signals into published facts, and refuse anything that is
> not one.*

### Responsibilities

1. Assemble the observation envelope (`02_VOM` §11) from detection, tracking, registry, and
   understanding signals.
2. **Enforce the Attribute Schema Registry** — the third and final ceiling gate (`00_CHARTER` §4.3).
3. **Enforce envelope completeness** — no observation without provenance, timing, and evidence (V4).
4. Attach and persist evidence; apply retention classification.
5. Project spatial information into ground/site frames using pinned calibration, computing uncertainty.
6. Apply confidence calibration profiles.
7. Set `measurement_basis` honestly (`measured` vs `predicted` vs `interpolated`) (V8).
8. Compute lineage and `supersedes` relationships.
9. Emit `coverage` observations when the platform's observability changes.
10. Apply **change suppression**: do not publish an observation identical to the last one — publish on
    change, on demand, or on a heartbeat cadence.

### Public API

```text
build_presence(object, detection, frame)   → Observation !ValidationFailed
build_spatial(object, frame)               → Observation?      # null if unchanged
build_attribute(object, understanding_result) → Observation[] !ValidationFailed
build_identity(assertion)                  → Observation
build_lifecycle(object, transition)        → Observation
build_coverage(scope, reason, window)      → Observation
validate(observation)                      → Valid | Violations[]
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| Detections (M5), tracks (M6), objects (M7) | `Observation[]` — the platform's only product |
| Understanding results (M9) | `Evidence` records |
| Calibration (M1) | Validation violation events |
| Attribute Schema Registry + Taxonomy | Suppression statistics |
| Confidence calibration profiles (Model Manager) | |

### Dependencies

Camera Manager (M1), Attribute Schema Registry, Taxonomy, Model Manager (calibration profiles), Storage
(evidence), Metrics, Event Bus, Clock.

### State Ownership

**Owns:** last-published signature per (object, observation type) for change suppression; sequence
state for lineage. Small, ephemeral, per-camera.

Owns **no** observations — it builds them and hands them to M12. This separation matters: the builder
must be a pure, heavily-testable function of its inputs, and giving it durable state would compromise
that.

### Thread Safety

Per-camera single-writer, matching upstream partitioning. Building is otherwise a pure function of
inputs plus registries (immutable snapshots), so it parallelizes across cameras with no shared mutable
state.

### Failure Handling

| Failure | Response |
|---|---|
| Attribute key not in registry | **Drop the attribute**, keep the rest of the observation, count, alarm on sustained rate |
| Envelope incomplete (missing provenance) | **Reject the observation entirely** and alarm. An unexplainable observation is worse than no observation — it is a fact nobody can audit (V4) |
| Calibration unavailable | Emit with normalized coordinates only; omit ground fields. Degrade the content, never the observation (V9) |
| Evidence store write fails | Emit the observation with `evidence_ref` marked `pending`; retry asynchronously; if permanently failed, mark `evidence_unavailable` — **honest rather than silent** |
| Clock quality `UNKNOWN` | Emit with maximal `t_capture_unc`; consumers decide whether it is usable (V11) |
| Suppression state lost (restart) | Publish a full snapshot for active objects; brief duplication is harmless, missing data is not |
| Taxonomy version mismatch between producers | Reject with a clear diagnostic; this indicates a partial deployment and must be loud |

### Performance

- On the hot path for **every** published fact; must be allocation-light.
- **Change suppression is the main performance feature**, and it is a correctness feature too: without
  it, a stationary object publishes an identical observation at full frame rate forever, which floods
  storage, subscribers, and consumers with no information. Typical reduction is 10–50×.
- Heartbeat cadence guarantees liveness: a consumer must be able to distinguish "unchanged" from
  "stopped observing," so unchanged objects still publish at a slow floor rate (V8).
- Evidence writes are asynchronous and batched; they never block observation publication.

### Extension Points

- **Suppression policies** (port): exact-match, threshold-based (position moved >X), semantic (only on
  meaningful change), always-publish for forensic modes.
- **Enrichment stages** (port): additional derived spatial computations (speed, heading stability,
  inter-object distance) — all pure geometry, all ceiling-compliant.
- **Evidence retention policies** (port): none, sampled, full, per-attribute, per-privacy-class.
- **Observation sinks** (port): in addition to state, an observation may be teed to a message bus, a
  data lake, or a future learning pipeline. This is the designed hook by which a training loop is added
  later without touching the platform.

---

# M12 · Vision State Manager

### Purpose

Own the **Vision State** — the authoritative, continuously-maintained projection of the current visual
world — and the immutable observation log it is derived from.

> **Single responsibility:** *Be the single writer of visual truth, and never interpret it.*

Detailed design is in `07_STATE_ARCHITECTURE.md`; this section specifies the module.

### Responsibilities

1. Append observations to the **immutable log** (V5) — the system of record.
2. Project the log into the **Vision State** materialized view (V6).
3. Serve immutable, consistent **snapshots** to readers.
4. Maintain bounded **history** per object for perception continuity.
5. Maintain the **coverage map**: which cameras and regions are currently observable (V8).
6. Enforce retention and erasure over log and state.
7. Support rebuild of state from the log (the recovery and reprocessing path).
8. Notify subscribers of state deltas.

### Public API

```text
append(observations)                → CommitResult !CommitFailed
snapshot(scope)                     → StateSnapshot          # immutable, consistent
object_state(object_id)             → ObjectState !NotFound
history(object_id, window)          → Observation[]
coverage(scope, at?)                → CoverageMap
subscribe(filter)                   ⇢ StateDelta
rebuild(scope, from_log_position)   → RebuildHandle
retention_sweep(policy)             → SweepReport
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| `Observation[]` from M11 | Commit acknowledgements |
| Coverage signals (M2 stream events, M3 drop alarms, M8 budget alarms) | Immutable state snapshots |
| Retention policy | State deltas to subscribers |
| Rebuild requests | Coverage maps |

### Dependencies

Storage Interfaces (M13), Event Bus, Metrics, Configuration, Clock. **No dependency on any perception
module** — it consumes observations and knows nothing of how they were made, which is what allows the
entire perception stack to be replaced beneath it.

### State Ownership

**Owns everything durable and semantic in the platform:** the observation log, the state projection,
history rings, coverage state, retention bookkeeping.

**Partitioned by camera; aggregated by site.** Each partition has exactly one writer (V6). Business
systems have **no write path at all** — this is enforced structurally, because the write API is not
exposed through the Observation API (M14) in any form.

### Thread Safety

- **Single writer per partition**, serialized through a partition actor.
- **Readers never block writers and never block each other**: snapshots are immutable structures with
  copy-on-write updates, so a reader holds a consistent view for as long as it needs without preventing
  progress.
- Cross-partition reads assemble a **snapshot set** with per-partition versions, and the API reports the
  resulting consistency level honestly rather than pretending to a global instant that does not exist in
  a distributed deployment.
- Log append is sequential per partition, batched, and fsync-policy-driven.

### Failure Handling

| Failure | Response |
|---|---|
| Storage unavailable (log append fails) | Buffer in a bounded local queue; if the queue fills, **stop accepting observations and mark the partition degraded** rather than dropping facts silently. Losing observations invisibly is a V8 violation of the worst kind |
| Projection error on an observation | Quarantine that observation, continue the projection, alarm. One bad record must not stop the world |
| State/log divergence detected | Rebuild the partition from the log; the log is authoritative, always |
| Partition writer dies | Restart, replay from the last committed log position; idempotent by `observation_id` |
| Retention sweep fails | Retry; alarm; never delete without confirming what was deleted |
| Rebuild requested during live operation | Rebuild into a shadow projection, then atomically swap |
| Clock skew across partitions | Coverage and cross-partition queries report per-partition times and uncertainty; no global instant is fabricated |

### Performance

- **Append path** is sequential and batched — the cheapest possible durable write pattern.
- **Projection** is incremental: an observation touches one object's state.
- **Snapshots** use structural sharing, so a snapshot is O(1) to take rather than a copy.
- **History is bounded** by count and by time. Unbounded history is the classic long-run failure of
  stateful vision systems; bounding it is structural here.
- **Write volume**: at 100 cameras with change suppression, roughly 500–2000 observations/second at
  ~2 KB each ≈ 1–4 MB/s. Ordinary for a log-structured store, and the reason V12 (pixels stay local)
  matters so much — the alternative is three orders of magnitude more.

### Extension Points

- **State store adapters** (port): in-memory (single camera), embedded key-value (edge), distributed
  database (cluster).
- **Log adapters** (port): local append-only file, Kafka/Redpanda, cloud streaming log.
- **Projection strategies** (port): current-only (minimal memory), current + bounded history, full
  temporal index.
- **Federated state**: multi-site query without central consolidation — the API contract already
  reports per-partition consistency, so federation adds no new semantics.

---

# M13 · Storage Interfaces

### Purpose

Define the **durability contracts** the platform depends on, so that a single-node edge box and a
cloud cluster differ only in adapter selection.

> **Single responsibility:** *Describe what must persist and with what guarantees; implement none of it.*

### Responsibilities

Define, and only define, five distinct storage contracts. Conflating them is the reason storage becomes
un-portable.

| Contract | Holds | Access pattern | Durability | Typical adapters |
|---|---|---|---|---|
| **ObservationLog** | Immutable observations | Append-heavy, sequential read, range scan | Highest — system of record | Append-only file, Kafka, cloud log |
| **StateStore** | Current projection | Random read/write, snapshot | High, rebuildable from log | Memory, embedded KV, distributed DB |
| **EvidenceStore** | Crops, raw model output | Write-once, rare read, TTL, content-addressed | Medium, policy-driven | Local disk, S3-compatible, encrypted volume |
| **ConfigStore** | Config, calibration, taxonomy, registry | Read-heavy, versioned, audited | High | Git, config service, database |
| **ArtifactStore** | Model weights, prompt packs | Read-once at load, content-verified | High, immutable | Object storage, registry, local cache |

### Public API

```text
ObservationLog:
  append(partition, observations)     → LogPosition !AppendFailed
  read(partition, from, to)           ⇢ Observation
  tail(partition, from)               ⇢ Observation        # live follow
  truncate(partition, before)         → void               # retention only
  position(partition)                 → LogPosition

StateStore:
  put(key, value, version)            → Version !ConflictError
  get(key)                            → (value, Version)?
  scan(prefix, limit, cursor)         → Page
  snapshot(scope)                     → SnapshotHandle
  delete(key, version)                → void

EvidenceStore:
  put(content_hash, bytes, retention, privacy_class) → BlobRef
  get(blob_ref)                       → bytes !NotFound !Expired
  exists(content_hash)                → bool               # dedup check
  expire(before | policy)             → ExpireReport
  erase(subject_scope)                → EraseReport        # right-to-erasure

ConfigStore:  get/put/history/watch (versioned, audited)
ArtifactStore: fetch(artifact_id, expected_hash) → LocalPath !IntegrityFailure
```

### State Ownership

Owns **no state** — it is a set of contracts. Adapters own their own storage.

### Thread Safety

All contracts are specified as **safe for concurrent use**. `StateStore.put` is optimistically
concurrent with explicit version conflicts rather than locks, so that a distributed adapter is possible
without changing the contract.

### Failure Handling

Contracts define failure explicitly rather than leaving it to adapters:

- Every operation may fail; failure is a **typed result**, never a silent partial success.
- `append` is **idempotent by `observation_id`**, so retry after an uncertain outcome is always safe —
  which is what makes at-least-once delivery workable end to end.
- `EvidenceStore.get` distinguishes `NotFound` (never existed — a bug) from `Expired` (retention did
  its job — normal). Collapsing these two is how retention behaviour becomes indistinguishable from
  data loss.
- `ArtifactStore.fetch` **verifies content hash** and fails closed. Loading unverified weights is a
  supply-chain vulnerability (`12_SECURITY_AND_PRIVACY.md`).

### Performance

- **ObservationLog**: batched appends, group commit, configurable fsync (per-batch on edge,
  per-replication in cluster).
- **EvidenceStore**: content-addressed with deduplication; written asynchronously off the hot path.
- **ArtifactStore**: local cache keyed by hash — a model is downloaded once per node, ever.
- **StateStore**: hot working set in memory with durability behind it; the store is never on the
  read path for live queries.

### Extension Points

Adapters per contract; tiered storage (hot local → warm object store → cold archive); encryption at
rest per privacy class; regional pinning for data residency (`12_SECURITY_AND_PRIVACY.md`).

---

# M14 · Observation API

### Purpose

Expose the platform's product to consumers — **read-only, versioned, scoped, and backpressure-aware** —
and accept the one thing consumers may send inward: demand contracts.

> **Single responsibility:** *Serve facts safely under contract. Produce nothing; accept no writes to
> state.*

Contract detail is in `09_API_CONTRACTS.md`; this section specifies the module.

### Responsibilities

1. Serve **queries** over current state and historical observations.
2. Serve **subscriptions** — filtered, live observation and state-delta streams.
3. Accept, validate, and register **demand contracts** (the only inbound influence).
4. Enforce **authentication, authorization, and tenant scoping** — the only module where external
   identity exists.
5. Negotiate **schema version** per consumer, supporting concurrent major versions during migration.
6. Apply **rate limiting, quotas, and subscriber backpressure**.
7. Publish **capability and coverage** so consumers can distinguish absence from blindness (V8).
8. Emit an **audit trail** of who read what.

**Explicitly not responsible for:** interpreting observations, aggregating for business purposes, or
providing any write path into Vision State.

### Public API

```text
# ---- read ----
query_state(scope, filter, at?)        → StateSnapshotView
query_observations(scope, window, filter, cursor) → Page<Observation>
get_object(object_id, include_history?) → ObjectView !NotFound
get_evidence(evidence_ref)             → EvidenceView !Expired !Forbidden
coverage(scope, window)                → CoverageReport
capabilities(scope)                    → CapabilityReport   # classes & attributes actually producible

# ---- subscribe ----
subscribe(filter, delivery_policy)     ⇢ Observation | StateDelta | Gap

# ---- influence (the ONLY inbound path) ----
register_demand(demand)                → DemandId !Rejected
update_demand(demand_id, demand)       → void
revoke_demand(demand_id)               → void
list_demands(subscriber)               → Demand[]

# ---- explicitly absent ----
# no create_object, no update_state, no set_attribute, no delete_observation (V5, V6)
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| Consumer queries and subscriptions | Observations, state views, coverage, capabilities |
| Demand contracts | Demand acknowledgements or rejections |
| Authentication credentials | Audit records |
| Version negotiation headers | Version-appropriate payloads |

### Dependencies

Vision State Manager (M12), demand registry, Camera Manager (capability reporting), authentication
provider, Metrics, Event Bus, Configuration.

### State Ownership

**Owns:** subscription sessions, cursors, rate-limit buckets, the demand registry, version negotiation
state. Owns no visual state.

The **demand registry is durable** — demands must survive restart, or every consumer would have to
re-register after every deployment and attribute coverage would silently lapse in the interval.

### Thread Safety

Fully concurrent and stateless per request, apart from subscription sessions which are per-connection
actors. All reads go through immutable snapshots from M12, so no locking exists on the read path at
all. This is a direct payoff of the snapshot design in §M12.

### Failure Handling

| Failure | Response |
|---|---|
| **Slow subscriber** | Apply the declared delivery policy: `conflate` (keep latest per object), `drop_with_gap` (skip and **emit an explicit `Gap` marker**), or `disconnect`. **Never buffer without bound; never drop silently.** The `Gap` marker is V8 applied to delivery |
| Query too large | Reject with a bound and a cursor rather than degrading the service for everyone |
| State partition unavailable | Return partial results with **explicit unavailability** for the missing scope, never a silent subset |
| Consumer requests an unsupported schema version | Reject with the supported set; never guess |
| Demand exceeds budget policy | Reject with the reason and a feasible alternative (lower freshness, narrower scope) |
| Demand references unregistered attributes | Reject, naming the attribute and the registration path |
| Auth failure | Deny, audit, rate-limit repeats |
| Cross-tenant access attempt | Deny, audit, alarm. **Tenant scoping is applied at query construction, not as a post-filter** — post-filtering is how leaks happen |
| Backend overload | Shed load by priority; protect subscriptions over ad-hoc queries, because subscriptions are how live consumers stay correct |

### Performance

- Reads are snapshot-based, so heavy query load cannot slow perception. This isolation is the reason
  L6 and L7 are separate layers (`01_LAYERED` §1.2).
- Subscription fan-out is the dominant cost; filters are evaluated **once per observation** against an
  index of subscriber predicates rather than once per subscriber.
- Historical queries are served from the log with time-partitioned indexes and are explicitly permitted
  to be slower than live reads.
- Evidence retrieval is rare, large, and rate-limited separately.

### Extension Points

- **Transport adapters** (port): synchronous request/response, streaming push, message-bus publication,
  webhook delivery, future protocols. **The contract is transport-independent by design** — this is why
  `09_API_CONTRACTS.md` specifies semantics rather than a wire protocol, and why adopting a new
  transport in 2031 will not be a platform change.
- **Query languages** (port): structured filters today; richer spatial-temporal query later.
- **Delivery policies** (port): at-least-once with dedupe, conflated, sampled, batched.
- **Authorization models** (port): role-based, attribute-based, per-camera and per-region scoping.
- **Aggregation is deliberately excluded.** Consumers aggregate. The moment the platform offers "count
  people per hour per zone," it has begun growing an analytics product inside a perception platform
  (`00_CHARTER` §6).

---

## Where to go next

| Question | Document |
|---|---|
| Who provides models, plugins, config, health? | `05_MODULES_PLATFORM_KERNEL.md` |
| What are the exact port contracts? | `06_PORTS_AND_ADAPTERS.md` |
| How is Vision State structured in detail? | `07_STATE_ARCHITECTURE.md` |
| What are the full API semantics? | `09_API_CONTRACTS.md` |
