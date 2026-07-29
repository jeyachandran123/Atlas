# Development System

> Implementation Phase 11 — the final constitutional faculty: long-term capability evolution.
> Governing law: `docs/architecture/COGNITIVE_DEVELOPMENT_ARCHITECTURE.md` (DeL1–DeL16).
> **Where implementation and Constitution disagree, the Constitution wins.**

## Single constitutional responsibility

Development is the authority for **long-term cognitive evolution** — and it produces
**proposals only**. It never changes cognition directly: it studies long-term
evidence, measures per-capability maturity, detects architectural limitations,
generates capability-evolution proposals, produces developmental roadmaps, and
supplies future architectural recommendations.

### The bounded, additive, proposal-only posture

- **Bounded (DeL13).** Development improves the *use* of faculties within fixed
  architectural limits — it never changes the limits or the architecture.
- **Realized by Learning (DeL10).** Development *targets and aggregates* Learning's
  results; the learning pipeline is its mechanism. It never bypasses or duplicates it.
- **Aggregate & trend-based (DeL12).** Never per-event — robust to noise and gaming.
- **Per-capability maturity (DeL9).** Maturity is certified per capability, never a
  global scalar the mind *is*; earned by objective outcomes (DeL2), evidence-gated
  (DeL15).
- **Gain slow, lose fast (DeL5/DeL6).** Maturity rises at most one level per cycle and
  falls immediately on regression — a fail-safe. Every certification is versioned,
  reversible, auditable (DeL11).
- **Constitution & identity Core are invariant (DeL1/DeL16).** No proposal may touch
  them — such proposals are blocked by policy, never generated. No maturity stage
  transcends the constitution.
- **Human authority undiminished (DeL3/DeL8).** Architectural/autonomy proposals
  require human review; Development applies nothing.
- **Writes no canonical state.** Artifacts are immutable, in the engine repository and
  the Ledger; `canonical_writes()` is `0` by construction.

### What Development is *not* (boundary discipline)

Development **never** reasons, learns, predicts, governs, or attends; never modifies
canonical cognition or any engine; never rewrites the constitution; never
auto-evolves architecture; never bypasses the Runtime or State Manager; never imports
a sibling engine. It exposes no `reason`/`predict`/`govern`/`learn`/`commit` verb —
enforced by `test_architecture.py`.

## The development pipeline (`develop`)

```
Learning Evidence + Meta Trends   (from the cumulative Ledger + read-only State — DeL10/DeL12)
  ▼
Long-Term Analysis                immutable DevelopmentWindow (aggregate rates, per-capability signals)
  ▼
Capability Assessment             per-capability maturity certification, gain-slow/lose-fast (DeL6/DeL9/DeL11)
  ▼
Trend Analysis                    per-capability trajectories; regression is a fail-safe signal (DeL14)
  ▼
Gap Detection                     limitations (capacity/coverage/calibration/robustness) + maturity gaps
  ▼
Development Proposal               evidence-backed, versioned evolution proposals (constitution-touching ones blocked)
  ▼
Roadmap                           versioned roadmap (short/medium/long horizons)
  ▼
Review                            proposals submitted to the Executive → human (never applied — DeL3/DeL8)
  ▼
Future Evolution Artifact          immutable, auditable DevelopmentArtifact (DeL11)
```

## Capability evolution model

Nine capabilities are certified: attention, working memory, reasoning, executive,
prediction, metacognition, learning, calibration, self-improvement — each on the
NASCENT→DEVELOPING→PROFICIENT→MATURE→OPTIMIZING scale. Certification is versioned;
gaps to the target maturity generate proposals; proposals are recommendations for
Learning (capability use), the Executive (review), and humans (architecture/autonomy).

## Files

| File | Component |
|---|---|
| `contracts.py` | Pure ABI: maturity/trend/limitation/proposal/roadmap value objects, review port. No sibling imports. |
| `evidence.py` | Long-term Development Evidence Aggregator (cumulative Ledger + read-only State). |
| `maturity.py` | Capability Maturity Model — per-capability, evidence-gated assessment. |
| `trends.py` | Long-Term Trend Analyzer + growth-opportunity detection. |
| `limitations.py` | Architectural Limitation Detector + Capability Gap Analysis. |
| `proposals.py` | Evolution Proposal Generator + Roadmap Generator. |
| `policy.py` | Development Policy Manager + Constitutional Evolution Protection. |
| `ports.py` | Runtime review port (to the Executive, by name) + null. |
| `state_io.py` | Read-only State access + canonical watermark. |
| `recovery.py` | Checkpoint & recovery of history + certification versions. |
| `reports.py` | Development trace, summary, and digest builders. |
| `engine.py` | Development Engine (the pipeline controller); `CognitiveEngine` + `ExecutableEngine`. |
| `errors.py` | `DevelopmentError` and friends. |

## Tests (`tests/cognitive_development/`) — 36 tests, all green

`test_maturity_trends.py` (assessment, trends, gaps, limitations, policy/constitutional
protection) · `test_development.py` (pipeline, evidence-backed proposals, zero canonical
writes, events, runtime, determinism) · `test_versioning.py` (certification versions,
gain-slow/lose-fast, roadmap versioning, per-capability tracking) · `test_governance_audit.py`
(no forbidden proposals, proposals-only, review routing, regression fail-safe) ·
`test_recovery_concurrency.py` (checkpoint/recover, concurrency, stress) ·
`test_architecture.py` (no sibling imports, no faculty verbs, zero canonical writes,
immutable artifacts, runtime-routed).
