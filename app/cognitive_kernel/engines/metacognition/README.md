# Meta-Cognition Engine

> Implementation Phase 9 — the independent oversight faculty (Tier 3).
> Governing law: `docs/architecture/COGNITIVE_METACOGNITIVE_ARCHITECTURE.md` (MeL1–MeL35),
> and every prior phase (ExL/PrL/ReL/AL/CL/RL/OL/P). **Where implementation and
> Constitution disagree, the Constitution wins.**

## Single constitutional responsibility

Meta-Cognition's purpose is **not cognition — it is evaluating cognition**. It
continuously observes cognitive processes, evaluates cognitive quality, detects
failures, measures confidence calibration, supervises Executive governance,
evaluates reasoning quality, measures prediction accuracy, assesses attention
effectiveness, monitors working-memory utilization, detects constitutional
violations, and **recommends** interventions — providing transparent oversight of
the entire cognitive system. It is the exclusive authority for cognitive
self-evaluation and oversight.

**Meta-Cognition never performs the work of the faculty it evaluates** (MeL1/MeL4).

### The independence & safety boundaries

- **Verifier ≠ generator (MeL4).** A faculty that both reasons and grades its own
  reasoning cannot be trusted to catch its own errors. Meta is structurally
  independent from what it evaluates.
- **Cannot bypass the Executive (MeL2).** Every intervention *request* is routed to
  the **Executive** through the Runtime; the Executive authorizes and acts. Meta
  advises; it never governs.
- **The safe side only (MeL6).** Meta may HALT (a recoverable circuit-breaker),
  ESCALATE, FLAG, and RECOMMEND — never START, COMMIT, or AUTHORIZE. Every
  intervention is **reversible-by-design** (MeL20).
- **Grounded in traces, not introspection (MeL16).** The self-model is built from
  the **Ledger**, the **Health Monitor**, and **Runtime telemetry** — never by
  calling an engine's introspection. Meta imports no sibling engine.
- **Confidence-qualified hypotheses (MeL17/MeL18).** Every assessment carries the
  reliability of its own judgment; meta never asserts certainty about the mind.
- **Writes no canonical state (MeL9/MeL13).** Reflection artifacts live in an
  in-engine immutable repository and the Ledger — never in a canonical region.
- **Additive, non-load-bearing (MeL35).** Remove meta and reliability degrades;
  authority (Executive + safety) is untouched.

### What Meta is *not* (boundary discipline)

Meta **never** reasons, predicts, attends, governs, or learns; never modifies
canonical state; never silently changes an engine; never bypasses the Runtime or
State Manager; never imports a sibling engine. It exposes no `reason`/`predict`/
`attend`/`govern`/`allocate`/`decide`/`authorize`/`learn`/`forecast` verb — enforced
by `tests/cognitive_metacognition/test_architecture.py`.

## The meta-cognitive pipeline (`reflect`)

```
Observe Cognitive Activity     Ledger traces + Health Monitor + Runtime telemetry (read-only, MeL16)
  ▼
Collect Evidence               immutable ObservationWindow (event tallies, samples, health, metrics)
  ▼
Evaluate Performance           8 confidence-qualified assessments (reasoning/prediction/attention/WM/executive/runtime/health/performance)
  ▼
Detect Patterns                dedicated detectors: failure · drift · bias · contradiction · fatigue · miscalibration · inefficiency (MeL26)
  ▼
Assess Constitutional Compliance   always-on structural invariant checks (MeL29) → audit report
  ▼
Generate Reflection            immutable, traced ReflectionArtifact (MeL19/MeL21)
  ▼
Recommend Intervention         safe side only, Executive-routed, reversible (MeL2/MeL6/MeL20)
  ▼
Submit Runtime Intervention Request   (opt-in) to the Executive, by name
  ▼
Record Reflection Artifact     in-engine repository + history (no canonical write)
  ▼
Publish Audit Events           metacognition.reflection / .audit / .finding / .intervention (MeL19)
```

## Intervention model

Meta may recommend **HALT / RESUME / ESCALATE / additional reasoning / additional
prediction / attention rebias / executive review** — and never performs them. Every
recommendation is routed to the **Executive** through the Runtime (`INTERVENTION_ROUTES`),
is reversible, and is recorded. Constitutional violations recruit a circuit-breaker
HALT plus human ESCALATE (MeL8/MeL31). `FLAG` is record-only.

## Files

| File | Component |
|---|---|
| `contracts.py` | Pure ABI: window/assessment/finding/artifact value objects, intervention routing, ports. No sibling imports. |
| `observation.py` | Cognitive Observation Manager — evidence from Ledger + Health + Runtime (read-only, MeL16). |
| `assessors.py` | Per-faculty quality/health/performance assessments (confidence-qualified). |
| `detectors.py` | Dedicated detectors: failure/drift/bias/contradiction/fatigue/miscalibration/inefficiency (MeL26). |
| `compliance.py` | Constitutional Compliance Monitor — always-on structural invariant checks (MeL29). |
| `recommend.py` | Intervention Recommendation Engine — safe side, Executive-routed, reversible (MeL6). |
| `reports.py` | Reflection trace, summary, governance report, digest (MeL21). |
| `ports.py` | Runtime intervention port (to the Executive, by name) + null. |
| `state_io.py` | **Read-only** State access + canonical watermark. |
| `recovery.py` | Checkpoint & deterministic recovery of reflection history. |
| `engine.py` | Meta-Cognition Engine (the oversight controller); `CognitiveEngine` + `ExecutableEngine`. |
| `errors.py` | `MetaError` and friends. |

## Tests (`tests/cognitive_metacognition/`) — 46 tests, all green

`test_assessors_detectors.py` (assessors, all detectors, compliance monitor,
recommendation mapping) · `test_reflection.py` (artifact/trace/repository/history/
events/runtime, zero canonical writes) · `test_oversight.py` (per-faculty hooks,
governance/learning/development reports) · `test_intervention.py` (Executive-routed,
observable, reversible, auto-request) · `test_constitutional_audit.py` (violation
detection, confidence-qualified) · `test_recovery_concurrency.py` (checkpoint/recover,
concurrency, stress) · `test_architecture.py` (no sibling imports, no faculty verbs,
zero canonical writes, every intervention Executive-routed & reversible).
