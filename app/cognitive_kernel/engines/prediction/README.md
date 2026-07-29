# Prediction Engine

> Implementation Phase 8 — the faculty that imagines possible futures.
> Governing law: `docs/architecture/COGNITIVE_PREDICTIVE_ARCHITECTURE.md` (PrL1–PrL22),
> the Executive (ExL1–ExL30), Reasoning (ReL1–ReL14), Attention (AL1–AL17), the
> Global Workspace (CL1–CL27), and the constitutional infrastructure.
> **Where implementation and Constitution disagree, the Constitution wins.**

## Single constitutional responsibility

Prediction **imagines possible futures**: it constructs isolated simulation
branches, generates bounded multi-scenario futures, runs the forward model,
estimates outcome probability, **risk and opportunity (asymmetrically)**, typed
uncertainty, and **horizon-decayed calibrated confidence**, and returns explainable
forecasts to the Executive. It is the exclusive authority for forecasting.

**Prediction never changes reality.** It only produces *possible* futures.

### The two inviolable boundaries

- **ISOLATION (PrL8)** — *simulation never mutates reality.* This implementation
  realizes the strongest possible form: simulation branches are **in-memory,
  immutable, reference-only**, and the engine has **no write path to Cognitive
  State whatsoever**. Every forecast operation leaves the canonical object count
  unchanged; `canonical_writes()` is `0` by construction. Verified in
  `test_isolation_cleanup.py` and `test_architecture.py`.
- **QUARANTINE (PrL9/PrL10)** — *imagined content never becomes belief or memory.*
  Every forecast, scenario, and branch is tagged `hypothetical`; audit/retention
  goes to the **Ledger** (marked hypothetical, PrL15) and the engine's in-memory
  history — **never** to a canonical State region.

### What Prediction is *not* (boundary discipline)

Prediction **never** modifies canonical State, modifies Knowledge, reasons, makes
executive decisions, attends, learns, or commits simulation results. It exposes no
`reason` / `attend` / `select` / `decide` / `authorize` / `learn` / `allocate`
verb, imports **no sibling engine**, and coordinates only through the Runtime.

## How it honours the infrastructure

| Constitutional rule | Mechanism |
|---|---|
| Register with the Kernel | `register(kernel, runtime)` → `kernel.register_engine(self)` |
| Execute only through the Runtime | implements `ExecutableEngine.execute("forecast"/"assess_risk"/"counterfactual")` |
| Read Cognitive State only through the State Manager | `DriverCollector`/`state_io` read via `state.get`/`query` — **read-only, no writes** |
| Consume conscious information only through Working Memory | `RuntimeWMReadPort` routes WM `broadcast` by name and resolves targets read-only |
| Respond only to Executive prediction requests | the Executive reaches Prediction via `RuntimePredictionPort` (runtime-routed) |
| Never communicate directly with sibling engines | no sibling-engine import; everything by name via the Runtime (ExL8/PrL14) |
| Publish prediction events + metrics | every forecast/risk/counterfactual event is tagged hypothetical (PrL15) |
| Deterministic recovery + checkpointing | history sealed via the kernel `CheckpointStore` (no canonical writes) |

## The simulation pipeline (`forecast`)

```
Executive Request (target, horizon, drivers, stakes, seed, interventions)
  │  Simulation Branch      isolated, in-memory, reference-only (PrL8) — bounded budget (PrL13)
  ▼
Load Conscious Context      WM read (read-only) + explicit canonical handles → causal drivers
  ▼
Generate Scenarios          bounded, stakes-scaled (PrL19): expected · optimistic · pessimistic · tail-risk
  ▼
Forecast Outcomes           seeded Monte-Carlo over the drivers (deterministic lifecycle)
  ▼
Estimate Risks              asymmetric, tail-weighted losses (PrL17)
  ▼
Estimate Opportunities      gains, estimated separately (PrL17)
  ▼
Compute Confidence          calibrated × sample-adequacy × horizon-decay (PrL12), capped if ungrounded (PrL11)
  ▼
Return Forecast             hypothetical, confidence-qualified, with assumptions + consequence cascade (PrL18)
  ▼
Destroy or Archive Branch   destroyed by default (item 36); archived only if explicitly retained for audit
```

Everything is **deterministic given a seed** (`Random(seed)`), so the simulation
lifecycle is reproducible while still exploring genuine scenario variety.

## Reconciliation (PrL22)

`reconcile(request_id, observed)` computes the **surprise** between a prediction and
reality and emits it (to drive attention and learning) and exposes
`learning_calibration_candidates()` — proposals for Learning to calibrate on.
Prediction records the surprise; it never learns from it itself (PrL9).

## Files (the seventeen components, decomposed for auditable, safe imagination)

| File | Component(s) |
|---|---|
| `contracts.py` | Pure ABI: scenario/forecast/branch value objects, read ports. No sibling imports. |
| `drivers.py` | Read-only causal-driver collection from State + conscious content. |
| `montecarlo.py` | The seeded, deterministic sampling framework (Monte-Carlo style). |
| `scenarios.py` | Scenario generation (stakes-scaled), ranking, comparison, counterfactual. |
| `forecast.py` | Forecast Manager — outcome/risk/opportunity/uncertainty/confidence/cascade. |
| `branch.py` | Simulation Manager — isolation, lifecycle, cleanup, budget. |
| `ports.py` | Runtime-routed WM read port + the Executive→Prediction adapter. |
| `state_io.py` | **Read-only** State access + canonical-protection watermark (item 37). |
| `recovery.py` | Checkpoint & deterministic recovery of forecast history. |
| `engine.py` | Prediction Engine (Simulation Controller); `CognitiveEngine` + `ExecutableEngine`. |
| `errors.py` | `PredictionError` and friends (incl. `IsolationViolation`). |

## Tests (`tests/cognitive_prediction/`) — 44 tests, all green

`test_montecarlo_scenarios.py` (Monte-Carlo determinism, scenario generation/ranking,
drivers) · `test_forecast.py` (confidence, horizon decay, ungrounded flag, uncertainty
typing, cascade, asymmetric risk) · `test_pipeline.py` (forecast/risk/counterfactual/
compare, events, runtime, determinism) · `test_isolation_cleanup.py` (**canonical state
untouched**, branch destruction/archival, references-only, budget, cleanup) ·
`test_recovery_concurrency.py` (checkpoint/recover, reconciliation, concurrency, stress) ·
`test_integration_wired.py` (WM conscious context read-only, Executive→Prediction routing) ·
`test_architecture.py` (no sibling imports, no faculty verbs, **zero canonical writes**,
branch isolation, runtime-routed).
