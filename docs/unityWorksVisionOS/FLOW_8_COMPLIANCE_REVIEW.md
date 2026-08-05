# Flow 8 — Architecture Compliance Review

**Modules:** M13 Storage Interfaces (L6), M14 Observation API (L7)
**Status:** Completed **before** any implementation, as the brief requires
**Scope of review:** the approved architecture only. Nothing below is inferred.

---

## 1. Why M13 exists

> §M13 Purpose: *"Define the **durability contracts** the platform depends on, so that a
> single-node edge box and a cloud cluster differ only in adapter selection."*

M13 exists so that the question *"where does this live?"* has exactly one answer per
kind of data, and that answer is a **contract**, not a technology. §M13's
responsibility section says the five contracts must stay distinct because
*"conflating them is the reason storage becomes un-portable."*

The five are distinct along axes that genuinely differ:

| Contract | Access pattern | Durability | Why it cannot share an adapter with the others |
|---|---|---|---|
| ObservationLog | append-heavy, sequential, range scan | **highest — system of record** | Append-only; never random-write |
| StateStore | random read/write, snapshot | high, **rebuildable from log** | Mutable by definition; the log is not |
| EvidenceStore | write-once, rare read, TTL, content-addressed | medium, policy-driven | Large binary payloads on a privacy clock |
| ConfigStore | read-heavy, versioned, audited | high | Needs history and watch; the others do not |
| ArtifactStore | read-once at load, content-verified | high, immutable | Fails closed on hash mismatch |

A platform that stored observations and evidence in one place would be forced to
give imagery the log's 7-day-to-years retention, when §8.1 makes evidence *"the
shortest tier by design"* precisely because it is the only tier containing pixels.

## 2. Why M14 exists

> §M14 Purpose: *"Expose the platform's product to consumers — read-only, versioned,
> scoped, and backpressure-aware — and accept the one thing consumers may send
> inward: demand contracts."*

M14 exists because `01_LAYERED` §1.2 names L6/L7 as one of three boundaries other
systems collapse, always with the same consequence:

> *"Systems that serve state directly from their working structures cannot change
> those structures, cannot version their API, and cannot enforce tenant scoping.
> The split lets internal representation evolve while the contract holds."*

Three capabilities exist only because the split exists: the internal projection can
be rebuilt into a new shape (§9.2) without a consumer noticing; two adjacent major
API versions can be served concurrently (§7.1); and tenant scoping has exactly one
place to live. `12_SECURITY` §5.1 makes the last one explicit: *"External identity
exists **only** at the Observation API... There is no ambient user context inside
the pipeline, which means no pipeline component can accidentally make an
authorization decision."*

## 3. Why persistence is separated from Vision State

Vision State is a **projection**; persistence is a **contract about durability**.
Merging them would make the projection's shape a storage schema, and 07_STATE §9.2
depends on the opposite:

> *"Over ten years, the state structure in §3 will be revised repeatedly; each
> revision is a rebuild rather than a migration, and no historical fidelity is lost
> in the process."*

A revision is only a rebuild if state owes nothing to a stored representation of
itself. §M13's StateStore row states the relationship exactly: durability *"High,
**rebuildable from log**"*, and *"the store is never on the read path for live
queries."*

## 4. Why the Observation Log remains the system of record

07_STATE §2 makes the log the primary artefact and state the derivative. §9.1's
recovery table is where that choice pays:

| Scenario | Recovery | Data loss |
|---|---|---|
| State store corruption | **Rebuild from log — the log is authoritative** | None |
| Projection bug | Fix, rebuild into shadow, atomic swap | **None — "this is the strongest argument for event sourcing here"** |
| Schema change | Rebuild under new projection code | None |

Every row that reports *no data loss* reports it **because** the log is
authoritative. If state were the record, a projection bug would be permanent
corruption rather than a redeployment.

§9.1 also names the one case that is not recoverable — total log loss — and calls
it *"a critical incident"*, adding that *"log replication is mandatory in any
deployment claiming durability."* The architecture is explicit that this is the
single point whose loss is unrecoverable, which is itself an argument for keeping
the record in exactly one well-defined place.

## 5. Why Vision State remains a projection

07_STATE §1.1's three properties: derived, bounded, current. A projection can be
thrown away. That is not a weakness — it is the property that makes §9.1's table
possible and §9.2's schema evolution routine.

If state were primary, it would need its own migration story, its own backup story,
and its own corruption story. As a projection it needs none: it has one recovery
procedure, `rebuild`, and that procedure is also the schema-migration procedure and
also the bug-fix procedure.

## 6. Why the Observation API is read-only

> `09_API` §1.1: *"~~Mutate~~ — **Does not exist** (V6). There is no endpoint, no
> field, no admin override."*

V6 is single-writer state. 07_STATE §1.2 explains why business systems cannot write
at all: a platform that accepted external writes could no longer say where any fact
came from, and V4 explainability would become unenforceable — a state value would
have a provenance chain that terminates in *"a consumer said so."*

§M14's Public API makes the absence structural rather than a matter of
authorization: `# no create_object, no update_state, no set_attribute, no
delete_observation (V5, V6)`. There is no privileged path, because there is no path.

## 7. Why Exposure cannot modify state

Because `01_LAYERED` §2's dependency law permits only downward calls, and a write
would be L7 reaching into L6's ownership. §M14 states it directly: *"Produce
nothing; accept no writes to state."*

The single apparent exception proves the rule. `01_LAYERED` §3.1:

> *"**`Observation API → Crop Manager`** is the only 'backward-looking' edge, and it
> is not a call: the API accepts demand contracts, which the Configuration/demand
> registry publishes as an event that the Crop Manager's trigger policy reads."*

§3.2 explains why this does not form a cycle: the path is *"asynchronous and
declarative — the API writes a demand record; the Crop Manager reads demand state at
trigger time. **No call ever returns through the pipeline it entered.**"*

A demand influences *what the platform spends money computing*. It never modifies a
fact, an object, a track, or a projection.

## 8. Why replay must reproduce identical state

Because V13 is what makes the log worth its cost. If replay produced a *similar*
world rather than an *identical* one, then:

* §9.1's *"rebuild from log — no data loss"* would be false;
* §9.2's shadow-rebuild-and-swap would silently change what consumers see;
* an audit answering *"what did the system report at 09:14 and why"* would answer
  with a reconstruction nobody could vouch for.

Determinism is therefore a property of the **projection function**, not of the
storage: `project` must be a pure function of `(partition, observation)`.

## 9. Why storage adapters remain replaceable

§M13's purpose sentence is the whole argument: an edge box and a cloud cluster
*"differ only in adapter selection."* Obligation A7 — *"pass the conformance kit"* —
is what makes that claim checkable rather than aspirational, and `06_PORTS` §3 calls
it *"the gate that makes all of the above enforceable."*

For P20 specifically, one obligation carries disproportionate weight: §M13 requires
`append` be *"**idempotent by `observation_id`**, so retry after an uncertain outcome
is always safe — which is what makes at-least-once delivery workable end to end."*
An adapter that failed this would corrupt the record on every recovery — at exactly
the moment recovery is supposed to help.

## 10. Why API contracts must remain stable

`09_API` §7.3 sets a nine-month deprecation timeline and explains it:

> *"consumers of a perception platform include long-lived operational systems on
> annual release cycles, and a shorter window would force either rushed migrations
> or permanent version sprawl."*

§9's consumer obligations are the other half of the bargain. C1 (*ignore unknown
fields*) and C2 (*tolerate unknown enum values*) are what make additive evolution
possible: *"A consumer that rejects unknown fields makes every minor version a
breaking change."*

Stability is therefore a two-party contract, and the compatibility matrix in §7.2 is
its schedule.

## 11. Why replay correctness matters more than storage implementation

Because storage is replaceable and replay is not.

A wrong storage adapter is a deployment problem: swap it, rebuild from the log,
carry on. A wrong *replay* silently produces a different world from the recorded
one — and there is nothing left to compare it against, because the projection was
the only other copy. §9.1 places the entire recovery model on replay's correctness;
every "no data loss" row is a promise replay must keep.

Put concretely: the platform can survive losing its storage adapter. It cannot
survive a replay that is subtly wrong, because nothing would ever detect it.

## 12. Where M13 begins

At the **contract boundary below Vision State**. M13 begins the moment data must
outlive the process. Its inputs are what M12 hands it: observations to append,
positions to report, projections to store, evidence to retain.

## 13. Where M13 ends

At the adapter. §M13 State Ownership: *"Owns **no state** — it is a set of
contracts. Adapters own their own storage."* M13 ends before any byte is written; it
never chooses a file format, a database, or a replication strategy.

Its single responsibility — *"describe what must persist and with what guarantees;
**implement none of it**"* — is the boundary stated as a prohibition.

## 14. Where M14 begins

At the **process edge**. §M14 responsibility 4: it is *"the only module where
external identity exists."* M14 begins where an authenticated, tenant-scoped
external request arrives.

## 15. Where M14 ends

At the immutable snapshot it read from M12. §M14 Thread Safety: *"All reads go
through immutable snapshots from M12, so no locking exists on the read path at
all."*

M14 ends before interpretation. §M14: *"Explicitly not responsible for: interpreting
observations, aggregating for business purposes, or providing any write path into
Vision State."* §M14's Extension Points is blunter: *"**Aggregation is deliberately
excluded.** Consumers aggregate. The moment the platform offers 'count people per
hour per zone,' it has begun growing an analytics product inside a perception
platform."*

## 16. Which previous modules feed M13

| Module | What it hands M13 | Contract |
|---|---|---|
| **M12 Vision State** | observations to append; positions to read | ObservationLog (P20) |
| **M12 Vision State** | the projection, optionally | StateStore (P21) |
| **M7 Object Registry** | the durable object population (07_STATE §9.3) | StateStore (P21), narrow use |
| **M9 Understanding** | raw model output; crop references | EvidenceStore (P22) |
| **M8 Crop Manager** | retention and privacy class stamped on the crop | EvidenceStore (P22) |
| **M16 Configuration** | config, calibration, taxonomy, **registry** | ConfigStore (P23) |
| **M18 Model Manager** | model weights, prompt packs | ArtifactStore (P25) |

M13 itself feeds nothing upward. It is a set of contracts other modules depend on.

## 17. Which previous modules feed M14

§M14 Dependencies: *"Vision State Manager (M12), demand registry, Camera Manager
(capability reporting), authentication provider, Metrics, Event Bus,
Configuration."*

| Module | What M14 reads | Never |
|---|---|---|
| **M12 Vision State** | snapshots, object state, history, coverage, deltas | writes anything |
| **M13 EvidenceStore** | evidence payloads, on authorized request | writes evidence |
| **Demand registry** | demand state for `list_demands` | calls M8 |
| **M1 Camera Manager** | capability and coverage reporting | changes a camera |
| **M21 Metrics / M19 Event Bus** | health, capability changes to notify subscribers | — |

Note what is **absent**: M5, M6, M7, M8, M9, M11. M14 never touches perception.
Everything it serves arrives through M12, which is the entire point of the L6/L7
split.

## 18. Which constitutional invariants constrain M13 and M14

| Invariant | Constrains | How it binds Flow 8 |
|---|---|---|
| **V1 Semantic Ceiling** | M14 | The API serves facts. `09_API` §4.2: a demand may carry *which* attributes, never *why*. No aggregation, no thresholds, no conclusions. |
| **V2 Vertical Neutrality** | M14 | The same API serves a kitchen and an operating theatre. No endpoint may name a vertical. |
| **V3 Ports over implementations** | M13, M14 | P20–P22 for storage; P31, P32 for authz and transport. Every one gated by a conformance kit. |
| **V4 Explainability** | M13, M14 | `get_evidence` is what makes V4 *"usable rather than theoretical"* (§6). EvidenceStore must distinguish `Expired` from `NotFound`. |
| **V5 Immutability** | M13 | The log is append-only. §8.2's erasure is *tombstoning, not rewriting*: *"Rewriting history to pretend an observation never existed would destroy the property that makes the log trustworthy."* |
| **V6 Single-writer state** | M14 | No mutate contract exists. |
| **V7 Perceptual economy** | M14 | Demands carry budgets; `effective_freshness` reports what the platform can actually sustain. |
| **V8 Blindness explicit** | M14 | `coverage` is returned on **every** state query, *"unconditionally"*. The `Gap` message is *"V8 applied to delivery"*. |
| **V9 Degrade never die** | M13, M14 | Partial results are explicit; a storage failure is a typed result, never a silent partial success. |
| **V10 Layered identity** | M14 | The API serves object identity; it never creates or resolves one. |
| **V11 Normalized time/space** | M14 | Historical queries are against `t_capture`, *"not ingest time"*, and each result carries `t_capture_unc`. |
| **V12 Pixels stay local** | M13, M14 | Evidence is fetched by reference, rate-limited separately, and authorized separately. |
| **V13 Deterministic replay** | M13 | Replay must reconstruct identical state. This is the invariant Flow 8 must prove, not merely respect. |

## 19. Which implementation shortcuts must be rejected

Each of these is a plausible, defensible-sounding choice that the architecture
forbids.

| Shortcut | Why it is tempting | Why it is rejected |
|---|---|---|
| **Post-filter by tenant** | One query path, filter at the end | `12_SECURITY` §4.2: *"Constructing the query already scoped means there is no moment at which cross-tenant data exists in memory to leak."* Post-filtering *"is how leaks happen."* |
| **Make `coverage` optional on query_state** | Smaller payloads, faster responses | `09_API` §2.1: *"Making it optional would guarantee that most consumers omit it, and the ones who omit it are exactly the ones who will misread the result."* |
| **Buffer a slow subscriber** | Nobody loses a message | §3.4: *"Never: unbounded buffering. Never: silent drop. Never: stall the platform."* Apply the declared policy and emit a `Gap`. |
| **Drop messages silently under pressure** | Simplest overflow handling | The `Gap` message exists so *"a subscriber is never silently skipped."* |
| **Add a small aggregation endpoint** | Every consumer wants counts | §M14: *"The moment the platform offers 'count people per hour per zone,' it has begun growing an analytics product inside a perception platform."* |
| **Serve state directly from M12's structures** | One fewer layer | `01_LAYERED` §1.2: doing so means you *"cannot change those structures, cannot version [the] API, and cannot enforce tenant scoping."* |
| **Infer retryability from a status code** | Fewer fields | §8: *"Consumers must never infer retryability from a status code or a message string. Inferring it is how retry storms begin."* `retryable` is explicit. |
| **Return a quietly smaller result when a partition is down** | Simpler than partial-result plumbing | §8: *"never a quietly smaller result set (V8)."* |
| **Collapse `Expired` and `NotFound`** | Both mean "no bytes" | §M13: *"Collapsing these two is how retention behaviour becomes indistinguishable from data loss."* |
| **Skip hash verification when fetching an artifact** | Faster boot | §M13: *"Loading unverified weights is a supply-chain vulnerability."* Fails closed. |
| **Rewrite the log to satisfy an erasure request** | Genuinely satisfies the regulation | §8.2: tombstone, never rewrite. *"The audit trail survives; the content does not."* |
| **Give replay a fast path that skips the projection** | Rebuild would be much faster | The brief: *"No replay shortcut may exist."* A second code path is a second world. |
| **Let the API call the Crop Manager to register a demand** | Direct, synchronous, obvious | `01_LAYERED` §3.2: the path is deliberately asynchronous and declarative to break the only possible cycle. |
| **Guess a schema version when the consumer asks for an unsupported one** | Fewer rejections | §M14 failure table: *"Reject with the supported set; **never guess**."* |

---

## 20. Ambiguities found, and how each is resolved

Five ambiguities arose. Each is resolved **from the architecture's own text**. None
required a design decision that the documents do not already contain.

### 20.1 P20 is missing `tail()`, which §M13 specifies

**The ambiguity.** Flow 7 realized `ObservationLogPort` with `append`, `read`,
`position` and `truncate`. §M13's Public API specifies five operations:

```text
ObservationLog:
  append(partition, observations)     → LogPosition !AppendFailed
  read(partition, from, to)           ⇢ Observation
  tail(partition, from)               ⇢ Observation        # live follow
  truncate(partition, before)         → void               # retention only
  position(partition)                 → LogPosition
```

`tail` is absent from the implementation.

**Resolution.** This is a genuine gap, not a disagreement. P20 is **M13's port**
(`06_PORTS` P20: *Owner module M13*), and M13 is Flow 8's module — so completing the
contract is Flow 8's work, not a retrospective change to Flow 7. Flow 7 implemented
the subset M12 needed; Flow 8 implements the subset M14 needs, and `tail` is exactly
what §M14's `subscribe` requires for *"live follow"* with `resume_from`.

Adding a method to a Protocol is additive: existing adapters gain a default or an
explicit implementation, and Flow 7's behaviour is unchanged. **Recorded as the one
place where Flow 8 touches a Flow 7 contract, and why it is permitted.**

### 20.2 P21 `StateStorePort` — two shapes for one port id

**The ambiguity.** `06_PORTS` P21 names `StateStorePort`, owned by M13, holding the
*"Current projection"*, with API `put/get/scan/snapshot/delete`. Flow 4 bound
`PortCatalogue.STATE_STORE` to `ObjectStorePort`, whose API is `save/load/forget` and
which holds the *object population*, not the projection.

**Resolution.** Flow 7's review §14.2 already ruled on this: *"one contract, two
legitimate consumers; no new port, no changed binding."* Flow 8 does not revisit a
settled question.

More importantly, **M13's StateStore has no consumer in Phase 1.** §M13's own table
gives it durability *"High, **rebuildable from log**"* and states *"the store is
never on the read path for live queries."* 07_STATE §9.1 makes state-store
corruption a **no-data-loss** scenario precisely because rebuild from log is the
recovery. M12 as implemented holds its projection in memory and rebuilds from the
log — which is the architecture's own recovery path, complete.

Implementing a projection-backing StateStore adapter would therefore be implementing
a contract that nothing calls, and §M13 says to **implement none of it**. The
contract is documented; no adapter is shipped. Recorded in Known Limitations.

### 20.3 Who owns the demand registry — M14 or L3?

**The ambiguity.** §M14 State Ownership says M14 *"owns... the demand registry"* and
that it *"is durable"*. But Flow 5 built a `DemandRegistry` inside
`perception/cropping/` at L3, because M8's trigger policy reads demand state. If M14
owned the only registry, M8 would depend upward on L7 — forbidden by §2.

**Resolution.** `01_LAYERED` §3.1 resolves it exactly:

> *"the API accepts demand contracts, which the **Configuration/demand registry**
> publishes as an event that the Crop Manager's trigger policy reads."*

And §3.2: *"the API writes a demand record; the Crop Manager reads demand state at
trigger time."*

So there is **one registry, two roles**. M14 owns *intake and lifecycle* —
authentication, tenant scoping, validation, acknowledgement, budget policy,
notification. The registry itself is a record store that L3 reads. M14 writes to it;
M14 never calls M8.

Durability comes from M13's **ConfigStore**, whose row in §M13's table explicitly
holds *"Config, calibration, taxonomy, **registry**"*. The architecture already
placed the demand registry's durability, and it is not a new contract.

### 20.4 Does §M14's evidence contract require Flow 8 to bind P22?

**The ambiguity.** P22 `EvidenceStorePort` has been deliberately unbound through
Flows 5, 6 and 7, each time with a recorded reason (*"writing imagery durably is
still nobody's job"*). §M14's Public API includes `get_evidence(evidence_ref) →
EvidenceView !Expired !Forbidden`. Serving evidence requires a store.

**Resolution.** P22 is **M13's port** (`06_PORTS` P22: *Owner module M13*), and M13
is Flow 8's module. The earlier flows' reasons for not binding it were each stated as
*"not this flow's job"* — never *"never."* Flow 6's manifest note reads: *"persisting
them is M13's job."*

Flow 8 is M13. Binding P22 now is the earlier flows' stated expectation arriving on
schedule, not a boundary being crossed early.

The `Expired` / `NotFound` distinction is mandatory (§M13, §6), and `erase(subject_scope)`
must exist for §8.2's right-to-erasure — implemented as **tombstoning**: the blob
goes, the record that it existed and was erased remains.

### 20.5 §M14 lists `register_demand` as inbound — does that violate read-only?

**The ambiguity.** The brief says the API is read-only and consumers *"may NEVER
modify"*. §M14's Public API includes `register_demand`, `update_demand`,
`revoke_demand` — which write something.

**Resolution.** `09_API` §1.1 draws the line precisely: the five contracts are Query,
Subscribe, **Demand**, Coverage/Capability, Evidence — and the sixth, *Mutate*,
*"does not exist."* A demand is inbound **influence**, not a state write:

> *"Consumers must be able to influence what the platform spends money computing
> without telling it why."*

A demand changes **what work the platform chooses to do**. It cannot change an
observation, an object, a track, a projection, or any published fact. §4.2's table
makes the boundary concrete: a demand may say *which registered attributes are
needed*; it may not contain *"a rule, threshold, or conclusion."*

Read-only therefore means **no write path into Vision State**, which is exactly what
§M14 says: *"accept no writes to state."* Demand intake is compatible with it, and
`12_SECURITY` §5.3 confirms demands are a *separate, privileged* action rather than a
read: *"`register_demand` is privileged... Demands spend money and cause computation;
they are not a read."*

---

## 21. Scope statement

Flow 8 implements:

* **M13** — completes P20 with `tail`; defines and binds P22 `EvidenceStorePort`;
  documents the StateStore contract without shipping an adapter it has no consumer for.
* **M14** — query, subscribe, demand intake, coverage, capability, evidence, with
  P31 `AuthorizationPort` and P32 `ApiTransportPort`.
* **System assembly** — one composition root wiring L0 through L7 with no bypasses.
* **Replay verification** — mechanical proof that rebuild reproduces identical state.

Flow 8 does **not** implement: any perception, any inference, any business logic, any
analytics, any aggregation endpoint, cross-camera identity, learning, prediction, or
any Phase 2+ roadmap functionality. M10 Prompt Manager remains unimplemented and out
of scope, as M9 consumes prompts through a module seam rather than a port it owns.

**No architectural change is requested. Implementation may proceed.**
