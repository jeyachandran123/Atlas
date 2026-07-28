# Reasoning Engine

> Implementation Phase 6 — the first engine that performs true cognitive inference.
> Governing law: `docs/architecture/COGNITIVE_REASONING_ARCHITECTURE.md` (ReL1–ReL14),
> the Global Workspace (CL1–CL27), Attention (AL1–AL17), and the constitutional
> infrastructure (Kernel, Runtime, Cognitive State Manager, Working Memory, Attention).
> **Where implementation and Constitution disagree, the Constitution wins.**

## Single constitutional responsibility

The Reasoning Engine **transforms consciously attended information into justified
conclusions** — and nothing else. It collects and weighs evidence, generates and
ranks hypotheses, runs the appropriate *kind* of inference behind a substitutable
engine port, estimates calibrated confidence, guards its own consistency, knows
when to stop, and records an explainable, auditable trace. It is the exclusive
constitutional authority for cognitive inference in UnityWorks.

Above all, reasoning is **a faculty, not a wrapper** (ReL1): the Generation
Platform (an LLM) — or a symbolic solver, or a probabilistic engine — is *one
instrument behind the port*, never "the reasoner". The engines will change many
times over the coming decade; the way UnityWorks thinks will not.

### What Reasoning is *not* (boundary discipline)

Reasoning **never**:

- selects attention or scores salience (that is Attention);
- owns, activates, or mutates Working Memory — it only *reads* conscious content
  through WM's public read contract (that is WM/Attention);
- commits an executive decision or exercises executive authority (that is Executive);
- predicts futures or runs simulations — it *requests* them through a hook (Prediction);
- learns, validates, or commits durable change — it only *proposes* (Learning);
- modifies Knowledge, bypasses the Runtime, bypasses the State Manager, or talks to
  a sibling engine directly.

It exposes no `attend` / `select` / `ignite` / `evict` / `plan` / `decide` /
`predict` / `learn` / `reflect` / `commit` / `broadcast`. These boundaries are
enforced mechanically by `tests/cognitive_reasoning/test_architecture.py`.

## How it honours the infrastructure

| Constitutional rule | Mechanism |
|---|---|
| Register with the Kernel | `register(kernel, runtime)` → `kernel.register_engine(self)` |
| Execute through the Runtime | implements `ExecutableEngine.execute("reason", …)`; prediction requests are routed via the Prediction hook (runtime-mediated when wired) |
| Read/write State only via the State Manager | evidence read from R5; episode written to **R6** `REASONING_STATE`; conclusion written to **R5** `BELIEF` (PROPOSED); learning candidates to **R9** (PROPOSED) |
| Consume conscious content only from Working Memory | `ReasoningWMPort` uses WM's public `read_focus`/`contents` — read-only |
| Never access Knowledge | no Knowledge dependency exists |
| Request simulations only through Prediction hooks | `PredictionPort` (null by default); reasoning never predicts |
| Communicate only through the Event Bus | `reasoning.*` events on the ledger-backed bus |
| Propose, never commit (ReL9) | beliefs and learning candidates are written **PROPOSED** |

## The pipeline (`reason`)

```
Working Memory (conscious focus)
  │  EvidenceCollector      read WM focus → resolve R5 objects → parse: Evidence · Rule · CausalLink · Analogy
  ▼
EvidenceEvaluator          weight = reliability × confidence × relevance ; belief evaluation (noisy-OR)
  ▼
HypothesisGenerator        question → {q, ¬q} ; or best-explanation via abduction ; + analogical transfer   → rank
  ▼
Type + Strategy selection  (explicit & recorded — ReL6)   [Executive/Meta-Reasoning hooks may bias]
  ▼
Reasoning loop (bounded)   Engine Pool → EngineProduct → calibrate (ReL3) → monotone (ReL4)
  │   symbolic (deduction/constraint) · probabilistic (weighing/induction/causal) · heuristic (System-1)
  │   consistency guard → contradiction detect + arbitrate (ReL10)
  │   convergence monitor + resource governor → converge / good-enough / budget / impasse (ReL7)
  │   switch strategy/type on impasse ; verify-then-trust ; ensemble
  ▼
Conclusion                 top hypothesis ; typed uncertainty ; escalate if unresolved or low-confidence high-stakes (ReL13)
  ▼
Explanation                auditable justification narrative (ReL5)
  ▼
State update               R6 episode record (history) · R5 PROPOSED belief (dep-edges to evidence) · R9 learning candidate
  ▼
Events                     reasoning.initiated · .strategy_switched · .contradiction · .concluded / .escalated / .terminated
```

### The engine pool — model independence (ReL1)

`pool.py` ships three deterministic, pure-stdlib engines *behind one port*:

- **Symbolic** — exact, verifiable deduction (backward-chaining modus ponens,
  recursion-bounded) and constraint checking. Calibration 1.0 (trusted when premises hold).
- **Probabilistic** — evidence weighing (noisy-OR) for abduction/diagnosis, plus
  induction and causal query. Calibration 0.9.
- **Heuristic** — a single System-1 shortcut (highest-prior hypothesis). Calibration 0.7.

A future LLM plugs in as a fourth engine (calibration 0.6) with **no change to the
faculty**. The pool routes by type, supports ensembles, verifies (verify-then-trust),
and *degrades gracefully on engine failure* (ReL14) — it falls back, never crashes.

### Confidence discipline

- **Calibration (ReL3):** every engine's self-reported confidence is discounted by
  its recorded calibration — fluency is never trusted at face value.
- **Monotonicity (ReL4):** a conclusion is no more confident than its weakest
  necessary premise.
- **Risk-scaled sufficiency (ReL13):** the autonomy threshold rises with stakes and
  irreversibility; below it, low confidence escalates (epistemic → reason more,
  aleatoric → hedge, high-stakes → human).

### Statelessness, interruption, recovery (ReL2 / ReL8)

Reasoning holds **no durable state**. The Working Reasoning Space is a transient,
reasoning-local, references-only scratch — not a WM store. It is serialised into the
R6 episode record, so an interrupted episode is checkpointed (`state.checkpoint()`
captures R6) and **resumable** (`resume(episode_id)`), and a transient space is
reconstructable from its trace (`reconstruct(episode_id)`). Parallel episodes each
own an independent space keyed by a unique episode id — genuine parallel reasoning
contexts with no collision.

## Integration hooks (all inbound-only; Reasoning never reaches out)

- `set_strategy_directive` / `set_deliberation_directive` — the Executive / Meta-Reasoning
  governor biases strategy and bounds depth/budget (item 33).
- `request_prediction` — request a forecast/simulation; null by default, a real
  Prediction engine plugs in behind the port (item 34).
- `inspect(episode_id)` — read-only meta-cognitive view: metrics, fatigue, engines,
  the episode record (item 35).
- `learning_candidates(episode_id)` — the PROPOSED R9 proposals for Learning to
  validate and commit — reasoning proposes, never disposes (item 36).
- `feedback(target, outcome)` — records a learning signal (reasoning records; it never learns).
- `set_config(config)` — Development-time re-parameterisation, **gated** on `state:admin` (item 37).

## Files

| File | Responsibility |
|---|---|
| `contracts.py` | Pure ABI: types, strategies, episode/step value objects, `ReasoningEnginePort`, `PredictionPort`, `WorkingMemoryReadPort`. No sibling imports. |
| `evidence.py` | Collect conscious content, evaluate & weight evidence, evaluate beliefs. |
| `inference.py` | The logical inference engine: prove/forward deduce, abduce, induce, analogize, causal query, constraint satisfaction. |
| `hypothesis.py` | Hypothesis generation and ranking. |
| `confidence.py` | Calibration, monotonicity, sufficiency, uncertainty typing. |
| `consistency.py` | Assumption tracking, contradiction detection, conflict arbitration. |
| `pool.py` | Substitutable engines + `EnginePool` + `NullPredictionPort`. |
| `dynamics.py` | Type/strategy selection, convergence monitor, resource governor, fatigue. |
| `space.py` | `WorkingReasoningSpace` — transient, bounded, checkpointable scratch. |
| `trace.py` | `TraceBuilder` — the auditable justification (ReL5). |
| `port.py` | `ReasoningWMPort` — read-only conscious content. |
| `state_io.py` | R5/R6/R9 writes via the State Manager. |
| `engine.py` | `ReasoningEngine` — the Controller; `CognitiveEngine` + `ExecutableEngine`. |
| `errors.py` | `ReasoningError` and friends. |

## Tests (`tests/cognitive_reasoning/`)

`test_inference.py` (units: deduction/induction/abduction/analogy/causal/constraints,
confidence, hypotheses, evidence) · `test_pipeline.py` (integration, multi-step,
WM-only consumption, R5/R6 products, events, runtime, determinism) ·
`test_reasoning_dynamics.py` (contradiction, escalation, recursion bound, strategy
switch, budget) · `test_hooks.py` (executive/prediction/meta/learning/development) ·
`test_recovery_concurrency.py` (reconstruct, checkpoint, interrupt+resume, concurrency,
stress) · `test_architecture.py` (boundary enforcement). **48 tests, all green.**
