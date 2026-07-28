# Cognitive Intelligence Platform (CIP)

### The Executive Intelligence Layer of UnityWorks AI

| | |
|---|---|
| **Status** | Architecture Blueprint — Phase 0 (Design Only) |
| **Scope** | Architecture only. No implementation. No modification of existing platforms. |
| **Audience** | AI researchers, principal engineers, CTOs |
| **Intent** | Permanent architectural foundation for every future cognitive capability in UnityWorks |
| **Version** | 1.0 (foundational) |

> This document specifies *what the Cognitive Intelligence Platform is, why it exists, and the
> invariants it must never violate.* It deliberately does not specify implementation. Where it
> references existing UnityWorks systems, it does so to define **boundaries**, never to redesign them.

---

## 0. Orientation — Mapping to the Existing System

UnityWorks already runs a mature AI Operating System. In this codebase (Atlas) the six stable
platforms correspond to concrete, production modules. The CIP must treat these as **fixed faculties**
and orchestrate them through their existing contracts.

| UnityWorks Platform | Role (faculty) | Where it lives today (Atlas) |
|---|---|---|
| **Document Platform** | Ingest, parse, chunk, represent source material | `app/indexing/` (scanner, AST chunkers, embedder), `app/workers/` |
| **Knowledge Platform** | Durable structured facts & long-term records | `app/memory/long_term.py`, PostgreSQL fact store, consolidator |
| **Semantic Intelligence Platform** | Embeddings, vector search, similarity, ranking | `app/retrieval/` (MMR), `app/vector_store/` (ChromaDB) |
| **Conversation Platform** | Turns, session buffer, streaming, message history | `app/api/v1/chat/`, `app/memory/session.py` (Redis, SSE) |
| **Generation Platform** | LLM inference, prompt assembly, code/text generation, adversarial review | `app/agents/` (CodingAgent, ReviewAgent), `app/prompts/` |
| **Workspace Platform** | Effects on the world: files, git, terminal, tools | `app/agents/tools/` (read/write, search, git, terminal) |

**The critical observation.** Today these faculties are wired together by a *fixed pipeline* — the
LangGraph orchestrator (`route_intent → load_memory → retrieve_context → plan_tools → tool loop →
review loop → finalise`). That pipeline is excellent, but it is **reactive and request-scoped**: it
has no durable intent, no bounded active workspace, no self-monitoring, and it learns only by an async
fact-consolidator. The pipeline *is* a hard-coded cognitive cycle.

The Cognitive Intelligence Platform replaces the *hard-coding of that cycle* with a **persistent,
stateful, self-directed mind** — while continuing to call the same six faculties, unchanged, through
clean interfaces.

```
                         ┌───────────────────────────────────────────┐
   THE MIND (new)        │        Cognitive Intelligence Platform      │
                         │   goals · attention · working memory ·      │
                         │   deliberation · planning · reflection ·     │
                         │   learning · metacognition                  │
                         └───────────────────────────────────────────┘
                                 │  (abstract cognitive ports)  ▲
                                 ▼                              │
   THE FACULTIES         ┌──────┬──────┬──────────┬──────┬──────┬──────┐
   (existing, stable)    │ Doc  │Know- │ Semantic │Conv. │ Gen. │Work- │
                         │      │ledge │          │      │      │space │
                         └──────┴──────┴──────────┴──────┴──────┴──────┘
```

---

## 1. Cognitive Philosophy

### 1.1 Purpose

The CIP exists to give UnityWorks a **mind**: a persistent, goal-directed cognitive process that
decides *what to think about, how much to think, what to remember, what to do, whether it worked, and
what to learn* — and does so continuously, across time and across modalities, rather than one request
at a time.

The six existing platforms are **specialized faculties**. Each is superb at one thing and each is, by
design, *reactive and stateless-per-request*. What UnityWorks lacks is not a better faculty — it is
the **executive coordination** that turns a collection of faculties into coherent, intentional
behavior. That coordination is the CIP.

### 1.2 Why it exists (the gap it closes)

A faculty answers a bounded question:

- *Semantic:* "Which chunks are most similar to this query?"
- *Generation:* "Given this prompt, what is the next best token sequence?"
- *Workspace:* "Apply this diff / run this command."

None of them answers the **executive questions**:

- What am I *trying to achieve* — now, and over the next hour, and across this project?
- Given everything happening, what deserves my attention *right now*?
- What do I *already believe*, and does this new information change it?
- How hard should I think about this, and using which strategy?
- Did my last action move me toward my goal, or away from it?
- What should I *permanently learn* from this so I am better next time?

A system that never answers these is a very capable reflex arc. Answering them is what makes a
**mind**. That is the CIP's entire reason to exist.

### 1.3 Why it is separate from Conversation, Knowledge, Semantic, and Workspace

Three independent forces demand separation:

1. **Different temporal contract.** Faculties are request-scoped and (ideally) stateless — this is
   what makes them scalable, cacheable, and replaceable. Cognition is the opposite: it is
   *stateful and continuous by definition*. Fusing the two would either make faculties un-scalable or
   make cognition amnesiac. They must live on opposite sides of a boundary.

2. **Different axis of change.** Faculties change along *capability* axes (a better embedder, a faster
   LLM, a new tool). Cognition changes along *behavioral* axes (better goals, better judgment, better
   learning). Coupling them means every model upgrade risks the mind, and every behavior change risks
   the infrastructure. Conway's law says: keep them as separate systems so separate teams can evolve
   them independently.

3. **Different correctness criteria.** A faculty is correct if it returns a good answer to *its* narrow
   question. Cognition is correct if it makes *good decisions over time*. These require different tests,
   different observability, and different failure handling. The CIP owns judgment; the platforms own
   competence.

> **One-sentence statement of the boundary:**
> *The platforms know **how** to perceive, recall, generate, and act. The Cognitive Platform decides
> **what, when, why, how much, and whether it worked** — and never re-implements a faculty.*

### 1.4 What the CIP is explicitly NOT (anti-goals)

| It is not a… | Because… |
|---|---|
| **Chatbot architecture** | A chatbot is turn-in/turn-out with no durable intent. The CIP maintains goals, attention, and beliefs that outlive any single turn or even any single conversation, and it reacts to non-conversational events (a repo push, an email, a meeting) with equal standing. |
| **Agent framework** | An agent framework is a *library* for wiring an LLM to tools in a loop. The CIP treats "run an agent loop" as one *implementation option* behind its reasoning/action ports. Frameworks have no working memory model, no attention economy, no metacognition, and no learning loop. Those are the CIP. |
| **Workflow engine** | A workflow engine executes a *predefined* DAG. In the CIP there is no static graph of steps; the sequence of cognition **emerges** from the current goals, salience, and metacognitive control. The workflow is an output of cognition, not its definition. |

---

## 2. Cognitive Lifecycle — The Cognitive Cycle

Cognition in the CIP is a continuous loop — the **Cognitive Cycle** — not a linear pipeline. One pass
through the cycle is a *cognitive step*; a bounded sequence of steps working toward a goal is a
*cognitive episode*. The **Metacognitive Supervisor** runs orthogonally and can intervene at any phase.

```
              ┌──────────────────────── METACOGNITIVE SUPERVISION ───────────────────────┐
              │  monitors confidence · coherence · progress · budgets · safety · drift    │
              │  can: allocate deliberation · switch strategy · pause · re-plan · escalate │
              └───────────────────────────────────────────────────────────────────────────┘
                    ▲        ▲         ▲          ▲         ▲         ▲         ▲
   ┌──────────┐  ┌──┴───┐ ┌──┴───┐ ┌───┴────┐ ┌───┴────┐ ┌──┴───┐ ┌───┴───┐ ┌──┴────┐
   │ PERCEIVE │→ │APPRAISE│→│ORIENT │→│ RECALL │→│COMPREHEND│→│DELIBERATE│→│ DECIDE │→│  ACT  │
   │          │  │(frame) │ │(attend)│ │(activate│ │(update  │ │(reason) │ │ (plan) │ │(invoke │
   │  intake  │  │salience│ │ gate) │ │ memory) │ │ beliefs)│ │         │ │        │ │faculty)│
   └──────────┘  └────────┘ └───────┘ └────────┘ └─────────┘ └─────────┘ └────────┘ └───┬────┘
        ▲                                                                                 │
        │                                                                                 ▼
        │                          ┌─────────┐   ┌──────────┐   ┌─────────┐          ┌─────────┐
        └──────────────────────────│  LEARN  │←──│ REFLECT  │←──│ OBSERVE │←─────────│ outcome │
             persist & consolidate  │(durable │   │(evaluate │   │(sense    │          │ (effect │
                                     │ change) │   │ decision)│   │ result)  │          │  world) │
                                     └─────────┘   └──────────┘   └─────────┘          └─────────┘
```

**The ten phases:**

1. **Perceive.** Modality-agnostic intake. A chat turn, a git push, an email, a meeting transcript, a
   scheduled trigger — each becomes a normalized **percept**. (Uses the Conversation Platform and future
   perception sources; the CIP itself does not parse raw modalities.)
2. **Appraise (Frame).** Assess each percept for salience: is it relevant to a goal? surprising?
   urgent? risky? Produces a *salience-scored* view of the situation.
3. **Orient (Attend).** The Attention Controller runs a competition; the winning coalition of percepts
   + goals is **broadcast** into Working Memory. Everything else is explicitly deferred or ignored (and
   *why* is recorded).
4. **Recall (Activate).** Given the contents of Working Memory and the active goal, the Recall
   Orchestrator formulates queries and *activates* relevant long-term memory from the Knowledge,
   Semantic, and Document platforms — pulling **pointers + activation state**, not copies.
5. **Comprehend (Update beliefs).** Fuse percepts + activated memory into the **World Model**: revise
   beliefs, resolve or flag contradictions, update confidence, note prediction errors.
6. **Deliberate (Reason).** The Reasoning Supervisor selects a strategy proportional to stakes (fast
   heuristic vs. slow deliberate; single-pass vs. tree/debate) and invokes the Generation Platform to
   actually reason. Produces hypotheses / candidate answers with confidence.
7. **Decide (Plan).** The Executive Planner converts intention + current state into an action plan:
   which faculties/tools to invoke, in what order, with what guards and expected outcomes.
8. **Act (Invoke faculty).** Execute the plan through the Workspace / Generation / other action ports,
   through a controlled **effect boundary** (dry-run, approval, and reversibility semantics).
9. **Observe.** Sense the outcome of the action (tests passed? PR merged? user corrected me?). Compare
   to the *expected* outcome recorded at Decide — the delta is the learning signal.
10. **Reflect → Learn.** Evaluate the decision (Reflection Engine); convert validated lessons into
    durable improvements (Learning System) — new beliefs, new memories, tuned strategies, tuned
    attention weights. Persist the updated Cognitive State and consolidate Working Memory.

Then the cycle repeats — with a mind that is now slightly different than it was one step ago. That
*difference across steps* is the thing no faculty and no pipeline provides.

---

## 3. Cognitive Principles (Immutable Invariants)

These are architectural laws. Every future cognitive component **must** satisfy all of them; a design
that violates one is rejected regardless of how capable it is.

| # | Principle | Statement | Consequence if violated |
|---|---|---|---|
| **P1** | **Mind ≠ Faculties** | The CIP never re-implements a faculty. No embeddings, no vector indexes, no LLM calls of its own, no document store. It *orchestrates* the six platforms through interfaces. | The CIP becomes a monolith; platforms can't evolve independently. |
| **P2** | **State is first-class and persistent** | Every cognitive episode reads and writes durable Cognitive State. Cognition is stateful across time by definition. | The system is amnesiac; "goals over time" is impossible. |
| **P3** | **Bounded Working Memory** | Active reasoning operates over a strictly capacity-limited workspace. Nothing reasons over "everything." Attention gates entry. | Context blows up, cost explodes, focus is lost, latency is unbounded. |
| **P4** | **Everything is observed; effects are reversible-by-design** | Every cognitive act is appended to the Cognitive Ledger. Every world-effect passes a controlled boundary (dry-run / approve / rollback). | No reflection, no learning, no audit, no safety. |
| **P5** | **Deliberation is proportional** | Cognitive effort scales with stakes and uncertainty. Trivial things get System-1 treatment; risky/ambiguous things get System-2. Metacognition sets the dial. | Either wasteful over-thinking or reckless under-thinking. |
| **P6** | **Interfaces over implementations** | Every cognitive component sits behind a contract and is independently replaceable. No component reaches into another's internals. | The platform ossifies; nothing can be swapped. |
| **P7** | **Goals are explicit and durable** | The system always holds an inspectable intentional state. Behavior is goal-directed, not turn-reactive. | Regresses to a chatbot. |
| **P8** | **Metacognition can preempt** | The supervisor may halt, redirect, throttle, or escalate *any* process at any phase. No unbounded loops. | Runaway cognition, infinite loops, drift. |
| **P9** | **Learning must not corrupt** | Every learned change is versioned, validated against verified knowledge, monitored for regression, and reversible. High-impact changes require human review. | The mind silently degrades or is poisoned. |
| **P10** | **Human-in-the-loop is a first-class control path** | Escalation, approval, and correction are architected primitives, not bolt-ons. | Autonomy without accountability. |
| **P11** | **Cognition is modality-agnostic** | The core operates on *abstract percepts* and *abstract capabilities*. New modalities plug in at the edges without touching the core. | Every new sense/actuator forces a redesign. |
| **P12** | **No hidden state** | All durable cognitive state lives in the Cognitive State store / Ledger. Components hold no private durable memory. | No recovery, no audit, no migration, no explainability. |

---

## 4. Platform Boundaries — Responsibilities Matrix

The boundary is drawn along a single question: **judgment vs. competence.** The CIP owns judgment over
time. The platforms own competence in the moment.

| Concern | Owned by CIP (the mind) | Owned by existing platform (the faculty) |
|---|---|---|
| **Intent / goals over time** | ✅ Goal Manager | — |
| **What to attend to** | ✅ Attention Controller | — |
| **Active working set** | ✅ Working Memory | — (Conversation holds *raw* session buffer only) |
| **Beliefs about user/project/self** | ✅ World Model / Cognitive State | — (Knowledge holds *objective* facts) |
| **When & how hard to reason** | ✅ Reasoning Supervisor | — |
| **Actual token generation** | — | ✅ Generation Platform |
| **What to recall, and why** | ✅ Recall Orchestrator (query formulation, fusion, activation) | — |
| **How to search / rank / embed** | — | ✅ Semantic Platform |
| **Durable facts & records** | — (CIP *writes through* it) | ✅ Knowledge Platform |
| **Document parsing / chunking** | — | ✅ Document Platform |
| **Turn management / streaming** | — | ✅ Conversation Platform |
| **Executing effects on the world** | ✅ decides *whether/what/guards* | ✅ Workspace executes the effect |
| **Self-evaluation of decisions** | ✅ Reflection Engine | — |
| **Turning experience into durable improvement** | ✅ Learning System (writes through Knowledge) | ✅ Knowledge stores the result |
| **Supervising the whole process** | ✅ Metacognitive Supervisor | — |

**Two boundaries that are easy to get wrong — stated explicitly:**

- **World Model (CIP) vs. Knowledge Platform.** The Knowledge Platform stores *objective, durable
  facts* ("the repo uses the Repository pattern," importance 0.9). The World Model stores the *mind's
  subjective, revisable beliefs and their confidence and provenance* ("I believe this user prefers terse
  answers; confidence 0.6; based on 2 corrections"). Beliefs are *derived from* knowledge + experience
  and are *cheap to revise*; knowledge is expensive ground truth. When a belief is validated and
  durable, Learning promotes it into the Knowledge Platform. They are never merged.

- **Working Memory (CIP) vs. Session Memory (Conversation).** Session memory is the *raw* last-N
  messages (Redis, 24h TTL). Working Memory is *interpreted, structured, goal-relevant* content — the
  current goal, the salient facts, the active hypotheses, the plan — which may draw on *many*
  conversations and on non-conversational events, and which persists as long as the goal does. Session
  memory is a transcript; Working Memory is a train of thought.

---

## 5. Cognitive Components

The CIP is a **cell of independently replaceable components** (P6) coordinated by a small core. Every
component is listed below with *why it exists* and *how it interacts*.

### 5.1 The Core

**C0 — Cognitive Kernel (Cycle Engine).**
*Why:* Something must run the Cognitive Cycle (§2), advance episodes, checkpoint state, and mediate
between components. *Interacts:* drives every other component; owns the step/episode lifecycle; reads
and writes Cognitive State; emits every transition to the Ledger. It is deliberately *thin* — it
sequences and schedules; it holds no judgment of its own.

**C1 — Cognitive Bus (Global Workspace / Broadcast Fabric).**
*Why:* Components must communicate without knowing each other's internals (P6). Implements the
Global-Workspace idea: the winning coalition of Working-Memory content is *broadcast* so any component
can react. Also carries metacognitive control signals. *Interacts:* every component publishes/subscribes
here; the port adapters (§13) sit on its edge.

**C2 — Cognitive Ledger (Episodic Trace).**
*Why:* P4 and P12 require that *everything* cognitive is recorded — percepts, attention decisions,
recalled items, plans, actions, expected vs. actual outcomes. This is the substrate for reflection,
learning, recovery (event-sourced replay), audit, and explainability. *Interacts:* written by the
Kernel and every component; read by Reflection, Learning, Metacognition, and recovery.

### 5.2 Perception & Intention

**C3 — Perceptor (Situation Framing).**
*Why:* Cognition needs a uniform notion of "something happened," independent of modality (P11). Turns
raw inputs into normalized, typed **percepts** with provenance and initial salience features. *Interacts:*
consumes from the Perception ports (Conversation today; Vision/Voice/Email/Meeting/Repository/Automation
later); feeds Appraise/Orient.

**C4 — Goal Manager (Intentional System).**
*Why:* P7 — the system must hold explicit, durable goals. Maintains a **goal graph**: goals, sub-goals,
priorities, commitments, constraints, deadlines, and satisfaction/abandonment conditions. Handles goal
arrival, decomposition, arbitration, and closure. *Interacts:* every phase consults active goals;
Attention weights toward them; Planning derives actions from them; Reflection judges against them.

### 5.3 Attention & Memory

**C5 — Attention Controller (Salience Engine).**
*Why:* P3 — a bounded mind must choose. Scores candidate percepts/memories/goals and runs the workspace
competition that decides what enters Working Memory and what is inhibited. *Interacts:* gates the
entrance to Working Memory; can trigger interrupts (bottom-up preemption) via Metacognition.

**C6 — Working Memory (Cognitive Blackboard).**
*Why:* Deliberation needs a small, fast, active workspace holding the current train of thought (§7).
*Interacts:* populated by Attention + Recall; mutated by Deliberation; checkpointed to Cognitive State;
consolidated by Learning on episode close.

**C7 — Recall Orchestrator (Memory Activation).**
*Why:* Long-term memory must be *activated into* Working Memory on demand, without duplication (§9,
P1). Formulates recall queries from cognitive context (not the raw message), performs spreading
activation, fuses results across faculties, and injects a bounded, ranked, provenance-tagged set.
*Interacts:* calls the Recall port (→ Knowledge + Semantic + Document); feeds Working Memory; writes
back nothing itself (Learning owns writes).

### 5.4 Reasoning, Planning & Action

**C8 — World Model (Belief State).**
*Why:* Comprehension must accumulate into a coherent, revisable model of user/project/environment/self
(§6). *Interacts:* updated at Comprehend and Observe; read by Deliberation and Planning; its confidence
& contradictions are watched by Metacognition.

**C9 — Reasoning Supervisor (Deliberation Manager).**
*Why:* P5 — effort must be proportional and strategy must be chosen, not fixed. Governs *how much* to
think and *which* strategy (heuristic, chain, tree, self-debate, tool-augmented). *Interacts:* invokes
the Generation port to actually reason; reports confidence to Metacognition; strategy choice is tuned by
Learning (procedural policy).

**C10 — Executive Planner (Action System).**
*Why:* Intentions must become sequenced, guarded actions with *expected outcomes* (so Observe can
measure them). *Interacts:* reads goals + World Model; emits plans to the Act phase; every action is
paired with an expectation recorded in the Ledger.

**C11 — Effect Boundary (Actuation Gate).**
*Why:* P4/P10 — world-changing actions need dry-run, approval, and rollback semantics in one place.
*Interacts:* the single chokepoint between Planner and the Action port (→ Workspace / Generation);
enforces reversibility and human-approval policies.

### 5.5 The Executive (Higher-Order)

**C12 — Metacognitive Supervisor (Executive Cognitive System).**
*Why:* P8 — a mind needs a model of *its own* cognition that can regulate it (§10). *Interacts:* runs
on its own always-on loop; reads Ledger + Working Memory + confidence signals; issues control signals
on the Bus (allocate deliberation, switch strategy, pause, re-plan, escalate).

**C13 — Reflection Engine.**
*Why:* Decisions must be evaluated so the system can improve (§11). *Interacts:* replays episodes from
the Ledger; compares outcome vs. expectation; produces structured critiques + candidate improvements
(does not mutate anything directly).

**C14 — Learning & Adaptation System.**
*Why:* Reflections must become durable, validated, reversible improvements (§12, P9). *Interacts:*
consumes candidate improvements; validates against verified knowledge; commits versioned changes to the
World Model, the Strategy/Policy store, and (via write-through) the Knowledge Platform; monitors for
regression.

**C15 — Strategy / Policy Store (Procedural Memory).**
*Why:* "How to think and act well in situation X" must be stored, versioned, and reused. *Interacts:*
read by the Reasoning Supervisor and Attention Controller; written only by Learning; versioned and
rollback-able.

### 5.6 Component Interaction Summary

```
 Perceptor ─┐                                    ┌─► Effect Boundary ─► [Workspace/Gen]
            ▼                                     │
      Attention ─► Working Memory ◄── Recall ◄────┼── [Knowledge/Semantic/Doc]
            ▲            │  ▲                      │
   Goal Manager         │  └── World Model ◄───────┤
            ▲            ▼                          │
            │      Reasoning Supervisor ─► Executive Planner
            │            │        (uses [Generation])
            │            ▼
            └──── Strategy/Policy Store
                         ▲
   ┌─────────────────────┴──────────────────────────────────────────┐
   │ Metacognitive Supervisor  ◄─ Cognitive Ledger ◄─ (all of above)  │
   │        │                        ▲                                 │
   │        └─► control signals      └── Reflection ─► Learning ───────┘
   └──────────────────────────────────────────────────────────────────┘
```

---

## 6. Cognitive State

### 6.1 Definition

**Cognitive State is the persistent, structured representation of the system's mind for a given
cognitive context** (scoped per user × org × workspace × cognitive-instance). It is the answer to "who
am I, what am I trying to do, what do I believe, and how am I doing" at any moment — and it survives
across turns, conversations, sessions, and restarts.

It is **subjective and revisable** (unlike Knowledge, which is objective and durable) and it is the
*backing store* for Working Memory (which is the small active subset).

### 6.2 What belongs inside it (six layers)

| Layer | Contents | Example |
|---|---|---|
| **Intentional** | The goal graph: active goals, sub-goals, priorities, commitments, constraints, deadlines, satisfaction/abandonment conditions | "Goal: ship auth fix by Fri; sub-goal: reproduce the Redis-down failure" |
| **Situational (World Model)** | Confidence-weighted, provenance-tracked beliefs about user, project, environment, task | "Belief: prod uses Redis for auth cache; conf 0.9; src: ledger#4471" |
| **Self** | Current mode, confidence, cognitive load, recent performance, known limitations, active strategies | "Mode: deliberate; load: high; recent accuracy on tests: 0.72" |
| **Attention** | Current focus, salience map, what is being ignored and *why* | "Focus: repro; ignoring: docs request (deferred, low urgency)" |
| **Working Memory snapshot** | The checkpointed active episode (volatile, but recoverable) | the current train of thought |
| **Episodic pointers** | *References* into the Ledger and into Knowledge/Semantic long-term stores — never copies (P1) | ledger episode ids; knowledge fact ids; doc chunk ids |

### 6.3 How it evolves

- **Comprehend** updates beliefs from percepts + recall, using explicit revision rules (new evidence
  adjusts confidence; contradictions are flagged for Metacognition, not silently overwritten).
- **Observe** updates the Self layer (performance, calibration) and beliefs (did the world behave as
  predicted?).
- **Reflect → Learn** commits validated, versioned changes (P9).
- **Goal Manager** mutates the Intentional layer on goal arrival/decomposition/closure.
- **Conflict resolution** is a named responsibility: contradictory beliefs above a threshold trigger a
  metacognitive arbitration step rather than last-write-wins.

### 6.4 How it is persisted

- **Event-sourced.** The Cognitive Ledger is the append-only source of truth: every state transition is
  an event. The current state is a *materialized projection* that can be rebuilt by replay (satisfies
  P12: recovery, audit, migration).
- **Scoped and tiered.** State is partitioned by scope — *episode* (volatile, checkpointed), *session*,
  *project*, *global/user* — each with its own consolidation and retention policy. Salient episode state
  is consolidated upward on close; the rest decays.
- **Write-through for durable knowledge.** When Learning decides a belief is durable ground truth, it
  is written *through* the Knowledge Platform; the CIP keeps only a pointer. The CIP never becomes a
  competing system of record.

---

## 7. Working Memory

### 7.1 Definition & lifecycle

Working Memory (the **Cognitive Blackboard**) is the small, fast, volatile workspace that holds the
current *train of thought* for an episode. Its lifecycle:

```
  episode open ─► populate (attention + recall) ─► mutate (deliberation) ─►
     checkpoint (to Cognitive State) ─► [decay / evict throughout] ─►
     episode close ─► consolidate salient items (Learning) ─► discard the rest
```

### 7.2 Capacity

Capacity is **deliberately bounded (P3)** — and not by tokens alone, but by **cognitive slots**: a
small number of active *items* (goals, beliefs, percepts, hypotheses, plan steps), each carrying an
**activation score**. This mirrors the cognitive-science finding that focal attention holds only a few
chunks at once, with long-term memory as the vast backing store. The token budget of the underlying LLM
is a *downstream* constraint that the slot budget keeps comfortably satisfied.

### 7.3 Update rules

- **Activation.** Items gain activation from goal-match, recency, relevance to the current focus, and
  metacognitive priority.
- **Decay.** Activation decays each cognitive step; unattended items fade.
- **Eviction.** When over slot capacity, the lowest-activation items are evicted — but *checkpointed to
  Cognitive State first*, so they can be re-recalled cheaply if they become relevant again.
- **Pinning.** The active goal and safety-critical constraints are **pinned** (never evicted while the
  goal is active).
- **Coherence.** Two highly-active contradictory items may not coexist silently; that condition raises a
  metacognitive conflict-resolution signal.

### 7.4 Expiration strategy

Three expiry mechanisms operate together: **decay** (within an episode), **consolidation** (on episode
close — salient items promoted to Cognitive State / Knowledge; the rest discarded), and **TTL** (the
checkpointed frame expires per its scope tier). This is distinct from the Conversation Platform's
24h session buffer — Working Memory can outlive it (a goal that spans days) or be far shorter (a
throwaway sub-thought).

---

## 8. Attention Model

### 8.1 The core idea

Attention is the **economy of a bounded mind**: compute, context budget, and faculty calls are scarce,
so the system must *choose*. The Attention Controller answers "what deserves cognition right now?" and,
equally important, *what to ignore and why*.

### 8.2 The salience function (multi-factor)

Each candidate (percept, memory item, or goal) is scored on:

| Factor | Question | Direction |
|---|---|---|
| **Goal relevance** | Does this advance or threaten an active goal/commitment? | ↑ |
| **Novelty / surprise** | How much does this violate the World Model's prediction (prediction error)? | ↑ |
| **Urgency** | Is it time-sensitive (deadline, live user waiting)? | ↑ |
| **Uncertainty / risk** | Are the stakes high or my confidence low? | ↑ |
| **User signal** | Explicit emphasis, correction, or priority cue? | ↑ |
| **Cost** | How expensive is attending to this? | ↓ |

### 8.3 The mechanism — top-down + bottom-up competition

- **Top-down (goal-driven):** active goals bias salience toward relevant candidates.
- **Bottom-up (stimulus-driven):** a surprising or high-risk percept can seize attention even if no
  goal points at it (e.g., a security-relevant repo event during an unrelated task).
- **Competition & broadcast:** candidates compete; the winning *coalition* is broadcast into Working
  Memory (Global Workspace). Losers are recorded as **deferred** or **inhibited**, with the reason — this
  is what prevents both distraction and silent neglect, and it is auditable.
- **Interruption & preemption:** a sufficiently salient bottom-up percept can preempt the current focus,
  but only through metacognitive gating, so the system cannot thrash between shiny stimuli.

### 8.4 Why attention is also *inhibition*

Explicitly deciding what to ignore is a safety and robustness feature: it bounds cost, resists
distraction and adversarial noise (a flood of low-value percepts cannot starve the goal), and produces
an explainable "here's what I chose not to look at, and why."

---

## 9. Long-Term Memory Interaction — Activate, Don't Duplicate

### 9.1 The principle (P1 applied to memory)

The CIP holds **pointers and activation state, never copies** of long-term memory. The Knowledge,
Semantic, and Document platforms remain the sole systems of record. The CIP's job is *activation*:
deciding what to pull into Working Memory, when, and why.

### 9.2 The Recall Orchestrator flow

```
   Working Memory + active goal
        │  (1) formulate recall query FROM cognitive context — not the raw user message
        ▼
   ┌──────────── Recall Port ────────────┐
   │  Semantic Platform  → similarity     │   (2) fan out across faculties
   │  Knowledge Platform → facts / graph  │
   │  Document Platform  → source content │
   └──────────────────────────────────────┘
        │  (3) spreading activation: retrieved items cue further, tighter queries
        ▼
   fuse · de-duplicate · rank by cognitive relevance (goal-match, confidence, recency, provenance)
        │  (4) inject a BOUNDED set as activated items (with activation scores + provenance handles)
        ▼
   Working Memory
```

**The value-add over today's `load_memory → retrieve_context` steps:** the current pipeline retrieves
against the *raw user query* once. The Recall Orchestrator retrieves against the *cognitive state and
goal*, **iteratively** (spreading activation), and fuses across faculties — a strictly more capable
superset that treats the existing steps as one of its ports.

### 9.3 Cognitive memory taxonomy (mapped to faculties)

| Memory type (cognitive) | What it is | Where it lives (never in CIP) |
|---|---|---|
| **Semantic** | Facts, concepts, project truths | Knowledge Platform (+ Semantic index) |
| **Episodic** | What happened, when, and how it went | Cognitive Ledger (+ promoted summaries in Knowledge) |
| **Procedural** | How to think/act well in a situation | Strategy/Policy Store (C15) |
| **Perceptual/source** | The raw material itself | Document Platform |

### 9.4 Write-back path

The CIP does **not** write to long-term memory during recall. Only the **Learning System** writes, and
only *through* the platforms: durable facts → Knowledge Platform (which triggers Semantic indexing);
episodic summaries → Ledger + optionally promoted to Knowledge; strategies → Strategy/Policy Store. This
preserves a single system of record per memory type and keeps the CIP non-duplicative.

---

## 10. Executive Cognitive System — The Metacognitive Layer

> **Design now, implement later.** This section specifies the role and the *hooks* the rest of the
> architecture must expose so the Metacognitive Supervisor can be added **without redesign** — namely
> the Cognitive Ledger (observation surface) and the Cognitive Bus control channel (intervention
> surface). Both are foundational (§5.1) precisely so that C12 is a clean future addition.

### 10.1 Role

The Metacognitive Supervisor is **cognition about cognition** — a model of the system's own thinking
that *regulates* it. It does no object-level work (it never generates the answer or edits the file); it
watches the cycle and steers it. It is the seat of "self-awareness" in the engineering sense.

### 10.2 Functions

- **Monitoring** — confidence, belief coherence (contradictions), progress toward goals, resource and
  loop budgets, drift from original intent, safety-constraint status.
- **Control** — allocate deliberation (raise/lower effort), switch reasoning strategy, trigger more
  recall, pause or abort, force a re-plan, decide "good enough," or **escalate to a human** (P10).
- **Calibration** — track whether its own confidence estimates are well-calibrated and which strategies
  work for which situations, feeding the Learning System.
- **Arbitration** — resolve conflicts between goals, between beliefs, and between fast/slow processes.

### 10.3 Operating model

It runs on a **separate, always-on control loop**, orthogonal to the object-level cycle (§2). It reads
the Ledger and Working Memory continuously and issues **control signals** on the Bus that the Kernel and
components must honor (P8: metacognition can preempt). Because it acts only through these two documented
surfaces, it can be introduced, upgraded, or replaced independently of everything below it.

---

## 11. Reflection Model

### 11.1 Two altitudes of reflection

| | **In-flight reflection** | **After-action reflection** |
|---|---|---|
| When | Synchronously, during the cycle | Asynchronously, after an episode closes |
| Owner | Metacognitive Supervisor | Reflection Engine (C13) |
| Cost | Cheap, frequent | Deliberate, periodic |
| Example | "Is this plan grounded in what I recalled? Confidence too low — think more." | "Replay yesterday's auth-fix episode: which decision caused the failed test?" |

### 11.2 How after-action reflection works

1. **Replay** the episode from the Ledger (percepts → attention → recall → plan → action → outcome).
2. **Compare** the *observed* outcome to the *expected* outcome recorded at Decide (prediction error is
   the primary signal — this is why Planning records expectations, §5.4).
3. **Attribute** success/failure to specific decisions (credit assignment): was it a bad belief? bad
   recall? bad strategy? bad attention?
4. **Emit** structured critiques + *candidate* improvements — Reflection **never mutates state
   directly**; it proposes, and Learning disposes (separation preserves P9).

### 11.3 Sources of ground truth for evaluation

Explicit user feedback and corrections; downstream world signals (did tests pass? was the PR merged? was
the answer edited?); goal satisfaction/abandonment conditions; and internal consistency checks.

### 11.4 Relationship to the existing ReviewAgent

The Generation Platform's adversarial **ReviewAgent** reviews the *object-level artifact* (is this code
correct/secure?). The Reflection Engine reviews the *cognition that produced it* (was my reasoning,
recall, and attention sound?). They are complementary and live on opposite sides of the boundary: the
ReviewAgent is a faculty the CIP *invokes*; Reflection is a higher-order CIP process *about* such
invocations.

---

## 12. Learning Model

### 12.1 Principle

Experiences become **durable, validated, reversible** improvements — never silent, unbounded mutation
(P9). Reflection *proposes*; Learning *validates, commits, and can roll back*.

### 12.2 Learning channels (each with a durable target)

| Channel | What is learned | Durable target |
|---|---|---|
| **Semantic** | New/updated facts & beliefs | Knowledge Platform (write-through) + World Model priors |
| **Episodic** | "When X, approach Y worked/failed" | Ledger summaries, promoted to Knowledge |
| **Procedural** | Better reasoning strategies, tool choices, attention weights | Strategy/Policy Store (C15) |
| **Preference / personalization** | User & org models, style, standards | World Model + Knowledge (extends today's preference memory) |
| **Calibration** | Better confidence & salience estimation | Metacognition + Attention parameters |

### 12.3 The commit pipeline (the guardrails that satisfy P9)

```
  candidate improvement (from Reflection)
     │  validate: contradicts verified knowledge? enough evidence? within policy?
     ▼
  shadow / A-B evaluate  ──► if regression: reject
     │
     ▼
  commit as a VERSIONED change (with provenance) ──► monitor for regression ──► rollback if needed
     │
     ▼   high-impact change? ──► human review (P10)
```

### 12.4 Timescales (multi-rate learning)

- **Fast (within-episode):** the Metacognitive Supervisor adapts effort/strategy *now*.
- **Medium (session/day):** the Reflection→Learning consolidation loop — the generalization of today's
  async fact-consolidator.
- **Slow (global):** policy evolution in the Strategy/Policy Store, versioned and rollback-able.

This is the mechanism by which the CIP "continuously evolves without losing architectural clarity": the
*structure* is fixed (these channels, these guardrails, these stores); only the *content* evolves.

---

## 13. Integration Strategy — Sitting Above Without Breaking Anything

### 13.1 The Port / Adapter layer (Anti-Corruption Layer)

The CIP depends only on **abstract cognitive ports**, never on platform internals (P1, P6). Each
existing platform gets a *thin adapter* that implements a port using the platform's **current public
API** — so no platform is modified.

| Cognitive Port | Abstract contract | Adapter targets (today) | Future producers plug in here |
|---|---|---|---|
| **PerceptionPort** | "give me normalized percepts" | Conversation Platform | Vision, Voice, Email, Meeting, Repository events, Automation triggers |
| **RecallPort** | "activate relevant long-term memory" | Semantic + Knowledge + Document | any future knowledge source |
| **GenerationPort** | "reason / generate given this context" | Generation Platform (CodingAgent, ReviewAgent) | any future model |
| **ActionPort** | "effect this, with guards" | Workspace Platform (tools, git) | Automation, Email send, Voice out |
| **KnowledgeWritePort** | "persist this durable fact" | Knowledge Platform | — |

Because the core speaks only *percepts* and *capabilities* (P11), a new modality is **a new adapter, not
a new mind.**

### 13.2 Progressive adoption — the Strangler-Fig rollout

The existing LangGraph pipeline is a *fixed* cognitive cycle. It is not thrown away — it is **wrapped
and then progressively handed over**:

```
  Stage 0 — Baseline:   pipeline runs exactly as today. CIP absent.
  Stage 1 — Shadow:     CIP observes (percepts + outcomes → Ledger; builds Cognitive State).
                        It controls NOTHING. Zero behavior change; pure learning of the ground.
  Stage 2 — Advisory:   CIP proposes attention/recall/strategy; pipeline may take or ignore hints.
  Stage 3 — In-control: CIP kernel drives the cycle; the old pipeline nodes become ADAPTERS behind
                        the cognitive ports (route_intent→Perceptor/Goal, load_memory+retrieve→Recall,
                        plan_tools→Planner, tool loop→ActionPort, review loop→Reflection-invoked
                        ReviewAgent, finalise→consolidate+Learn).
```

Each stage is independently shippable and reversible via a feature flag / capability negotiation. Old
clients hitting existing endpoints see **identical behavior** until an episode is explicitly opted into
cognitive control.

### 13.3 Backward compatibility guarantees

- **Additive only.** The CIP introduces new services and new state stores; it changes no existing API
  contract, schema, or module. Existing endpoints keep working unchanged.
- **No platform reaches into the CIP.** Dependency points *downward only* (mind → faculties). Removing
  the CIP entirely returns the system to Stage 0. This is the ultimate backward-compatibility proof.
- **Independent lifecycle.** The CIP is a separate service/process with its own stores (Cognitive State
  DB, Ledger, Working-Memory cache), released and scaled independently.

### 13.4 Future expansion — one table, zero redesign

| Future capability | Plugs in as | Core changes required |
|---|---|---|
| **Vision AI** | PerceptionPort producer (image percepts) + Document adapter | none |
| **Repository AI** | PerceptionPort (repo events) + ActionPort (repo effects) | none |
| **Meeting Intelligence** | PerceptionPort (transcript/decision percepts) | none |
| **Automation** | ActionPort capabilities + Automation triggers as percepts | none |
| **Email Intelligence** | PerceptionPort (inbound) + ActionPort (send, guarded) | none |
| **Voice Intelligence** | PerceptionPort (STT percepts) + ActionPort (TTS out) | none |
| **Multi-Agent Collaboration** | Multiple cognitive instances sharing the Knowledge Platform and coordinating on the Cognitive Bus / a shared workspace | none |

The invariant that makes this table possible: **the cognitive core operates on abstract percepts and
abstract capabilities (P11), and never on modality- or platform-specific types.**

---

## 14. Engineering Requirements — Compliance Summary

| Requirement (from the mandate) | How the architecture satisfies it |
|---|---|
| Completely modular | Independent components (§5) on the Bus (C1), each behind a contract (P6). |
| Every capability independently replaceable | Ports + adapters (§13.1); no cross-component internals (P6, P12). |
| No existing platform depends on cognitive internals | Dependencies point downward only (§13.3); removing the CIP → Stage 0. |
| CIP orchestrates services through defined interfaces | The five cognitive ports (§13.1) are the only contact surface. |
| Supports Vision / Repository / Meeting / Automation / Email / Voice / Multi-Agent without redesign | Percept/capability abstraction (P11) + expansion table (§13.4). |
| Suitable for review by researchers, principal engineers, CTOs | Grounded in cognitive science (Global Workspace, working-memory capacity, dual-process, predictive processing) *and* in software invariants (event-sourcing, ACL, strangler-fig). |

---

## 15. Glossary

- **Faculty** — one of the six existing platforms; a reactive, request-scoped capability.
- **Cognitive Cycle** — the ten-phase loop (§2); one pass = a *cognitive step*.
- **Cognitive Episode** — a bounded run of steps toward a goal.
- **Percept** — a normalized, modality-agnostic unit of "something happened."
- **Cognitive State** — the persistent, subjective, six-layer state of the mind (§6).
- **Working Memory** — the small, bounded, active workspace / blackboard (§7).
- **World Model** — the situational (belief) layer of Cognitive State.
- **Salience** — the multi-factor score that drives attention (§8.2).
- **Broadcast** — publishing the winning attention coalition into Working Memory (Global Workspace).
- **Cognitive Ledger** — the append-only event-sourced trace of all cognition (C2).
- **Metacognition** — cognition about cognition; the executive supervisor (§10).
- **Port / Adapter** — the anti-corruption boundary between the mind and a faculty (§13.1).

---

### Closing statement

The six UnityWorks platforms are a superb set of **faculties**. This blueprint adds the one thing a
collection of faculties cannot supply on its own: a **mind** — a persistent, attentive, goal-directed,
self-supervising, learning process that sits *above* them, speaks to them only through clean contracts,
and can grow new senses and new actions without ever redesigning its core. The structure is fixed; the
intelligence within it is free to evolve.
