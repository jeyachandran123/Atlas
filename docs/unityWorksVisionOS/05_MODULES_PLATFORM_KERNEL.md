# UnityWorks Vision OS (UWV)

## Phase 1 — Module Specifications III: The Platform Kernel (L0)

| | |
|---|---|
| **Status** | Architecture Blueprint — Phase 1 (Design Only) |
| **Prerequisite** | `00`–`04` |
| **Covers** | Runtime · Configuration Manager · Plugin Manager · Model Manager · Event Bus · Health Monitor · Metrics Engine |

> **The kernel law.** Every L0 module is depended upon by the flow layers and depends on none of them.
> **No kernel module knows what a frame, detection, track, or observation is.** This is not stylistic
> purity: it is what allows the kernel to be reused unchanged by a future UnityWorks Audio OS or
> Sensor OS, and what prevents the kernel from becoming the place where layering rules go to die.

---

## Table of Contents

- [M15 · Runtime](#m15--runtime)
- [M16 · Configuration Manager](#m16--configuration-manager)
- [M17 · Plugin Manager](#m17--plugin-manager)
- [M18 · Model Manager](#m18--model-manager)
- [M19 · Event Bus](#m19--event-bus)
- [M20 · Health Monitor](#m20--health-monitor)
- [M21 · Metrics Engine](#m21--metrics-engine)

---

# M15 · Runtime

### Purpose

Assemble the platform from configuration and plugins, own process and thread lifecycle, and orchestrate
startup, shutdown, and reconfiguration.

> **Single responsibility:** *Make the platform exist and keep it running. Perform no perception.*

### Responsibilities

1. **Composition root** — the one place where the dependency graph is constructed and injected
   (`01_LAYERED` §8.1). No other module constructs a dependency.
2. Own the **execution substrate**: actor scheduling, thread pools, queues, device workers.
3. Own **lifecycle**: ordered startup, readiness gating, graceful drain, ordered shutdown.
4. Own the **clock** — real or virtual — and inject it everywhere (the prerequisite for V13).
5. Manage **camera pipeline placement**: which pipelines run in which worker.
6. Coordinate **reconfiguration**: apply hot-reloadable changes, schedule restarts for the rest.
7. Provide **isolation and supervision**: restart failed components under a supervision policy.

### Public API

```text
boot(config_revision)          → RuntimeHandle !BootFailed
readiness()                    → Ready | NotReady(reasons)
liveness()                     → Alive | Impaired(components)
attach_pipeline(camera_id)     → PipelineHandle !CapacityExceeded
detach_pipeline(camera_id, drain_timeout) → void
reconfigure(new_revision)      → ReconfigureResult
drain(timeout)                 → DrainReport
shutdown(mode: graceful | immediate) → void
topology()                     → RuntimeTopology
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| Validated configuration (M16) | A running, wired platform |
| Plugin catalogue (M17) | Readiness and liveness signals |
| Placement policy | Lifecycle events |
| Reconfiguration requests | Topology reports |

### Dependencies

Configuration Manager (M16), Plugin Manager (M17), Model Manager (M18), Event Bus (M19), Health (M20),
Metrics (M21), OS scheduling and device APIs. **It constructs the flow layers but does not depend on
their semantics** — it wires interfaces it does not interpret.

### State Ownership

**Owns:** the object graph, thread pools, actor registry, pipeline placement, lifecycle state machine,
the clock. All ephemeral, all node-local.

### Thread Safety

The Runtime *is* the threading model (`08_RUNTIME_AND_THREADING.md`). Its own control operations are
serialized through a single supervisor actor, so `reconfigure` and `shutdown` can never interleave
destructively — a class of bug that is otherwise very hard to test for and very damaging in production.

### Failure Handling

| Failure | Response |
|---|---|
| Config invalid at boot | **Fail fast, exit non-zero, explain precisely.** Never boot into a half-valid state |
| A plugin fails to load at boot | If required → fail boot; if optional → boot degraded and report clearly which capability is missing |
| A camera pipeline crashes | Supervised restart with backoff; other pipelines unaffected (actor isolation) |
| A pipeline crash-loops | Stop restarting after a threshold, mark the camera `failed`, keep the platform running (V9) |
| A device (GPU) disappears | Migrate work to remaining devices at reduced cadence; alarm |
| Reconfiguration partially fails | **Roll back to the previous revision atomically.** A half-applied configuration is worse than an outdated one |
| Shutdown requested with work in flight | Drain: stop admission → finish in-flight → flush observations → **commit state** → close. Bounded by timeout, then force |
| OOM | Shed cameras by priority class rather than dying wholesale |

**Graceful drain matters more than it appears.** Without it, every deployment loses the tail of
in-flight observations and leaves the state projection behind the log — creating a small, permanent
inconsistency at every release. Drain-before-exit makes deployments non-events.

### Performance

- **Zero steady-state allocation** in the scheduling substrate.
- **Thread affinity** for device workers; NUMA-aware placement for buffer pools.
- Actor scheduling must scale to hundreds of pipelines per node without a thread each — pipelines are
  logical (`01_LAYERED` §6.2), so a 100-camera node runs ~10–20 OS threads, not 100+.
- Boot time matters: a 100-camera node should reach readiness in tens of seconds, dominated by model
  loading, which is why M18 supports parallel and lazy warmup.

### Extension Points

- **Execution substrates** (port): thread pool, async runtime, process-per-pipeline for hard isolation.
- **Placement policies** (port): static assignment, load-balanced, affinity-based (cameras sharing a
  model on the same node), locality-based (edge nodes near cameras).
- **Supervision policies** (port): restart strategies, circuit-breaking, escalation.
- **Distributed runtime**: pipelines placed across nodes by a cluster scheduler. The `topology()` and
  `attach_pipeline` contracts already express placement, so distribution is an adapter plus a scheduler
  rather than a redesign.

---

# M16 · Configuration Manager

### Purpose

Provide **validated, versioned, layered, injectable configuration**, and be the only component that
reads the outside world for settings.

> **Single responsibility:** *Resolve and validate configuration. Interpret nothing.*

### Responsibilities

1. Resolve layered configuration with a defined precedence.
2. **Validate against schema at load**, before anything starts.
3. Assign an immutable `config_revision` recorded on every observation's provenance (`02_VOM` §3).
4. Distribute typed configuration slices to modules by injection.
5. Support **hot reload** for the subset declared reloadable; require restart for the rest, explicitly.
6. Maintain configuration history and audit.
7. **Reject business logic in configuration** — the fourth guard on V1/V2.

### The layering model

```text
1. Platform defaults          (shipped, immutable)
2. Deployment profile         (edge | node | cluster)
3. Tenant configuration
4. Site configuration
5. Camera configuration
6. Runtime override           (time-boxed, operational, always audited)
```

Later layers override earlier ones. Every effective value is traceable to the layer that set it —
without which "why is this camera running at 2 fps?" becomes an afternoon of archaeology.

### Public API

```text
resolve(scope)                    → EffectiveConfig
slice(module_id, scope)           → TypedConfigSlice        # what a module receives
revision()                        → ConfigRevision
validate(candidate)               → Valid | Violations[]
reload(source)                    → ReloadResult !ValidationFailed
watch(scope)                      ⇢ ConfigChanged
history(scope, window)            → ConfigVersion[]
explain(key, scope)               → ValueOrigin             # which layer set it, and why
override(key, value, ttl, actor)  → OverrideHandle          # audited, expiring
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| Config sources (files, config service, environment) | Typed, validated config slices |
| Schema definitions | `ConfigRevision` identifiers |
| Runtime overrides | Change events |
| Secret store references | Value-origin explanations |

### Dependencies

ConfigStore (M13), secret store, schema validator, Event Bus, Metrics. Depends on **nothing else**.

### State Ownership

**Owns:** the resolved configuration tree, revision history, watchers, override registry.
Snapshot-versioned and read-mostly.

### Thread Safety

Immutable snapshots with atomic swap. A module holds its slice for the duration of an operation and
never observes a torn configuration — important because a camera pipeline reading cadence from one
revision and budget from another produces behaviour nobody can reproduce.

### Failure Handling

| Failure | Response |
|---|---|
| Schema validation fails at boot | **Fail boot** with the precise path and the expected shape |
| Schema validation fails at hot reload | **Keep the current revision**, alarm. Never apply partial configuration |
| A source is unavailable at boot | Fail if required; fall back to the last known-good cached revision if permitted by policy |
| A source is unavailable at reload | Keep current; retry; alarm |
| Secret reference unresolvable | Fail the affected camera only, not the platform |
| A reload changes a non-reloadable key | Apply what is reloadable, report precisely what requires a restart. **Never silently ignore a change an operator made** |
| Conflicting overrides | Last-write-wins with full audit; overrides always expire |

### Performance

Resolution happens at load and on change, never per frame. Hot-path modules hold their slice by
reference. `explain()` may be slow; it is a diagnostic.

### Extension Points

- **Config sources** (port): file, environment, git, config service, Kubernetes ConfigMap, cloud
  parameter store.
- **Secret providers** (port): environment, file, vault, cloud secret manager.
- **Validation extensions**: custom validators per module.
- **Policy-driven configuration** (future): time-of-day profiles, load-adaptive settings.

> **The guard against business logic.** The configuration schema is **closed**. A vertical may supply
> exactly four things: taxonomy mappings, region geometry with opaque labels, prompt pack selection,
> and resource profiles. There is no schema slot for a threshold with business meaning, a role
> definition, or a rule. Attempting to add one requires a schema change, which is a reviewed, visible
> act — which is exactly the point. Closing the schema turns "don't put business logic in config" from
> a code-review convention into a structural property.

---

# M17 · Plugin Manager

### Purpose

Discover, validate, load, isolate, and version **plugins** — the units in which every replaceable
capability arrives.

> **Single responsibility:** *Make third-party and swappable code loadable and safe. Know nothing of
> what it does.*

### Responsibilities

1. Discover plugins from configured sources.
2. Validate **manifests**: declared ports, versions, compatibility ranges, resource needs, signatures.
3. Enforce **contract compatibility** — a plugin declaring `DetectorPort@1.x` loads only against a
   compatible platform.
4. Run the **conformance kit** for the declared port before activation (`06_PORTS_AND_ADAPTERS.md`).
5. Instantiate plugins with the declared **isolation level**.
6. Manage plugin lifecycle: load, activate, deactivate, unload, hot-swap.
7. Enforce the **capability boundary**: a plugin gets its port contract and nothing else.

### The plugin manifest

```text
PluginManifest:
  plugin_id        : PluginId
  version          : SemVer
  implements       : [(PortId, port_version_range)]
  platform_range   : SemVer range
  isolation        : in_process | subprocess | remote
  resources        : { device: cpu|gpu, memory, vram, exclusive: bool }
  capabilities     : declared outputs (classes / attributes) — published for V8 gap reporting
  taxonomy_mapping : TaxonomyMapping?
  signature        : cryptographic signature
  conformance      : { kit_version, last_result, tested_at }
  config_schema    : schema for this plugin's settings
```

### Public API

```text
discover(sources)                → PluginDescriptor[]
validate(descriptor)             → Valid | Violations[]
run_conformance(descriptor, kit) → ConformanceReport
load(plugin_id, version)         → PluginHandle !LoadFailed !ConformanceFailed
activate(handle, port_binding)   → void
swap(port_binding, new_handle, mode: drain | immediate) → SwapResult
deactivate(handle, drain_timeout)→ void
unload(handle)                   → void
catalogue()                      → LoadedPlugin[]
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| Plugin sources and manifests | Loaded, validated plugin handles |
| Port contract registry | Conformance reports |
| Signature trust roots | Capability declarations |
| Isolation configuration | Lifecycle events |

### Dependencies

ArtifactStore (M13), Configuration (M16), port contract registry, conformance kits, signature
verification, Event Bus, Metrics.

### State Ownership

**Owns:** the plugin catalogue, loaded handles, isolation contexts, conformance results, port bindings.

### Thread Safety

Load and unload are serialized through a single actor. Loaded plugins are invoked concurrently by their
consumers; **thread-safety requirements are declared in the manifest** and the Runtime honours them —
a plugin declaring itself single-threaded gets a dedicated worker rather than an unsafe shared one.
This is what makes third-party models with poor concurrency stories usable without contaminating the
platform.

### Failure Handling

| Failure | Response |
|---|---|
| Manifest invalid | Reject at discovery with a precise reason |
| Signature invalid | **Reject.** Unsigned or mis-signed code never loads (`12_SECURITY_AND_PRIVACY.md`) |
| Port version incompatible | Reject with the compatible range named |
| **Conformance kit fails** | **Reject.** This is the mechanism that makes "swap any model without platform change" a guarantee instead of an aspiration |
| Plugin crashes (in-process) | Circuit-break the port binding; fall back if configured; **recommend subprocess isolation for that plugin** |
| Plugin crashes (subprocess) | Restart with backoff; the platform is unaffected |
| Plugin leaks memory | Detected by resource monitoring; recycled on threshold |
| Plugin exceeds declared resources | Throttle or unload; alarm. A declaration is a contract, not a hint |
| Hot swap fails mid-flight | Roll back to the previous plugin; in-flight requests complete on the old one |

### Performance

Loading is startup-time or maintenance-time, never hot-path. Invocation overhead depends on isolation:

| Isolation | Overhead | Use when |
|---|---|---|
| `in_process` | Negligible | Trusted, well-behaved, high-frequency (detectors) |
| `subprocess` | IPC + serialization per call | Untrusted, crash-prone, or GPL-incompatible code |
| `remote` | Network per call | Shared inference servers, cloud models, cross-node scaling |

The same plugin can move between these levels **by configuration alone**, which is what allows a
detector to run in-process on an edge box and on a remote inference server in a cluster with no code
difference.

### Extension Points

- **Plugin sources** (port): filesystem, OCI registry, package index, internal marketplace.
- **Isolation mechanisms** (port): shared library, subprocess with IPC, container, remote service, WASM
  sandbox (a strong future option for untrusted plugins).
- **Signature and provenance schemes** (port).
- **Plugin kinds** are enumerated by the port registry (`06_PORTS_AND_ADAPTERS.md`) — adding a plugin
  kind means adding a port, which is a deliberate, reviewed act.

---

# M18 · Model Manager

### Purpose

Own **model artifacts, devices, residency, versioning, and calibration** so that no perception module
ever loads, places, or evicts a model.

> **Single responsibility:** *Provide a ready model handle on a suitable device. Know nothing about
> what the model is for.*

This module knows about **weights, memory, devices, and versions** — never about detectors, trackers,
or attributes. That ignorance is what lets it serve model kinds that do not exist yet.

### Responsibilities

1. Maintain the **model registry**: identity, version, artifact hash, precision, device requirements,
   licence, model card.
2. Fetch and **verify artifacts** (content hash, signature), cache locally.
3. Manage **residency**: load, warm up, keep resident, evict under pressure.
4. **Arbitrate devices** between competing consumers (detector vs VLM on one GPU).
5. Provide **model handles** with health and readiness.
6. Support **versioned rollout**: pinning, canary, shadow, rollback.
7. Own **confidence calibration profiles** per model (`02_VOM` §7).
8. Publish **capability declarations** for V8 gap reporting.

### Public API

```text
register(model_spec)                → ModelId !ValidationFailed
acquire(model_id, version, device_hint) → ModelHandle !Unavailable !OutOfMemory
release(handle)                     → void
warm(model_id, version)             → void
evict(model_id, version, reason)    → void
resolve(role, policy)               → (ModelId, version)   # e.g. role="primary_detector"
pin(role, model_id, version)        → void
canary(role, candidate, traffic_fraction) → CanaryHandle
shadow(role, candidate)             → ShadowHandle          # runs, never publishes to state
rollback(role)                      → void
calibration(model_id, version)      → CalibrationProfile?
device_status()                     → DeviceReport
subscribe()                         ⇢ ModelLoaded | ModelEvicted | ModelSwapped
                                    | DevicePressure | CanaryPromoted
```

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| Model specifications and artifacts | Ready model handles |
| Device inventory | Device utilization and pressure reports |
| Rollout policy | Model lifecycle events |
| Calibration profiles | Calibration profiles for M11 |
| Consumer demand (acquire/release) | Capability declarations |

### Dependencies

ArtifactStore (M13), Plugin Manager (M17, for runtime adapters), Configuration (M16), device APIs,
Event Bus, Metrics.

### State Ownership

**Owns:** the model registry, local artifact cache, residency table, device allocation map, rollout
state, calibration profiles.

### Thread Safety

Residency operations are serialized through a single actor; handles are reference-counted and safe to
use concurrently. **Device allocation uses a broker pattern**: consumers request capacity, the broker
grants or denies, and no consumer touches device memory directly. Without a broker, a detector and a
VLM sharing one GPU will eventually OOM each other at the worst possible moment, and the failure will
look like a random inference error rather than a resource conflict.

### Failure Handling

| Failure | Response |
|---|---|
| Artifact fetch fails | Retry with backoff; use cached version; if none, the dependent capability is unavailable and says so |
| **Hash mismatch** | **Reject and alarm.** A supply-chain event, not a network glitch |
| Load fails (corrupt, incompatible) | Mark the version bad, fall back to the last known-good, alarm |
| Device OOM on load | Evict by policy (LRU among non-pinned), retry once, then deny with a clear reason |
| Device disappears | Migrate handles to remaining devices; if none, dependent capabilities become unavailable and coverage observations follow (V8) |
| Model degrades (canary worse than baseline) | Auto-rollback on declared guardrails; alarm |
| Two consumers need mutually exclusive residency | Broker arbitrates by priority class; the loser waits or gets a smaller-tier model |
| Licence forbids a deployment context | Refuse to load; this is checked at registration, not discovered in production |

### Performance

- **Warmup is mandatory.** A cold model's first inference can be 10–100× slower; unwarmed models make
  startup look like a performance regression. Warmup runs at load with representative input.
- **Residency policy** is the central trade: keeping a large VLM resident costs VRAM permanently but
  avoids multi-second load latency. Configurable per deployment, because edge and cluster answer this
  differently.
- **Artifact cache keyed by hash** — a model is fetched once per node, forever.
- **Parallel warmup at boot**, bounded by device memory, to keep boot time reasonable.

### Extension Points

- **Runtime adapters** (port): native framework, ONNX Runtime, TensorRT, OpenVINO, Triton, vLLM, cloud
  endpoints.
- **Device abstractions** (port): CUDA, ROCm, Apple Silicon, edge accelerators (Jetson, Hailo, Coral),
  CPU.
- **Residency policies** (port): always-resident, LRU, demand-loaded, tiered.
- **Rollout strategies** (port): pinned, canary, shadow, blue-green.
- **Calibration methods** (port): temperature scaling, isotonic regression, per-site fitting.

> **Shadow mode is the strategic feature.** A new model runs on live traffic, produces observations
> into a **shadow channel that never enters Vision State**, and is compared against the incumbent on
> real data. This is how a model is qualified in 2029 without risking production, and it is only
> possible because observations carry full provenance (V4) and state has a single writer (V6). It is
> also the exact mechanism a future learning pipeline will use — built later, enabled now.

---

# M19 · Event Bus

### Purpose

Decouple producers from consumers for **control-plane notifications**, enabling upward communication
without upward dependencies (`01_LAYERED` §2).

> **Single responsibility:** *Deliver typed notifications. Understand none of them.*

### Responsibilities

1. Typed publish/subscribe with a versioned event registry.
2. Bounded delivery with declared overflow policy per subscription.
3. Ordering guarantees per partition key where declared.
4. Local (in-process) and distributed (cross-node) transport behind one contract.
5. Delivery telemetry: lag, drops, fan-out cost.

### Public API

```text
publish(event)                       → void            # non-blocking, bounded
subscribe(event_types, filter, policy) → Subscription
unsubscribe(subscription)            → void
register_event_type(schema)          → EventTypeId
stats()                              → BusStats
```

```text
DeliveryPolicy:
  at_most_once | at_least_once
  overflow: drop_oldest | drop_newest | conflate | block
  ordering: none | per_partition_key
  max_lag: Duration                  # beyond which the subscriber is dropped with a Gap marker
```

### Inputs / Outputs

Typed events from every module in; filtered event streams to subscribers out. The bus never inspects
payloads beyond the type and partition key.

### Dependencies

Configuration, Metrics. Optionally a transport adapter for distributed mode. **Depends on nothing in
the flow layers**, and must not — a bus that understands detections is no longer a bus.

### State Ownership

**Owns:** the subscription registry, per-subscription buffers and cursors, the event type registry.
Ephemeral; events are notifications, not the system of record. **The observation log (M12/M13) is the
system of record** — this distinction prevents the bus from quietly becoming a durability mechanism it
was never designed to be.

### Thread Safety

Fully concurrent. Publishing is lock-free onto per-subscription bounded queues; each subscription is
drained by its own consumer context. Fan-out is O(matching subscriptions) with a type-and-filter index
so that a publish does not walk every subscriber.

### Failure Handling

| Failure | Response |
|---|---|
| Subscriber slow | Apply overflow policy; **emit a `Gap` marker on drop, never silence** (V8) |
| Subscriber crashes | Drop the subscription, release the buffer, alarm |
| Buffer exhausted | Policy-driven; `block` is permitted only for subscriptions explicitly declared critical, because a blocking subscriber can stall a producer |
| Unknown event type | Rejected at publish; event types are registered, which keeps the bus typed rather than becoming an untyped message soup |
| Distributed transport unavailable | Local delivery continues; remote delivery buffers within bounds, then drops with `Gap` |

### Performance

- Publishing must be **sub-microsecond and non-blocking** — it happens on hot paths.
- **Events are control plane only.** No frame, crop, or tensor ever travels on the bus. Event payloads
  are bounded in size by contract; a large payload becomes a reference to storage.
- At 100 cameras, event volume is thousands per second — trivial, *provided* it never carries pixels.

### Extension Points

- **Transport adapters** (port): in-process, shared memory, NATS, Kafka, cloud pub/sub.
- **Filtering strategies** (port): type, attribute predicate, content-based routing.
- **Dead-letter handling** for undeliverable critical events.

---

# M20 · Health Monitor

### Purpose

Determine and publish the **health of every component and camera**, and — uniquely — translate health
into the **coverage** signal that consumers depend on (V8).

> **Single responsibility:** *Know what is working. Fix nothing, decide no business consequence.*

### Responsibilities

1. Collect health reports from every component.
2. Aggregate component health into **camera health** and **site health**.
3. Detect **silent failures** — the ones that matter most: a stream that connects but delivers no
   frames, a detector that returns empty results indefinitely, a model whose confidence distribution
   collapses, a scene that has stopped changing because the lens is obscured.
4. Publish **liveness and readiness** for orchestration.
5. **Generate coverage state** feeding M11's `coverage` observations.
6. Run active probes (synthetic frames through the pipeline) where passive signals are insufficient.

### Public API

```text
report(component_id, health)     → void          # components push
component_health(component_id)   → ComponentHealth
camera_health(camera_id)         → CameraHealth
site_health(site_id)             → SiteHealth
coverage_state(scope)            → CoverageState
liveness() / readiness()         → probe results
subscribe()                      ⇢ HealthChanged | CoverageChanged | SilentFailureSuspected
```

```text
HealthState: healthy | degraded | blind | failed | starting | draining
```

| State | Meaning | Consumer consequence |
|---|---|---|
| `healthy` | Operating within expectations | Observations are trustworthy |
| `degraded` | Working with reduced capability (lower cadence, fallback model, no calibration) | Observations are valid but thinner; check coverage |
| `blind` | **Connected but not perceiving** | **Absence of observations means nothing** |
| `failed` | Not operating | As above |
| `starting` / `draining` | Transitional | Expect gaps |

**`blind` is the state that justifies this module's existence.** A camera that is streaming, decoding,
and detecting nothing because a delivery truck parked in front of it is *healthy* by every naive
metric and *useless* in fact. Distinguishing these is what stops a consumer concluding "the area was
clear."

### Inputs / Outputs

| Inputs | Outputs |
|---|---|
| Component health reports | Component, camera, and site health |
| Metrics (rates, latencies, distributions) | Coverage state for observation generation |
| Stream events (M2), drop alarms (M3), budget alarms (M8) | Liveness/readiness probes |
| Active probe results | Health change events |

### Dependencies

Metrics Engine (M21), Event Bus (M19), Configuration. Reads from everything; **is depended on by
nothing on the hot path**, so its failure never stops perception.

### State Ownership

**Owns:** current health per component, health history windows, coverage state, probe schedules,
detector baselines for silent-failure detection.

### Thread Safety

Concurrent writes from many reporters into sharded, per-component state; aggregation runs on a periodic
tick rather than on every report, so a thousand reports per second cost one aggregation pass.

### Failure Handling

| Failure | Response |
|---|---|
| A component stops reporting | Treated as **unhealthy after a timeout**. Silence is never health — this default is the single most important line in the module |
| Health monitor itself fails | Platform continues perceiving; readiness degrades so orchestration notices. **Health is observational, never load-bearing** |
| Probe fails | Distinguish probe infrastructure failure from genuine component failure before alarming |
| Flapping | Hysteresis and dwell thresholds; a state change requires persistence to avoid alarm storms |

### Performance

Reporting is a cheap non-blocking write. Aggregation is periodic (1–5 s). Active probes are rate-limited
and must never consume meaningful perception capacity.

### Extension Points

- **Silent-failure detectors** (port): frame-rate anomaly, detection-rate anomaly, confidence-distribution
  drift, **scene-stability check** (a static scene may mean an obscured or frozen camera — and also
  feeds M1's viewpoint-drift signal), colour-histogram anomaly (IR mode stuck, lens fogged).
- **Health aggregation policies** (port).
- **Probe strategies** (port): synthetic frame injection, canary objects, end-to-end trace probes.
- **External health sinks** (port): orchestrator probes, monitoring systems, on-call routing.

---

# M21 · Metrics Engine

### Purpose

Collect, aggregate, and export **quantitative telemetry** for every module, so that behaviour,
performance, and cost are measurable rather than anecdotal.

> **Single responsibility:** *Count things accurately and cheaply. Interpret nothing.*

### Responsibilities

1. Provide counters, gauges, histograms, and timers with low-overhead recording.
2. Enforce **label cardinality limits** — the standard way metrics systems destroy themselves.
3. Aggregate locally and export to external systems.
4. Provide **cost accounting**: inference calls, device-seconds, and (for remote models) currency, by
   camera, model, tenant, and demand.
5. Support **distributed tracing** for end-to-end latency attribution.
6. Feed the Health Monitor's anomaly detection.

### Public API

```text
counter(name, labels).increment(n)
gauge(name, labels).set(v)
histogram(name, labels).record(v)
timer(name, labels).time(scope)
trace(operation, context)            → Span
snapshot()                           → MetricsSnapshot
export()                             → void
cost_report(scope, window)           → CostReport
```

### The core metric set

Every module reports against a common shape, which is what allows one dashboard to describe a platform
whose internals will change completely over a decade.

| Category | Metrics |
|---|---|
| **Throughput** | frames received / admitted / dropped (by reason), detections, tracks, observations published / suppressed |
| **Latency** | per-stage duration histograms, end-to-end frame→observation, queue wait |
| **Saturation** | queue depths, pool occupancy, device utilization, in-flight counts |
| **Errors** | by module, by classification, by adapter |
| **Quality** | confidence distributions, quality-gate pass rate, crop rejection reasons, class distribution |
| **Cost** | inference calls, device-seconds, currency by model/camera/tenant/demand |
| **Coverage** | observable time fraction per camera, blind duration, capability gaps |

**Confidence distributions and class distributions are the drift canaries.** When a detector is
swapped, or a camera's lens degrades, or a site's lighting changes seasonally, these distributions move
before anyone notices bad results. This is the cheapest early-warning signal a vision platform has, and
it costs one histogram.

### Inputs / Outputs

Measurements in; aggregated series, traces, and cost reports out to external systems.

### Dependencies

Configuration, an export adapter. Depends on nothing in the flow layers.

### State Ownership

**Owns:** metric registries, aggregation buffers, cardinality tracking, trace context.

### Thread Safety

Fully concurrent, **lock-free on the recording path** — per-thread or per-shard accumulators merged at
export. Recording a metric must never contend, because it happens on every hot path in the platform.

### Failure Handling

| Failure | Response |
|---|---|
| Export destination unavailable | Buffer within bounds, then drop oldest; **never block the platform to record a metric** |
| Cardinality explosion | Enforce limits, collapse offending labels into `other`, alarm. Unbounded labels (per-object-id metrics, for instance) will otherwise take down the metrics backend and then the platform along with it |
| Metrics engine fails | Perception continues. Metrics are observational, never load-bearing |

### Performance

Recording is nanoseconds. Aggregation is periodic. **Cardinality is the real constraint**: labels are
bounded to `camera_id`, `model_id`, `tenant_id`, `reason` and similar closed sets — never `object_id`,
never `frame_ref`.

### Extension Points

- **Export adapters** (port): Prometheus/OpenMetrics, OpenTelemetry, StatsD, cloud monitoring, local
  files for air-gapped edge deployments.
- **Trace exporters** (port).
- **Cost models** (port): device-seconds, token-based for remote VLMs, blended per-tenant chargeback.
- **Anomaly detectors** (port) feeding M20.

---

## Kernel summary

| Module | Knows about vision? | Durable state? | On hot path? | Failure stops perception? |
|---|---|---|---|---|
| Runtime | No | No | Yes (scheduling) | Yes — it is the substrate |
| Configuration Manager | No | Yes (versioned) | No (resolved once) | Only at boot |
| Plugin Manager | No | No (catalogue) | No | Only at load |
| Model Manager | No | Yes (registry, cache) | Yes (handle acquisition) | Partially — degrades to fallbacks |
| Event Bus | No | No | Yes (publish) | No |
| Health Monitor | No | No (windows) | No | **No — observational only** |
| Metrics Engine | No | No | Yes (recording) | **No — observational only** |

The last two rows are a deliberate design property: **the platform must keep perceiving even when it
has lost the ability to describe how well it is perceiving.** Observability that can take down the
system it observes is a liability, not an asset.

---

## Where to go next

| Question | Document |
|---|---|
| What are the exact port contracts these load? | `06_PORTS_AND_ADAPTERS.md` |
| How do threads, actors, and the clock work? | `08_RUNTIME_AND_THREADING.md` |
| How does failure recovery compose across modules? | `10_RELIABILITY_AND_FAILURE.md` |
| How is all of this deployed? | `13_DEPLOYMENT_ARCHITECTURE.md` |
