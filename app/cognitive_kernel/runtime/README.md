# UnityWorks Cognitive Runtime & Execution Pipeline

> **Implementation Phase 2.** The execution environment of the artificial mind —
> the process scheduler, execution manager, and orchestration layer. It executes
> cognitive work but performs **no cognition**. Built entirely on top of the
> Kernel Foundation (`app.cognitive_kernel`); it modifies nothing in the kernel.

## Governing constitution

Primary: **Phase 2 — `COGNITIVE_RUNTIME_ARCHITECTURE.md`** (Runtime Laws
RL1–RL8), with binding constraints from Phases 0, 1, 2.5, 5, 7. Key compliance:

| Law | How the runtime complies |
|---|---|
| RL1 continuous | Always-available manager; optional background pump; idle ≠ off |
| RL3 transactional | Validated `ExecutionStateMachine`; every transition is a recorded ledger event |
| RL4 logical time | Deterministic queue ordered by `(priority, logical-sequence)` |
| RL6 tech-independent | Depends only on kernel contracts + a runtime `ExecutableEngine` Protocol |
| RL7/P8/MeL6 | Controller exposes pause/resume/cancel/timeout/escalate — it **halts, never authorizes** cognition |
| RL8 replayable | Ledger replay + execution checkpoints + idempotency (no duplicated execution) |
| P1 mind≠faculties | Runtime coordinates registered engines; architecture tests assert zero cognition |
| P3/P5 bounded | Multi-dimensional `RuntimeBudget` enforced by the runtime, not by engines |
| P4/P12 observed | Metrics + execution-tree observability + ledger; no global mutable state |

## The execution pipeline

Every request follows one path the runtime owns (engines never bypass it):

```
submit → create context → allocate budget → resolve engine → execute →
collect events → update ledger → emit metrics → complete
```

```python
from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel.runtime import CognitiveRuntime, ExecutionRequest

kernel = Bootstrapper().boot(KernelConfig(identity_name="Atlas"))
runtime = CognitiveRuntime(kernel.services()); runtime.start()

class SumEngine:                                  # implements ExecutableEngine
    def execute(self, operation, payload, context):
        return sum(payload["xs"])

runtime.register_engine("sum", SumEngine())
h = runtime.submit(ExecutionRequest(engine="sum", operation="add", payload={"xs": [1, 2, 3]}))
runtime.drain()                                    # deterministic dispatch
assert h.result().value == 6
runtime.stop()
```

## Components (mission items 1–15)

| # | Component | Module |
|---|---|---|
| 1 | Runtime Manager | `manager.CognitiveRuntime` (init/start/stop/pause/resume/health/coordinate/diagnostics) |
| 2 | Execution Pipeline | `pipeline.ExecutionPipeline` (the 9-stage flow) |
| 3 | Execution State Machine | `state_machine.ExecutionStateMachine` (validated transitions) |
| 4 | Execution Controller | `pipeline.ExecutionController` (pause/resume/cancel/retry/timeout/escalate; nesting) |
| 5 | Budget Manager | `budget.RuntimeBudget` / `BudgetManager` (time/step/memory/tokens/tools/simulations) |
| 6 | Execution Policies | `policies.PolicyRegistry` + `ExecutionPolicy` |
| 7 | Execution Queue | `queue.ExecutionQueue` (deterministic; immediate/priority/background/deferred/periodic) |
| 8 | Engine Orchestrator | `orchestrator.EngineOrchestrator` (execution routing table) |
| 9 | Context Evolution | `execution.Execution` (parent/child hierarchy, snapshots, directional cancellation) |
| 10 | Execution Checkpoints | `recovery.ExecutionCheckpointer` (runtime knows *where* execution stopped) |
| 11 | Execution Recovery | `recovery.ExecutionRecovery` (integrity gate + ledger replay; no duplicates) |
| 12 | Runtime Metrics | `metrics.RuntimeMetrics` |
| 13 | Runtime Observability | `observability.RuntimeObservability` (execution tree, timeline, spans) |
| 14 | Runtime Health | `manager` (Healthy/Busy/Degraded/Recovering/Unavailable) |
| 15 | Runtime API (internal) | `contracts.RuntimeApi` / `ExecutableEngine` |

## Design guarantees

- **No cognition:** the runtime resolves and runs engines via `ExecutableEngine`
  and treats results as opaque (architecture test enforced).
- **Deterministic:** synchronous dispatch, logical-time ordering; `drain()`
  reproduces exactly. Optional background pump for real-time.
- **No kernel changes:** hierarchy/snapshots/cancellation are layered *around*
  the kernel's frozen `ExecutionContext`.
- **No circular dependencies; contracts are a pure ABI** (architecture tests).

## Tests

```bash
# from backend/
venv/Scripts/python.exe -m pytest tests/cognitive_runtime/ -o addopts="" --noconftest -q
```

Unit, integration/E2E, architecture, cancellation, timeout, retry,
checkpoint-resume, nested-execution, failure-recovery, concurrency, and stress —
38 tests. Future engines require only `register_engine(...)` + `submit(...)`; the
runtime needs no redesign as engines arrive.
