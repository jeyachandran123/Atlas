# Flow 5 — Constitutional / Architecture Compliance Review

**Performed before any code was written**, as required.

Documents reviewed: `03_MODULES` (M8, the M7→M8 and M8→M9 handoffs), `02_VOM`
(§10.7 Crop, §10.8 QualityGrades, §10.9 Evidence, §9 attributes), `01_LAYERED`
(§2 dependency law, §5 data flow, §8 cross-cutting placement). Secondary:
`06_PORTS`, `07_STATE`, `08_RUNTIME`, `09_API_CONTRACTS`, `10_RELIABILITY`,
`11_PERFORMANCE`, `12_SECURITY`, `14_TESTING`. `00_CHARTER` for constitutional
clarification; `15_ROADMAP` only to confirm nothing future is built.

---

## 1. Why M8 exists

`03_MODULES` §M8 states it in one sentence:

> *This module is why a 100-camera deployment is affordable. Without it,
> understanding cost is `cameras × fps × objects`. With it, cost is
> `demands × changes`, which is smaller by two to three orders of magnitude in
> every realistic deployment.*

M8 is the platform's **attention mechanism** and the primary enforcement point of
invariant V7 (perceptual economy). It has two faces that are one job:

1. **Decide what deserves expensive analysis** — trigger evaluation against
   demand contracts and budget.
2. **Prepare defensible input for it** — extract, normalize, quality-gate and
   content-address a crop.

`11_PERFORMANCE` §1.2 quantifies the stakes: a single VLM call costs roughly as
much as 70 detections. Run understanding per object per frame and it is ~99% of
platform cost and the deployment is unaffordable. Run it only when a demand is
unsatisfied and something changed, and it is ~20% and routine.

> *"That reduction is not an optimization; it is the architecture."*

## 2. What problem M8 solves

Three, each of which is fatal alone:

**Cost.** 100 cameras × 5 objects × 5 fps = 2,500 candidate analyses/second.
Demand filtering, change-based triggering and quality gating reduce that to
**10–15 VLM calls/second** — the difference between "impossible" and "one GPU".

**Defensibility.** An expensive model given 14 blurry pixels produces a confident
answer that is worthless, and nothing downstream can tell. The quality gate
refuses the crop *before* the money is spent, and records why.

**Consistency.** Without one owner of crop preparation, every model gets its own
cropping code, and two models evaluated on differently-padded crops are not
comparable — `02_VOM` §10.7: *"two models evaluated on differently-letterboxed
crops are not comparable, and without this field nobody finds out."*

## 3. What M8 owns

`03_MODULES` §M8 State Ownership:

> **Owns:** per-object trigger state (last analysis time per attribute, last
> appearance signature), budget accounting, crop deduplication cache, priority
> queues.

Plus the seven responsibilities: trigger evaluation, quality gating, crop
extraction, content-addressing and deduplication, budget management,
prioritization, and **recording a skip reason for every candidate not analysed**.

Its state is explicitly **ephemeral and node-local**, *"rebuilt from registry
state after restart, with the conservative consequence that a restart causes one
round of `FIRST_SIGHT` re-analysis. Acceptable and bounded."*

## 4. What M8 absolutely does NOT own

| Not owned | Belongs to | Basis |
| --- | --- | --- |
| Object identity, lifecycle, attributes-as-truth | M7 | `01_LAYERED` §8 — one module mints identity |
| Detection, tracking | M5, M6 | M8 consumes *objects*, never detections |
| Understanding, captioning, OCR, VLM inference | M9 | L3 vs L4; §5 below |
| Observation assembly, schema and ceiling enforcement | M11 | `01_LAYERED` §8 — one choke point |
| Vision State | M13 | Projected from the log, not written by M8 |
| Frame pixels | M4 | M8 **borrows** via lease/pin; it never owns or copies the ring |
| Evidence persistence | M12 Storage Interfaces | M8 sets `retention`; the store honours it |
| Why a priority class exists | The consumer | V1 — the class is opaque |

## 5. Why M7 cannot own Crop Management

Four reasons, each sufficient:

1. **Layer.** M7 is L2 Perception (*what exists and which is the same thing*).
   M8 is L3 Attention (*what deserves closer analysis*). `01_LAYERED` §1.2 names
   L2/L3 fusion as a boundary systems collapse "always with the same
   consequences": *"Systems that fuse these end up invoking heavy models from
   inside the tracker, which makes cost proportional to frame rate and makes both
   components untestable."*

2. **Cost shape.** M7 runs on every frame for every object (~0.1 ms). M8 runs
   only when a trigger fires (~2 ms/crop, triggered only). Putting crop
   extraction inside M7 makes cost proportional to frame rate, which is exactly
   what M8 exists to prevent.

3. **State lifetime.** M7's state is **durable** — it must survive restart. M8's
   is **ephemeral and node-local** and is deliberately rebuilt. One module cannot
   own both a state that must survive and one that is designed to be discarded.

4. **Pixels.** M7 never touches a frame (V12 at its layer). M8 must borrow pixels
   through the buffer's lease. Giving M7 pixel access would dissolve a boundary
   Flow 4 was built to hold.

## 6. Why Understanding cannot own Crop Management

1. **Budget is a platform concern, not a model concern.** The budget spans models
   and cameras; a model that decided when to run itself could not be swapped
   without re-implementing the platform's cost control.

2. **Standardization.** If each understander crops for itself, "the same crop"
   stops existing. A/B comparison, replay and caching all break — and
   `02_VOM` §10.7 requires the applied transform be *recorded* precisely so
   comparisons stay fair.

3. **The gate must precede the spend.** Quality gating is only valuable *before*
   the expensive call. Inside M9 it would be an expensive way to discover the
   call was pointless.

4. **Deduplication.** `CropId` is a content hash, so identical pixels resolve
   from cache once — but only if one component owns the hashing.

## 7. Why crop generation must be centralized

The brief calls M8 the **sole owner of visual evidence preparation**, and the
architecture supports it in three independent places:

- `02_VOM` §10.7: `CropId` is a **content hash of the normalized crop pixels** —
  *"The same pixels cropped twice must be one crop. Content addressing gives free
  deduplication, free cache keys, free integrity checking, and a stable evidence
  reference that survives storage migration."* Two croppers produce two hashes for
  one truth.
- `02_VOM` §10.7 notes: recording `transform` *"is what makes a crop reproducible
  and a model comparison fair."*
- `12_SECURITY` §3: crops are **C1 · Imagery** with their own retention and
  access rules. A second, uncoordinated producer of imagery is an
  unclassified-data path.

## 8. Where M8 begins and ends

**Begins:** on candidate objects from M7 (`01_LAYERED` §5.1:
`REG->>CRP: candidate objects`; §5.2 sizes the edge at ~1 KB, **control** plane).

**Ends:** when a `Crop` is produced or a skip is recorded. Specifically at:

- `CropRequest[] | Skipped[(object_id, reason)]` from `evaluate`
- `Crop` from `extract`
- budget telemetry and `BudgetExhausted` / `GateRejectionSpike` events

It does **not** extend to invoking a model (M9), assembling an observation (M11),
or persisting evidence (M12 honours the `retention` M8 sets).

## 9. Who feeds M8, who consumes M8

| Direction | Module | Payload | Status |
| --- | --- | --- | --- |
| **Feeds** | M7 Object Registry | Candidate objects, attribute state, staleness | ✅ Flow 4 |
| **Feeds** | M4 Frame Buffer | Frame pixels via lease/pin | ✅ Flow 1 (`acquire`, `pin`, `unpin` exist) |
| **Feeds** | Demand registry | Demand contracts | Registered through M8's own API; M14 forwards in Flow 8 |
| **Feeds** | M1 Camera Manager | Regions (for `on_region_entry` hints) | ✅ Flow 1 |
| **Consumes** | M9 Understanding Engine | `Crop` + requested attribute set | ⏳ Flow 6 |
| **Consumes** | M11 Observation Builder | `TriggerReason` for evidence | ⏳ Flow 7 |

## 10. Invariants constraining M8

| | Invariant | Binding on M8 |
| --- | --- | --- |
| **V1** | Semantic Ceiling | *"A trigger policy may say 're-look because appearance changed by 0.4 cosine distance.' It may never say 're-look because this is the kitchen.' Priority is expressed as an **opaque class** supplied by configuration."* |
| **V2** | Vertical neutrality | Region ids and priority classes are opaque strings. |
| **V4** | Explainability | Every crop records the transform actually applied, its quality grades, and its gate result with a reason. |
| **V5** | Immutability | `Crop` is a frozen value; `CropId` is a content hash, so a modified crop is a different crop by construction. |
| **V7** | Perceptual economy | The reason the module exists. Demand-driven, change-triggered, quality-gated, deduplicated, budget-capped. |
| **V8** | Blindness explicit | **Every skip carries an attributed reason.** A consumer must distinguish "no attribute because nothing was there" from "no attribute because we could not afford to look". |
| **V11** | Normalized time | Freshness and staleness are computed from capture time. |
| **V12** | Pixels stay local | Crops are data-plane. The crop *reference* travels; the pixels do not leave the node. |
| **V13** | Deterministic replay | Extraction is *"a pure function of (frame, box, transform)"*. Same inputs, same `CropId`. |

## 11. Implementation shortcuts that must be rejected

| Shortcut | Why it is wrong |
| --- | --- |
| Skip silently when nothing triggers | V8 and responsibility 7. **Every** candidate not analysed gets an attributed `SkipReason`. |
| Crop without recording the transform | `02_VOM` §10.7 — without it, two models are not comparable and nobody finds out. |
| Let a downstream model re-crop | Destroys `CropId` as a cache key, breaks replay, and creates a second imagery path. |
| Emit a crop larger than the model input | §M8 Performance: *"never larger, which is pure waste."* |
| Invent quality heuristics | The brief and `02_VOM` §10.8 fix the grade set. Only what is specified. |
| Send a hopeless crop to an expensive model | §M8: *"Never send a hopeless crop to an expensive model."* Gate first, retry on `QUALITY_IMPROVED`. |
| Treat a budget exhaustion as silence | §M8: emit `BudgetExhausted` **and publish coverage observations** so consumers know attributes are thinned. |
| Let a demand encode a business reason | `09_API_CONTRACTS` §4.2 — priority is a label, never a justification. |
| Unbounded dedup cache | §M8: bounded LRU. |
| Cache keys without tenancy | `12_SECURITY` §4: *"Every cache key includes `tenant_id` — including crop and understanding caches."* |
| Fabricate a crop when the frame is gone | Skip with `FRAME_UNAVAILABLE` and count. Unknown beats fabricated. |
| Model-specific preprocessing in M8 | Belongs to the M9 adapter. M8 produces canonical evidence only. |

---

## 12. Ambiguities found — three, all resolved without inference

### 12.1 `QualityGrades` lacks `overall`

`02_VOM` §10.8 specifies seven grades including
`overall: excellent | good | marginal | insufficient`. The type built in Flow 2
has six — `overall` is absent, because detection cannot compute it.

§10.8 also says: *"Quality is computed once, **in the Crop Manager**, and travels
with everything derived from it."* Flow 2's docstring says the remaining grades
"belong to Flow 4", which was wrong — they belong to **M8**.

**Resolution:** add `overall` as an optional field defaulting to `None`, and
correct the docstring. This is **additive** — no existing construction changes,
and detection continues to leave it unset because it genuinely cannot measure it.
Recorded as a Flow 2 public-contract change in the report.

### 12.2 "Never introduce cross-camera synchronization" vs a shared budget

The brief says *"Respect camera partitioning. Never introduce cross-camera
synchronization."* The architecture says the opposite about one thing:

> *"Per-camera single-writer for trigger state, matching M7's partitioning. The
> **budget is shared across cameras** and uses atomic counters with periodic
> reconciliation — the same trade as M3, and for the same reason."*

**This is not a conflict once read precisely.** A budget that were per-camera
would not be a budget: understanding cost is a property of the *node's* GPU, not
of any camera, and a per-camera cap cannot prevent 100 cameras each staying under
their own limit while collectively exhausting the device.

**Resolution:** trigger state is strictly per-camera single-writer, as the brief
requires. The budget is a shared **counter** — lock-free accounting with a short
critical section, exactly as M3's global FPS budget already does — not
cross-camera *coordination*, and no camera ever waits on another. The
Constitution mandates the shared budget; the brief's constraint is honoured in
the sense that matters, which is that no camera blocks on another's progress.

### 12.3 The demand registry is listed both as a dependency and as M8's API

§M8 Dependencies lists "demand registry" alongside M8; §M8 Public API includes
`register_demand` / `revoke_demand`; `09_API_CONTRACTS` §4.1 assigns
`register_demand` to the Observation API (M14, Flow 8).

**Resolution:** M8 **owns** the demand registry and exposes registration; M14 will
*forward* to it in Flow 8. That is the only reading in which all three statements
hold, and it matches the pattern of every earlier flow — the module owns its
state and a later flow exposes it.

---

## 13. Scope confirmation against `15_ROADMAP`

Confirmed **not** implemented and structurally prevented:

| Capability | Phase | Why it stays out |
| --- | --- | --- |
| Temporal / action understanding | Phase 3 | `UnderstanderPort` already accepts crop *sequences*; the temporal `CropStrategy` is an extension point, not a shipped strategy |
| Learned salience triggers | Extension | `TriggerPolicyPort` ships a **default** policy; learned policies plug in |
| Learned quality predictors | Extension | `QualityEstimatorPort` ships heuristics, as §M8 specifies |
| Cross-camera identity | Phase 2 | P11 remains unbindable |
| Learning pipeline | Phase 4 | M8 retains evidence; it trains nothing |

Unlike P11, the roadmap does **not** defer P12/P13/P14 — §M8 describes the
trigger set as *"a default policy, fully replaceable"* and the quality estimator
as *"heuristic sharpness/scale today"*. So all three ports ship with default
adapters and become bindable.

---

## 14. Compliance conclusion

The architecture specifies M8 completely enough to implement without inference.
Three ambiguities were found and each resolved by closer reading rather than
invention; one of them (§12.2) is an apparent conflict between the brief and the
Constitution, resolved in the Constitution's favour with the brief's intent
preserved.

**No architectural change is requested. Implementation may proceed.**
