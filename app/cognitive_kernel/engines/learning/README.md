# Learning Engine

> Implementation Phase 10 — the exclusive authority for durable cognitive change.
> Governing law: `docs/architecture/COGNITIVE_LEARNING_ARCHITECTURE.md` (LeL1–LeL41),
> and every prior phase. **Where implementation and Constitution disagree, the
> Constitution wins.**

## Single constitutional responsibility

Learning transforms **validated experience** into durable cognitive improvement. It
is the *only* faculty permitted to make durable cognitive changes (LeL1) — all
others propose; Learning disposes. It never reacts to a single observation: it
accumulates multi-episode evidence, validates it, measures confidence, verifies
consistency, requires constitutional authorization where appropriate, and then
performs **safe, versioned, reversible, provenance-bearing updates through the
Cognitive State Manager**.

### The firewall and the burden of proof

- **From validated experience, never raw interaction (LeL7).** Assertion and
  repetition within one episode are not evidence — the anti-poisoning firewall.
  Aggregation requires ≥ N *distinct episodes*.
- **Defaults to NO CHANGE (LeL9).** The burden of proof is on the change; a candidate
  must survive evidence sufficiency, **disconfirmation** (LeL10), a confidence floor,
  and **belief-graph consistency** (LeL12/LeL23) to be committed.
- **Never from hypothetical predictions (LeL26).** Calibration learns only from
  *reconciled, realized* outcomes — never the hypothetical forecast.
- **Reversible + versioned (LeL13/LeL21).** Every commit goes through the State
  Manager (auto-versioned) and has a defined rollback; forgetting is deprecation, not
  deletion (LeL27).
- **Provenance + confidence (LeL24).** Every learned belief carries `learned_by`, its
  episodes, and `INFLUENCE` edges to its evidence.
- **Impact-scaled governance (LeL33).** LOW learns on the automatic tier (validated,
  reversible — LeL34); MODERATE requires Executive approval; HIGH (safety/identity/
  policy) escalates to human review (LeL6/LeL17/LeL18). The constitution can never be
  learned (LeL5).
- **Auditable including rejections (LeL20).** Every examination — commit *or* rejection
  — produces an immutable learning record; the false-learning rate is measured (LeL39).

### What Learning is *not* (boundary discipline)

Learning **never** learns from one event / a hallucination / a hypothetical / without
evidence / provenance / confidence / traceability / rollback; never modifies another
engine directly; never bypasses the Runtime or State Manager; never imports a sibling
engine. It exposes no `reason`/`predict`/`attend`/`govern`/`allocate`/`decide`/
`reflect`/`forecast`/`oversee` verb — enforced by `test_architecture.py`.

## The learning pipeline (`learn`)

```
Experience              LEARNING_CANDIDATE (R9, from Reasoning) + prediction.reconciled (realized) + meta findings
  ▼
Evidence Aggregation    group by claim across DISTINCT episodes; accumulate support and opposition (LeL7)
  ▼
Validation              sufficiency · disconfirmation · confidence floor · consistency — else NO CHANGE (LeL9/LeL10/LeL23)
  ▼
Confidence Assessment   aggregate confidence, lowered by opposition
  ▼
Authorization           impact-scaled (LeL33): LOW automatic · MODERATE → Executive · HIGH → human review
  ▼
Knowledge Revision      promote/consolidate a belief through the State Manager — versioned, provenance-stamped
  ▼
Version Creation        new version; prior versions preserved (LeL21); source candidates archived (LeL27)
  ▼
Audit Trail             learning.cycle / learning.committed / learning.rolled_back events
  ▼
Learning Artifact       immutable LearningRecord (commit or rejection) with trace + digest (LeL19/LeL20)
```

## Knowledge revision & rollback model

A validated candidate promotes an existing PROPOSED belief to ACTIVE (or consolidates
a new one), stamping provenance edges and archiving the consumed candidates. The
revision records `from_version`/`to_version`. **Rollback** reverts a promotion to its
prior version via the State Manager, or deprecates (archives) a newly-created belief —
never deleting (LeL13/LeL27). Calibration rollback restores the prior model value.

## Files

| File | Component |
|---|---|
| `contracts.py` | Pure ABI: experience/candidate/revision/record value objects, authorization port. No sibling imports. |
| `experience.py` | Experience Collector — read-only inputs (R9 candidates, reconciled events, meta findings). |
| `aggregator.py` | Multi-episode Evidence Aggregator (LeL7). |
| `validation.py` | Validation Pipeline — sufficiency, disconfirmation, confidence, consistency (LeL9/LeL10/LeL23). |
| `policy.py` | Learning Policy Manager — impact classification, safe constraints (LeL33/LeL5). |
| `revision.py` | Knowledge Revision Manager — the durable, versioned, reversible write + rollback. |
| `calibration.py` | Calibration Learning from realized outcomes (LeL26). |
| `ports.py` | Runtime authorization port (to the Executive, by name) + null. |
| `state_io.py` | Read-only helpers + knowledge-integrity verification (LeL24). |
| `recovery.py` | Checkpoint & recovery of history + calibration. |
| `reports.py` | Trace, report, and long-term improvement builders. |
| `engine.py` | Learning Engine (the pipeline controller); `CognitiveEngine` + `ExecutableEngine`. |
| `errors.py` | `LearningError` and friends. |

## Tests (`tests/cognitive_learning/`) — 36 tests, all green

`test_pipeline_validation.py` (aggregation, validation gates, consistency, policy) ·
`test_learning.py` (no-change default, multi-episode commit, provenance, events,
runtime, determinism) · `test_versioning_rollback.py` (versioned updates, rollback,
calibration rollback) · `test_authorization.py` (automatic / executive / human tiers) ·
`test_audit_calibration.py` (calibration from realized outcomes, integrity,
constitution rejection, false-learning rate) · `test_recovery_concurrency.py`
(checkpoint/recover, concurrency, stress) · `test_architecture.py` (no sibling imports,
no faculty verbs, state via manager, every revision has provenance & is reversible).
