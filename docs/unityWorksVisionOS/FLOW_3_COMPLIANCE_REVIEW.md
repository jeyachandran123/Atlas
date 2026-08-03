# Flow 3 — Architecture Compliance Review

**Performed before any code was written**, as required. This document records what
the architecture obliges the Tracking implementation to do, what it forbids, and
the one place where a Flow 2 implementation detail contradicts the constitution.

Documents reviewed: `03_MODULES` (M6, M7 boundary), `01_LAYERED`, `06_PORTS`,
`07_STATE`, `08_RUNTIME`, `09_API_CONTRACTS`, `10_RELIABILITY`, `11_PERFORMANCE`,
`12_SECURITY`, `14_TESTING`. `00_CHARTER` consulted for constitutional
clarification; `15_ROADMAP` consulted only to confirm nothing future is built.

---

## 1. M6 Tracking Engine — binding requirements

`03_MODULES §M6` states the single responsibility as: *"Associate detections
across time within one camera. Never assert durable identity — that is M7."*

| # | Obligation | Source |
| --- | --- | --- |
| 1 | Associate detections frame-to-frame into tracks | M6 R1 |
| 2 | Maintain lifecycle `tentative → confirmed → coasting → lost → terminated` | M6 R2 |
| 3 | Estimate motion (velocity, heading, acceleration) and classify `motion_state` | M6 R3 |
| 4 | Predict during gaps, marking predictions via `measurement_basis` | M6 R4 |
| 5 | Report association confidence and `break_reason` diagnostics | M6 R5 |
| 6 | Treat detection gaps as **normal operating condition**, not an exception path | M6 R6 |

**Public API is fixed by the architecture** and is implemented verbatim:

```text
update(camera_id, frame_ref, detections)  → TrackUpdate
tracks(camera_id)                          → Track[]
reset(camera_id, reason)                   → TrackerEpoch
capabilities()                             → TrackerCapabilities
health()                                   → ComponentHealth
```

### 1.1 The lifecycle has five states, not six

The architecture specifies exactly five: `tentative`, `confirmed`, `coasting`,
`lost`, `terminated`. `coasting` is called out as **first-class, not an
implementation detail** — a coasted position is a prediction, and anything derived
from it must be marked so consumers never read inferred position as measured
(V8 at object scale).

An earlier framing of this work named a six-state model with `NEW` and
`RECOVERED`. Those are not states in the constitution, and they are not added.
They map without loss onto what the architecture already has:

- `NEW` is the *creation* of a track, which enters at `tentative`. It is an
  **event** (`TrackCreated`), not a state.
- `RECOVERED` is the *transition* `coasting|lost → confirmed` by re-association.
  It is an **event** (`TrackRecovered`), not a state.

Modelling them as events rather than states preserves the architecture exactly
while losing none of the observability that motivated them. Every transition is
observable either way; the difference is that the state set stays closed.

### 1.2 Track model — fixed by `02_VOM §10.5`

```text
Track:
  <substrate>                    # confidence.semantics = ASSOCIATION
  track_id, camera_id, tracker_epoch
  state          : tentative | confirmed | coasting | lost | terminated
  detections     : FrameRef[]    # references, NEVER copies
  motion         : velocity, acceleration, heading
  motion_state   : stationary | moving | erratic | unknown
  first_seen, last_seen, age_frames, coast_frames
  break_reason   : occlusion | exit | detector_miss | association_failure | none
```

`TrackId` is **composite** — `(CameraId, TrackerEpoch, LocalTrackId)` — not a bare
integer. This is what makes a track id meaningless outside its camera and epoch,
and is the structural reason a track id can never become an identity.

`detections` holds `FrameRef[]` — references, never copies. Copying detections
into tracks would make tracking memory grow with track lifetime, violating T8.

### 1.3 State ownership — `07_STATE`, `03_MODULES §M6`

Tracking owns **per-camera tracker state only**: active tracks, motion filter
state, epoch counter. This is described as *"the platform's most volatile state
and deliberately not durable."* On restart, tracks restart under a new
`TrackerEpoch`. Object continuity across restarts is M7's problem.

Tracking therefore **writes no Vision State**. `CameraPartition.tracker_epoch`
exists in state, but it is written by the state projector (Flow 7), not by M6.

---

## 2. P9 TrackerPort — the eight obligations

`06_PORTS §P9`. Every one is implemented as an executable conformance check.

| # | Obligation |
| --- | --- |
| **T1** | Strictly sequential per camera; reject violations rather than degrade silently |
| **T2** | **Non-uniform time gaps are normal.** Motion must integrate over *elapsed time*, never frame count |
| **T3** | Track IDs unique within `(camera_id, tracker_epoch)`, **never reused** within an epoch |
| **T4** | Association confidence carries `ASSOCIATION` semantics and is honest |
| **T5** | Coasting explicitly marked; predictions never presented as measurements |
| **T6** | Termination carries a `break_reason` |
| **T7** | State is per-camera and fully reset by `reset()`; no cross-camera state |
| **T8** | Memory bounded regardless of scene duration or object count |

**T2 is singled out by the architecture** as *"the single most common way an
off-the-shelf tracker misbehaves inside UWV"* — because the scheduler drops frames
by design (V7), a tracker validated only on continuous video is not validated for
this platform (`14_TESTING §7.2`). This gets disproportionate test weight.

---

## 3. Runtime and threading — `08_RUNTIME`

| Rule | Requirement |
| --- | --- |
| Concurrency model | **Actor per camera**, single-threaded. M6 is named in the actor table. |
| Ordering | Hard requirement. Source assigns `FrameSeq`; tracker **asserts monotonicity and rejects violations loudly**. |
| Cross-camera | No shared state; cameras run fully parallel with zero contention. |
| Queue `Detection → Tracking` | **Small capacity, `block` policy.** *"Ordering matters; dropping here corrupts tracks."* |

The queue policy is a hard constraint and differs from Flow 2's detection queue,
which sheds under pressure. Tracking must apply **backpressure**, never drop.

---

## 4. Reliability — `10_RELIABILITY`

| Failure | Required response |
| --- | --- |
| Detection gap | Coast with prediction; mark `predicted`; terminate after `max_coast` |
| Occlusion | Coast; `break_reason = occlusion` |
| Suspected ID switch | Emit **low** association confidence. *"The tracker never hides uncertainty to look clean."* |
| Association ambiguity | **Prefer terminating a track over a wrong association** |
| Adapter failure | Fall back to a trivial IoU tracker so the pipeline degrades rather than stops (V9) |
| Out-of-order frame | Reject, count, alarm — **loudly**; this is a pipeline bug |
| State corruption / unbounded growth | Reset with a new epoch so consumers see discontinuity rather than inferring teleportation |

`tracker.iou` is named twice — in M6 failure handling and in `10_RELIABILITY §7.3`
as one of only two **always-available fallbacks** in the entire platform: *"pure
geometry, no weights, no device."* It is mandatory, not a convenience.

---

## 5. Security and privacy — `12_SECURITY`

Decisive for the appearance/embedding question.

- Appearance embeddings are classified **C2 · Biometric**.
- **Disabled by default**; session-scoped when enabled; policy-gated; restricted
  access; separate retention.
- *"UWV holds no persistent biometric identity by default."*
- Threat #4 is **identity linkage**: *"any persistent mapping that links sightings
  across time or cameras."*

**Consequence for this flow:** `EmbeddingPort` (P10) is declared as a seam so that
`requires_embeddings` is a meaningful capability and a DeepSORT-class adapter is
possible later. **No embedding adapter is shipped, none is bindable by default,
and the tracking layer stores no embedding.** A tracker declaring
`requires_embeddings: true` must fail to activate when no provider is configured,
rather than silently degrading to geometry — silent degradation would make a
capability gap invisible, violating V8.

---

## 6. Performance — `11_PERFORMANCE`

| Stage | Budget | Scales with |
| --- | --- | --- |
| Tracking | **~0.3 ms/frame** | Processing rate × **object count** |

Relative cost 1.5 against detection's 15 — tracking is ~5% of pipeline cost and
must stay there. Association is O(n·m); gating by predicted position makes it
effectively linear at realistic densities; crowd scenes (n > 100) need spatial
hashing.

---

## 7. Testing — `14_TESTING`

`§4` names the M6 invariants that must be verified: non-uniform time gaps,
coasting marked predicted, out-of-order frame rejected loudly, track ID uniqueness
within epoch.

`§7.2` states tracker quality is **not** per-frame accuracy, and names the metrics
that matter: **track fragmentation rate**, **ID switch rate**, **occlusion
recovery rate**, and **behaviour under non-uniform time gaps**.

---

## 8. Scope confirmation against `15_ROADMAP`

Confirmed **not** implemented, and structurally prevented:

| Capability | Roadmap phase | Seam |
| --- | --- | --- |
| Cross-camera identity | Phase 2 | `IdentityResolverPort` (P11) — defined, unused, unbindable |
| Federated multi-site identity | Phase 2+, policy-gated | — |
| Persistent biometric identity | Disabled by default | C2, policy-gated |

Durable object identity (`ObjectId`) belongs to **M7 Object Registry**, which is
Flow 4+ and is not implemented here.

---

## 9. Architectural conflict found — one

### 9.1 The conflict

Flow 2's `DetectionRuntime` module docstring asserts:

> *"Detections are published to the **Event Bus**, not handed to a named successor.
> Flow 3 subscribes; Flow 2 does not know it will."*

The architecture says otherwise, in three places:

1. **`01_LAYERED §2.1`** classifies `L2 Tracking consumes L2 Detection output` as a
   **sideways within-layer** dependency — *"Direct, but only along the declared
   intra-layer order."* The Event Bus is listed separately, as the mechanism for
   **upward** notification only.
2. **`08_RUNTIME §5.2`** specifies the `Detection → Tracking` connection as a
   bounded queue with **`block`** policy, rationale *"Ordering matters; dropping
   here corrupts tracks."*
3. **`08_RUNTIME §3.2`** makes per-camera ordering a hard guarantee that the
   tracker asserts on.

The Event Bus as built in Flow 1 is **lossy by design** — bounded per-subscriber
capacity with `drop_oldest` and a synthesized `Gap` marker. That is correct for
upward notification and wrong for this edge. Routing detections to tracking over
the bus would drop detections under load, silently corrupting tracks, which is
precisely the failure `08_RUNTIME §5.2` legislates against.

### 9.2 Assessment

This is **not** a defect in the architecture, and no architectural change is
requested. It is a Flow 2 implementation statement that overreached: Flow 2
correctly published `DetectionCompleted` / `DetectionFailed` to the bus for
*observability*, then described that bus as the *pipeline transport* for Flow 3.
The constitution never said that.

Flow 2 also already ships the correct seam in embryo — `DetectionRuntime(sink=...)`,
"an optional in-process tap on the detection stream". It is insufficient as
written:

| Gap | Consequence for tracking |
| --- | --- |
| Called only when `outcome.detections` is non-empty | **Fatal.** A frame with zero detections is exactly when tracks coast and terminate. A tracker that never sees empty frames never ages a track. |
| Carries `Sequence[Detection]`, no `FrameRef` | An empty frame has no frame reference at all; ordering cannot be asserted. |
| No failure signal | "Detector failed" and "nothing was there" become indistinguishable — a direct V8 violation. |
| Synchronous, exceptions swallowed with `pass` | Cannot apply backpressure (`block`); a tracking fault vanishes silently. |

### 9.3 Resolution

Widen the existing Flow 2 extension point rather than adding a second one. The
`sink` parameter's type becomes a protocol carrying the whole `DetectionOutcome`,
invoked for **every** outcome including empty and failed:

```python
@runtime_checkable
class DetectionConsumer(Protocol):
    async def on_detected(self, outcome: DetectionOutcome) -> None: ...
```

This is a **public-contract change to Flow 2**, which this flow's brief explicitly
permits ("Flow 2 remains unchanged except through approved extension points" /
"except public contracts"). It changes no detection *behaviour*: the consumer is
optional and defaults to `None`, and the bus events Flow 2 publishes are untouched.

The misleading docstring is corrected to state what the architecture states.

**Recorded as an architectural discovery, not an architectural change.** The
constitution is unmodified; a Flow 2 comment that contradicted it is.

---

## 10. Compliance conclusion

The architecture specifies M6 completely enough to implement without inference.
One conflict was found, and it lies in Flow 2's implementation rather than in the
architecture; it is resolved by conforming Flow 2 to the constitution through an
extension point the constitution already sanctions.

**No architectural change is requested. Implementation may proceed.**
