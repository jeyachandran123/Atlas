# UnityWorks Working Memory Engine

> **Implementation Phase 4 — the first true cognitive engine.** The bounded
> conscious workspace of UnityWorks. It *activates references* to cognitive
> objects (never copies), is capacity-bounded and ephemeral, and reads/writes
> only through the Cognitive State Manager. It performs no cognition — Attention
> decides what enters, Reasoning operates on it, Executive manages goals within
> it, Prediction simulates inside it. It owns none of that.

## What it is (and is not)

- **Is:** the mechanism of the conscious field — a bounded set of *references*
  (focus + periphery + binding), with ephemeral activation, that can be loaded,
  refreshed, evicted, chunked, and organised into workspaces.
- **Is not:** a store. It **never** copies Knowledge, Documents, Conversation
  history, or Cognitive State. It holds *handles* that ACTIVATE targets.

## Constitutional fidelity (Phase 2.5 §5, Phase 1 R4)

| Law | Implementation |
|---|---|
| CL8 / OL7 — references only | WM references hold a target *handle* + activation metadata; never the target's content |
| CL1 / P3 — bounded | Focus (~4) + small periphery; overflow → **deterministic eviction**, never growth |
| CL23 — chunking | Binding several refs into one chunk frees focus capacity |
| §5.6 — ephemeral & reconstructable | Activation is a computed decay (not stored per step); membership lives in R4; `reconstruct()` rebuilds WM from the State |
| §5.6 — one principal per WM | A single active workspace per cognitive thread; sharing is by broadcast |
| P12 / RL3 | All durable WM state is R4 objects committed via the State Manager (atomic, versioned, ledger-recorded) |
| PrL8 — simulation isolation | `branch_simulation` copies membership into an isolated workspace; changes never touch the base |

## Boundaries (who owns what)

| Concern | Owner |
|---|---|
| Bounded workspace mechanism (load/evict/refresh/chunk/broadcast/workspaces) | **Working Memory** |
| *What enters* WM (salience → ignition) | Attention (hook: `ignite`/`load`) |
| *Operating on* WM content | Reasoning (hook: `read_focus`, deposit products) |
| *Pinning goals / capacity policy* | Executive / Development (hooks: `pin`, `set_capacity` — gated) |
| *Simulating inside* WM | Prediction (hook: `branch_simulation`) |
| *Inspecting* WM | Meta-Cognition (hook: `inspect`) |
| *Consolidating* salient content | Learning (hook: `consolidation_candidates`) |
| Durable storage of every reference | **Cognitive State Manager** (R4) |

## Integration (never bypasses infrastructure)

- **Registers** with the Kernel (`kernel.register_engine`) — discoverable.
- **Executes** through the Runtime (`ExecutableEngine.execute`) — the
  `WorkingMemoryRuntimeApi` routes every cross-engine operation through the
  runtime pipeline.
- **Reads/writes** only through the Cognitive State Manager (R4 transactions).
- **Communicates** only through the kernel Event Bus (`working_memory.*` events).
- **Checkpoints** via the State Manager (WM lives in R4); **reconstructs** from
  persistent state.

## Usage

```python
wm = WorkingMemoryEngine(services, state_manager, WMConfig(focus_capacity=4, periphery_capacity=3))
wm.register(kernel, runtime)                 # kernel + runtime + health probe + start

ref = wm.load(goal_handle, ctx, activation=1.0)   # activate a reference (Attention hook)
wm.refresh(ref, ctx)                              # rehearse (reset decay)
wm.pin(ref, ctx)                                  # Executive pins the active goal
chunk = wm.chunk([ref_a, ref_b], ctx)             # bind (frees focus capacity)
focus = wm.read_focus()                           # Reasoning reads the conscious content
wm.broadcast(None, ctx)                           # Global Workspace broadcast
sim = wm.branch_simulation(ws, ctx)               # Prediction: isolated simulation WM
```

## Tests

```bash
# from backend/
venv/Scripts/python.exe -m pytest tests/cognitive_working_memory/ -o addopts="" --noconftest -q
```

Unit, integration, architecture, capacity, eviction, activation, recovery,
checkpoint, concurrency, stress, nested-context, and simulation-workspace — 33
tests. Architecture tests enforce: no reasoning/attention/learning/prediction/
executive, references-only, capacity enforced, eviction deterministic, execution
through the Runtime, and state mutations through the State Manager.
