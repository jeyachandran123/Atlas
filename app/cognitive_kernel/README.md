# UnityWorks Cognitive Kernel Foundation

> **Phase K0 — the Cognitive Operating System kernel.** This is the execution
> environment in which every future cognitive engine will live. It performs *no*
> cognition — no reasoning, attention, planning, prediction, meta-cognition,
> learning, or development. It provides only the infrastructure those engines
> require, faithfully to the frozen constitution (Phases 0–9).

## What this is (and is not)

- **Is:** a dependency-injection container, a logical clock, the event bus
  (nervous system), the append-only cognitive ledger, execution contexts, the
  scheduler, identity, the read-only constitution registry, capability
  discovery, the engine registry, health, checkpoints, recovery, and
  observability.
- **Is not:** an application, a platform, or any cognitive engine. The six
  existing UnityWorks platforms remain untouched; they become *Faculties*
  discovered through the Capability Registry. The kernel is the *Mind*.

## Boot

```python
from app.cognitive_kernel import Bootstrapper, KernelConfig

kernel = Bootstrapper().boot(
    KernelConfig(identity_name="Atlas", identity_core={"safety_first": True})
)
# kernel.state == KernelState.RUNNING
services = kernel.services()   # the injectable KernelServices bundle
...
kernel.shutdown()              # graceful → KernelState.STOPPED
```

Boot sequence (fails safely, rolling back on any step): *load configuration →
validate constitution → initialize runtime → event bus → ledger → scheduler →
identity → capability registry → engine registry → health monitor → ready.*

## How a future engine plugs in (no kernel changes required)

An engine implements the `CognitiveEngine` contract and self-registers a
*factory* (never a concrete singleton). The kernel resolves it via DI, injects
`KernelServices`, and wires it to everything else **only through the event bus**.

```python
class WorkingMemoryEngine:                      # implements CognitiveEngine
    @property
    def metadata(self): return EngineMetadata("working_memory", depends_on=())
    def initialize(self, services): ...          # subscribe to events, etc.
    def start(self): ...
    def stop(self): ...
    def health(self): ...

kernel.register_engine(WorkingMemoryEngine().metadata, lambda s: WorkingMemoryEngine())
kernel.start_engines()   # started in dependency (topological) order
```

Engines never import or instantiate one another; they communicate by publishing
and subscribing to `CognitiveEvent`s. The kernel records all bus traffic to the
ledger automatically.

## Constitutional mapping

| Kernel component | Constitutional anchor |
|---|---|
| Event bus (nervous system) | Phase 0 C1 / Phase 2.5 broadcast; P1/P6 (engines talk only via events) |
| Append-only ledger (hash-chained) | OL4/OL6/RL8; Phase 1.5 Ch10 sealing |
| Logical clock | RL4 (logical time authoritative); Phase 2 Ch8 |
| DI container / engine registry | P1/P6/OL8 (interfaces over implementations) |
| Identity core (create-once, immutable) | Phase 1 Ch4; DeL1/ExL12/MeL12 |
| Constitution registry (read-only) | Single source of frozen law; MeL12/LeL5 (cannot be altered) |
| Checkpoint/recovery | Phase 1.5 Ch10; RL8 (deterministic replay) |
| Execution context (bounded, cancellable) | P3/P5 (bounded, proportional); P4 (observable) |
| Health/observability | P4 (everything observed) |

## Engineering guarantees

- **Deterministic:** synchronous event dispatch and a manually-drivable
  scheduler; replay reproduces state exactly.
- **No hidden/global mutable state:** all state lives behind injected services;
  the ledger is the system of record.
- **No circular dependencies:** enforced by an architecture test.
- **Append-only:** the ledger exposes no update/delete/mutate (architecture
  test).
- **Pure stdlib:** zero third-party dependencies; imports nothing from the
  existing platforms.

## Tests

```bash
# from backend/
venv/Scripts/python.exe -m pytest tests/cognitive_kernel/ -o addopts="" --noconftest -q
```

Unit + integration (`test_kernel_foundation.py`), end-to-end
(`test_bootstrap_e2e.py`), and architecture (`test_architecture.py`) — 36 tests.

## Status

`KERNEL_VERSION = "1.0.0"`. The foundation is complete and stable. Future phases
implement engines (Working Memory, Attention, Reasoning, Executive, Prediction,
Meta-Cognition, Learning, Development) that **register into** this kernel — the
kernel itself should not require redesign as they arrive, nor for future Vision,
Repository, Meeting, Voice, Robotics, Multi-Agent, or Autonomous capabilities.
