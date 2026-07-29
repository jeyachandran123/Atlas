# Cognitive Integration Layer (Version 1 Integration Phase)

> Adapters — and only adapters — connecting the existing UnityWorks **Body**
> (platforms + Ollama + Intent Detector + Context Builder + Generation) to the
> completed Cognitive Operating System **Brain**. Nothing here redesigns an engine,
> a platform, or the Constitution.

## The brain becomes the centre

```
BEFORE:  Conversation → LLM → Response
NOW:     Conversation → Perception → [BRAIN] → Executive → Generation → Response
```

## Components (this package)

| File | Role |
|---|---|
| `session.py` | **CognitiveSession** — boots Kernel/Runtime/State + all 8 engines; Reasoning is given an Ollama-backed pool. The one composition root. |
| `ports.py` | Synchronous Protocols (Intent/Context/LLM/Generation/PlatformAction) + DTOs. The seams. |
| `perception.py` | **Perception Adapter** — Intent + Context → cognitive objects (goal/percept/evidence) loaded into Working Memory. |
| `reasoning_port.py` | **Reasoning Adapter** — `OllamaReasoningEngine` implements the engine's `ReasoningEnginePort` and invokes the existing Ollama client. |
| `platform_actions.py` | **Platform Action Adapter** — Executive-authorized action → injected platform organ (Document/Knowledge/Workspace/Generation). |
| `generation.py` | **Generation Adapter** — conclusion → existing Generation pipeline → reply. |
| `pipeline.py` | **CognitivePipeline** — the one vertical slice, orchestrating the adapters. |
| `adapters_prod.py` | Production wrappers reusing the *real* Ollama / Intent Detector / history / generation. |
| `factory.py` | Builds a production pipeline (lazy singleton for the route). |
| `flag.py` | `COGNITIVE_BRAIN_ENABLED` — off by default; production chat pipeline untouched. |

## Rules honoured

- No constitutional change · no engine redesign · no platform redesign.
- No duplicated logic · engines import no platform/adapter · adapters use ports + DI.
- The whole layer is gated by one flag; disabled = existing pipeline unchanged.

## Enable it

```bash
COGNITIVE_BRAIN_ENABLED=true
# then POST /api/v1/cognitive-chat/message  { "message": "..." }
```

Tests: `tests/cognitive_integration/test_cognitive_chat_slice.py` (7 tests) prove the
full turn flows Conversation → Perception → WM → Attention → Reasoning → Ollama →
Executive → Generation → Response, and that dangerous requests are escalated, not
auto-answered.
