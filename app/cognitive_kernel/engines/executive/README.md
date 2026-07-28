# Executive Engine

> Implementation Phase 7 — the governance authority of the Cognitive OS.
> Governing law: `docs/architecture/COGNITIVE_EXECUTIVE_ARCHITECTURE.md` (ExL1–ExL30),
> the Reasoning faculty (ReL1–ReL14), Attention (AL1–AL17), the Global Workspace
> (CL1–CL27), and the constitutional infrastructure (Kernel, Runtime, State Manager,
> Working Memory). **Where implementation and Constitution disagree, the Constitution wins.**

## Single constitutional responsibility

The Executive Engine is **Tier 2 — the governor of the object level**: it decides
*what should happen, when, why, with which resources, under which policy*. It
governs by **standing policy, bounded resource allocation, and exception-handling**
(subsidiarity, Norman–Shallice) — engaging its own scarce attention only for the
non-routine, cross-cutting, high-stakes, and strategic, while the local governors
(attention competition, reasoning economy, runtime scheduler) handle the routine.
It is the exclusive constitutional authority to **own goals, allocate cognitive
resource, and authorize action** (ExL1/ExL2).

It is a **mechanism, not a homunculus** (Appendix B): decomposed into fifteen
inspectable components, grounded in reasoning's output (no magic decider, ExL10),
reading no privileged channel (ExL11), bounded like every faculty (ExL15), and
itself governable from above by a future Meta-Cognition tier (ExL30).

### What the Executive is *not* (boundary discipline)

The Executive **never**:

- performs reasoning, attention, prediction, or learning — it *coordinates* those
  faculties and *uses* their products;
- selects consciousness (it *biases* attention through the override channel);
- modifies Knowledge, bypasses the Runtime, bypasses the State Manager, or calls a
  sibling engine directly.

It exposes no `reason` / `attend` / `select` / `ignite` / `predict` / `learn` /
`reflect` verb. Coordination flows **only through the Runtime, addressed by engine
name** — the executive imports no sibling engine at all. These boundaries are
enforced mechanically by `tests/cognitive_executive/test_architecture.py`.

## How it honours the infrastructure

| Constitutional rule | Mechanism |
|---|---|
| Register with the Kernel | `register(kernel, runtime)` → `kernel.register_engine(self)` |
| Execute through the Runtime | implements `ExecutableEngine.execute("govern", …)` |
| Coordinate faculties only through public contracts + Runtime (ExL8) | `RuntimeReasoningPort` / `RuntimeAttentionPort` submit `ExecutionRequest`s **by name** — never an engine reference |
| Consume Reasoning outputs only through public contracts | governs a `ReasoningProposal` value object; decisions grounded in its calibrated confidence (ExL10) |
| Influence Attention only through public bias interfaces | routes `set_executive_bias` via the runtime (Phase 3 Ch6), bounded by safety |
| Request Prediction only through Prediction hooks | `PredictionRiskPort` (null until wired); the executive never predicts |
| Read/write State only via the State Manager | goals → `GOAL` (R2); rulings → immutable `EXECUTIVE_DECISION` (R9) |
| Publish executive events + metrics | every act audited through the Audit Layer → ledger (ExL5) |
| Checkpoint + deterministic recovery | governance config sealed via the kernel `CheckpointStore` (ExL27) |

## The governance cycle (`govern`)

```
Reasoning Proposal (confidence, stakes, reversibility, safety/identity flags)
  │  Policy Evaluation      constitutional enforcement first — Safety/Identity absolute (ExL7/ExL12/ExL37)
  ▼
Goal Evaluation            relate to a portfolio goal (owner, active?)
  ▼
Priority Assessment        global recomputed ordering (Priority Manager)
  ▼
Risk Assessment Request    (if high-stakes / irreversible) via the Prediction/Risk hook
  ▼
Executive Decision         risk-scaled autonomy threshold on reasoning's confidence (ExL13/ExL6)
  │   APPROVE · REJECT · ASK_USER · ESCALATE · WAIT  (the taxonomy, Ch4)
  ▼
Action Authorization       APPROVE ⇒ authorized
  ▼
Cognitive State Update     immutable EXECUTIVE_DECISION written to R9 (ExL3/ExL26)
  ▼
Runtime Coordination       best-effort directives via ports (attention bias, reasoning strategy) — degrade gracefully
  ▼
Events + Audit Trail       every act recorded immutably (ExL5)
```

### The governance triad (ExL24)

- **Policy** — standing legislation the local governors follow without the
  executive present. Versioned, inherited (narrow-only), **precedence-ordered**
  (Safety > Identity > privacy > operational > convenience). Safety/Identity DENY
  is **absolute and non-overridable**. Constitutional policies are seeded at
  construction (`policy.py`).
- **Allocation** — a single **bounded** global allocator over the local economies
  (`resources.py`): allocation, reservation, starvation aging (ExL17), priority
  inversion + inheritance (ExL18), never over-committing the finite total (ExL4).
- **Decision** — case-by-case governance rulings, each an immutable
  `EXECUTIVE_DECISION` with alternatives, rationale, confidence, and authority.

### Goal portfolio (Ch3)

The executive does not pursue goals; it *manages a portfolio*: a bounded active
working set (ExL15), most suspended/dormant, the impossible **abandoned** (audited,
resurrectable — ExL19), completion **declared on evaluated conditions** (ExL20),
periodically reviewed against neglect (ExL21). Every goal has exactly one
accountable owner (ExL2).

### Conflict ladder (Ch6, ExL23)

Detected conflicts are resolved by a fixed, auditable ladder — **Safety/Identity
(absolute) → Priority → Confidence → Authority → Compromise → Override → Escalate**
— never by silent last-write-wins. Safety and Identity dominate lexicographically.

### Safety subordination (ExL7/ExL13/ExL14)

No decision, override, or policy may violate a safety/identity-core constraint.
The risk-scaled autonomy threshold rises with stakes and irreversibility; below it,
the executive **Asks the User / Escalates** — its most important competence is
knowing when *not* to decide alone.

## Files (the fifteen components, decomposed — the anti-homunculus commitment)

| File | Component(s) |
|---|---|
| `contracts.py` | Pure ABI: governance enums, value objects, control ports. No sibling imports. |
| `security.py` | Authority gate (ExL1) — privileged acts require governance authority. |
| `policy.py` | Cognitive Policy Manager + evaluation + constitutional enforcement (Ch7). |
| `goals.py` | Goal Governor — portfolio, hierarchy, lifecycle, dependencies, completion (Ch3). |
| `priority.py` | Priority Manager — the global recomputed ordering. |
| `resources.py` | Resource Governor — the central bank; allocation, inversion, boundedness (Ch5). |
| `conflict.py` | Conflict Resolver — the fixed ladder (Ch6). |
| `decision.py` | Decision Arbiter — approve/reject/escalate, risk-scaled threshold (Ch4). |
| `strategy.py` | Strategy Governor — reasoning/attention directives, planning coordination. |
| `ports.py` | Runtime-routed control ports + null Prediction/Risk port. |
| `audit.py` | Executive Audit Layer — every act recorded (ExL5), independent of control (ExL25). |
| `state_io.py` | Immutable Executive Decisions + the decision audit trail (R9). |
| `recovery.py` | Executive Checkpoint & Recovery of governance config (ExL27). |
| `engine.py` | Executive Controller — the governance cycle; `CognitiveEngine` + `ExecutableEngine`. |
| `errors.py` | `ExecutiveError` and friends. |

## Tests (`tests/cognitive_executive/`) — 52 tests, all green

`test_governors.py` (policy/priority/resources/conflict/decision units) ·
`test_goals.py` (ownership, hierarchy, lifecycle, dependencies, completion,
delegation, abandonment, bounded working set) · `test_decision_pipeline.py`
(approve/reject/escalate/ask-user, immutable R9 decisions, audit, events, runtime,
determinism) · `test_interventions.py` (interrupt/pause/resume/escalate/allocation/
inversion) · `test_recovery_concurrency.py` (governance checkpoint+recover, state
checkpoint, concurrency, stress) · `test_integration_wired.py` (directives routed
via the runtime, governing a real reasoning proposal, dashboard) ·
`test_architecture.py` (no sibling imports, no faculty verbs, runtime-routed
coordination, state via manager, constitutional enforcement).
