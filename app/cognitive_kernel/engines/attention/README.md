# Attention Engine

> Implementation Phase 5 — the first *decision-making* cognitive engine.
> Governing law: `docs/architecture/COGNITIVE_ATTENTION_ARCHITECTURE.md` (AL1–AL17),
> the Global Workspace (`COGNITIVE_GLOBAL_WORKSPACE.md`, CL1–CL27), and the
> constitutional infrastructure (Kernel, Runtime, Cognitive State Manager, Working
> Memory Engine). **Where implementation and Constitution disagree, the Constitution wins.**

## Single constitutional responsibility

The Attention Engine **selects what becomes conscious** — nothing more. It is the
gatekeeper between the vast, unconscious Cognitive State and the tiny, bounded
conscious field held by Working Memory. Every cycle it takes a set of *candidates*,
scores their **salience**, runs a **biased competition with an ignition threshold**,
and admits a bounded **coalition** of winners into consciousness by activating them
through the Working Memory Engine.

### What Attention is *not* (boundary discipline)

The engine **never**:

- stores long-term information — it holds only ephemeral, per-cycle dynamics;
- duplicates Cognitive State — it reads references and writes only its own R3 records;
- owns Working Memory — it *requests* activation through WM's public contract;
- performs reasoning, executive planning, learning, or prediction — it exposes no
  `reason` / `plan` / `predict` / `learn` / `reflect` / `decide` / `infer` / `simulate`;
- fabricates a focus — if nothing crosses the ignition threshold, **nothing ignites**
  (AL11); consciousness is allowed to rest;
- modifies Knowledge, and never talks to a sibling engine directly.

These boundaries are enforced mechanically by `tests/cognitive_attention/test_architecture.py`.

## How it honours the infrastructure

| Constitutional rule | Mechanism |
|---|---|
| Register with the Kernel | `register(kernel, runtime)` → `kernel.register_engine(self)` |
| Execute through the Runtime | implements `ExecutableEngine.execute`; WM activation is a **runtime execution**, never a direct call |
| Read/write State only via the State Manager | all reads/writes go through `CognitiveStateManager`; focus/salience/inhibition land in region **R3** |
| Communicate only through the Event Bus | ignition/rest/interrupt emitted as `CognitiveEvent`s on the ledger-backed bus |
| Activate Working Memory only through its public contract | `AttentionWMPort` calls `WorkingMemoryRuntimeApi.ignite/refresh/evict/broadcast`, routed via the Runtime |

## The cycle (`attend`)

```
candidates
  │  _enrich      structural goal-relevance (R2 goals), prediction surprise, novelty (recency window)
  ▼
salience.compose  18-dim vector → composite  (noisy-OR field × precision, safety/risk gates dominate, minus cost)
  │  _adjust      executive bias (safety-bounded), hysteresis for incumbents, inhibition-of-return
  ▼
competition.compete
  │  eliminate < elimination_floor  →  sort (−composite, target)  →  interrupts always enter
  │  admit while composite ≥ ignition_threshold and |coalition| < capacity   (may be empty — AL11)
  ▼
inhibition-before-replacement (AL7): incumbents that lost are evicted before winners load
  ▼
Working Memory activation via the runtime  →  broadcast (Global Workspace)
  ▼
R3 written: ATTENTION_FOCUS · SALIENCE · INHIBITION   (one transaction, new version each cycle)
```

### Salience (`salience.py`)

An 18-dimension **salience vector** (AL2/AL9) is composed into one scalar by a
**hybrid** rule (`COGNITIVE_ATTENTION_ARCHITECTURE.md` §3.4):

- a **safety veto** and a **risk × irreversibility** gate dominate the field — safety-
  relevant or irreversible content is pulled toward the top regardless of goal fit;
- otherwise a **noisy-OR** aggregation of the weighted motivational dimensions forms a
  field, scaled by **precision** (confidence);
- **cognitive cost** is subtracted last (opportunity cost).

Composition is pure and deterministic: same vector + config ⇒ same `(composite, breakdown)`.

### Competition (`competition.py`)

Biased competition with a hard **ignition threshold** and bounded **coalition capacity**.
Below-floor candidates are *eliminated* (not merely inhibited); ties break on the target
handle for determinism; an **interrupt** (safety ≥ veto, or surprise ≥ interrupt threshold)
always claims a slot. The coalition may legitimately be empty.

### Dynamics (`dynamics.py`)

- **`FocusHistory`** — a recency deque driving bottom-up novelty and inhibition-of-return.
- **`FatigueModel`** — sustained focus accrues fatigue (`fatigue_per_cycle`) and recovers
  (`fatigue_recovery`), damping the field so attention cannot lock forever.
- **Hysteresis** — an incumbent keeps a `hysteresis_margin` advantage, preventing flicker.

## Integration hooks (all inbound-only; Attention never reaches out)

- `set_executive_bias(target, bias, ctx)` — the Executive tilts the field. **Safety-bounded**
  (AL8): bias can promote, but can never suppress a candidate below its safety floor.
- `set_prediction_surprise(target, surprise, ctx)` — prediction error feeds the surprise
  dimension. Attention consumes it; it never predicts.
- `feedback(target, label, ctx)` — records a learning signal. Attention *stores* it for the
  Learning Engine; it never adapts itself from it.
- `inspect()` — read-only meta-cognitive view (coalition, salience map, fatigue, metrics).
- `set_config(config, ctx)` — Development-time re-parameterisation, **gated** on `state:admin`.

## Recovery & durability

Attention holds no long-term state, so recovery is reconstruction, not restore:
`reconstruct()` rebuilds the ephemeral coalition/dynamics from the durable R3 record.
Because focus/salience/inhibition live in Cognitive State, a State **checkpoint** captures
them and **restore** brings the conscious field back with everything else — Attention adds
no separate persistence path.

## Files

| File | Responsibility |
|---|---|
| `contracts.py` | Pure ABI: `SalienceVector`, `Candidate`, `ScoredCandidate`, `AttentionConfig`, `AttendResult`, metrics/health, `WorkingMemoryPort`. No sibling imports. |
| `salience.py` | `compose()` + `SalienceEngine` — vector → composite. |
| `competition.py` | `compete()` + `is_interrupt()` — biased competition, ignition, capacity. |
| `dynamics.py` | `FocusHistory`, `FatigueModel` — novelty, IOR, fatigue, hysteresis inputs. |
| `port.py` | `AttentionWMPort` — reads WM via public methods, writes via the runtime-routed WM API. |
| `state_io.py` | R3 read/write of `ATTENTION_FOCUS` / `SALIENCE` / `INHIBITION` in one transaction. |
| `engine.py` | `AttentionEngine` — `CognitiveEngine` + `ExecutableEngine`; the `attend` pipeline and hooks. |
| `errors.py` | `AttentionError` and friends. |

## Tests (`tests/cognitive_attention/`)

`test_salience_competition.py` (unit) · `test_pipeline_wm_integration.py` (pipeline, WM
gating, broadcast, R3, runtime routing) · `test_hooks.py` (executive/prediction bias,
inspect, feedback, gated config) · `test_recovery_concurrency.py` (reconstruct, checkpoint,
concurrency, stress) · `test_architecture.py` (boundary enforcement). **36 tests, all green.**
