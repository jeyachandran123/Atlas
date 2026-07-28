# UnityWorks Cognitive State Manager

> **Implementation Phase 3 — the first true cognitive component.** It owns the
> complete lifecycle of the **Cognitive State** (store, protect, version,
> validate, restore) and performs **no cognition**. Built on the Kernel
> Foundation; it modifies neither the kernel nor the runtime.

## The boundary (why this preserves the Constitution)

The manager owns the **state**; future engines own the **behaviour**.

- **State (this manager):** the graph of cognitive objects across the ten
  Regions (Phase 1) — Identity, Goal, Attention, Belief, Prediction, Plan,
  Reflection, Learning-candidate, Executive-Decision, Percept, Evidence, WM
  references, handles — plus their versions, relationships, transactions,
  history, checkpoints, and integrity.
- **Behaviour (future engines):** *how* those objects are produced/transformed.
  The Working Memory engine chooses references (not the stored references);
  Attention computes salience (not the stored salience); Reasoning derives
  beliefs/plans; Executive governs; Learning commits. Each object's `payload`
  is **opaque** to the manager.

Every object's `payload` is treated as opaque data. The manager enforces
*structural* invariants (placement, acyclicity, referential integrity,
immutability, version monotonicity); *semantic* invariants (belief coherence,
confidence monotonicity) are **pluggable validators** engines register.

## Constitutional fidelity

| Law | Implementation |
|---|---|
| OL4 — versioned; history never lost | Every mutation → a new immutable version; full history retained |
| OL7 / CL7 / CL8 — reference, not copy | Objects reference by handle via typed relationship edges |
| RL3 — ACID transactions | Atomic, invariant-checked, lock-serialised, ledger-durable commits |
| Phase 1.5 §12.6 — OCC | `expected_version` compared at commit; conflict, never a silent lost update |
| RL8 — replayable | State reconstructable by ledger replay (events carry object snapshots) |
| DeL1 / ExL12 — Identity Core invariant | Identity objects immutable; evolve only via the gated `state:admin` path |
| Phase 1.5 Ch9 — Executive Decisions immutable | Editing refused; **supersede**-only (new linked object) |
| Phase 1 §2.2 — placement law | `TYPE_REGION` enforced: an object lives only in its constitutional Region |

## Usage (the read/write contract engines use)

```python
from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel.state import CognitiveStateManager, ObjectType, RelationshipType

kernel = Bootstrapper().boot(KernelConfig(identity_name="Atlas"))
state = CognitiveStateManager(kernel.services()); state.start()
ctx = kernel.services().new_context(security=...)

tx = state.begin_transaction(ctx)                       # ACID cognitive transaction
goal   = tx.create(ObjectType.GOAL, payload={"desc": "fix auth"}, confidence=0.4)
belief = tx.create(ObjectType.BELIEF, payload={"prop": "prod uses redis"}, confidence=0.9)
tx.link(goal, RelationshipType.DEPENDENCY, belief)
tx.commit()                                             # atomic, versioned, validated, recorded

state.get(goal)                    # current version
state.history(goal)                # all versions (OL4)
state.diff(goal, 1, 2)             # change tracking
cid = state.checkpoint()           # snapshot into the kernel CheckpointStore
state.restore(cid)                 # restoration
state.rollback(goal, 1, ctx)       # a new version with old content
state.recover()                    # rebuild from the ledger (RL8)
```

## The 25 implemented concerns

State Manager · State Repository (versioned) · Lifecycle · Versioning ·
Transactions · Snapshots · Checkpoint integration · Recovery · Validation ·
Consistency invariants · Event publishing · Change tracking · Diff engine ·
History · Merge · Rollback · Locking · Optimistic Concurrency Control ·
Integrity verification · Health · Metrics · Observability · Security ·
Serialization · Restoration.

## Tests

```bash
# from backend/
venv/Scripts/python.exe -m pytest tests/cognitive_state/ -o addopts="" --noconftest -q
```

Unit, integration, architecture, concurrency, recovery, checkpoint, rollback,
versioning, history, and stress — 32 tests. Architecture tests enforce that the
manager performs no cognition, knows nothing about any engine, and that the only
write path is a transaction. **No future engine implements its own state
management** — it reads/writes through this manager.
