---
name: unityworks-ai-ml
description: Use when changing, debugging or evaluating anything in the UnityWorks AI Assistant backend that calls a model or depends on model output - LLM calls, chat profiles, thinking/reasoning, prompts, provider or model config (NVIDIA, Ollama, UnityWorks self-hosted), embeddings, ChromaDB retrieval, RAG, document grounding and [S#] citations, VLM invoice extraction, chat vision, code generation sandbox, Cognitive OS chat, or vision_eval datasets - and when a reply is blank, refused, ungrounded, slow, ignores a prompt edit, or retrieval returns poor results.
---

# UnityWorks AI/ML

## Overview

The backend has **several independent model paths**, each with its own client, provider switch and
prompt. Most wasted effort in this repo comes from editing the wrong one. The rule:

> **Find the path that actually serves the request before touching a prompt, a model or a threshold.**

The second rule is the repo's culture: every threshold, token budget and prompt rule carries the
measurement that justified it in a comment. Change one only with a new measurement, and write the
numbers into the comment the same way.

All paths below are relative to `backend/`. Run Python as `.\venv\Scripts\python.exe` (venv is 3.11.9).

## Step 1 — Which path serves this request?

`POST /api/v1/chat/stream` ([app/api/v1/chat/router.py](app/api/v1/chat/router.py)) tries these **in order**
and the first match wins:

| # | Condition | Handler | System prompt comes from |
|---|---|---|---|
| 1 | Message asks for a file / is about a sheet | `_maybe_stream_file_response` → `app/chat_artifacts/` | chat_artifacts |
| 2 | Conversation has uploaded documents | `_stream_document_response` → `app/documents/service.py` | intelligence engine + extracted text |
| 3 | `COGNITIVE_BRAIN_ENABLED` (**default True**) and `deliberate_turn` returns non-None | `_stream_cognitive_response` | **hard-coded `_STREAM_SYSTEM` in [cognitive_integration/pipeline.py](app/cognitive_integration/pipeline.py)** |
| 4 | Fallback | LangGraph `AgentOrchestrator.stream` | `intelligence/prompt/composer.py` + `prompts/registry.py` modules |

Consequence: **with default config, ordinary chat never reaches the orchestrator, the intelligence
engine, repo retrieval or `app/prompts/modules/`.** Editing those changes nothing the user sees unless
the brain is disabled or `deliberate()` raised. `deliberate()` makes no LLM call; it only runs
Perception → Attention → Executive and decides authorize vs. escalate.

Other entry points:

| Surface | Code | Model client | Provider switch |
|---|---|---|---|
| `POST /chat/message` (non-stream) | orchestrator directly | `OllamaClient.chat` | `LLM_PROVIDER` |
| `POST /chat/stream/vision` | `app/vision/vision_model.py` | own httpx per provider | `VISION_PROVIDER` (default `nvidia`; set empty → `LLM_PROVIDER`) |
| `POST /cognitive-chat/message` | `CognitivePipeline.handle` → `OllamaReasoningEngine` | `OllamaLLMAdapter` → `OllamaClient.chat` (sync bridge) | `LLM_PROVIDER` |
| Knowledge workspace Q&A | `document_platform/conversation/gateway.py` | `get_llm_provider()` in `conversation/llm.py` | **`DOCUMENT_VLM_PROVIDER`** (not `DIP_LLM_PROVIDER`, which nothing reads) |
| Generation plans | `document_platform/generation/planner.py` | same `get_llm_provider()` | `DOCUMENT_VLM_PROVIDER` |
| Document tasks (NL → Python) | `document_platform/execution/` | `execution/model.py` | `DOCUMENT_VLM_PROVIDER`; runs in Docker `--network none` |
| Invoice extraction | `document_platform/vlm/pipeline.py` | `DocumentVLMPort` from `adapters/document_vlm/registry.py` | `DOCUMENT_VLM_PROVIDER` |
| Repo indexing / code retrieval / LTM | `indexing/`, `retrieval/`, `memory/` | `OllamaClient.embed` | **always Ollama** (`OLLAMA_EMBED_MODEL`) |
| DIP embeddings | `document_platform/semantic/providers.py` | `get_embedding_provider()` | `DIP_EMBEDDING_PROVIDER` |

## Step 2 — The text-model layer

[app/llm/](app/llm/) is the one door for text generation on NVIDIA:

- **Call sites name a profile, never a model, temperature or token budget.** Profiles in
  [profiles.py](app/llm/profiles.py): `general`, `reasoning`, `math`, `coding`, `agent_planning`, `document`
  (public) and `codegen`, `fast` (internal). `reasoning`/`math` run on `NVIDIA_REASONING_MODEL`; the rest
  on `NVIDIA_CHAT_MODEL`. Tune one profile with `LLM_PROFILE_OVERRIDES` JSON, not code.
- `agent_mode` → profile via `profile_for_mode()`; unknown modes fall back to `general`.
- `ChatGateway.complete()` / `.stream()` return the answer and the reasoning **separately**. Reasoning
  is streamed as its own SSE event (`type: reasoning`, via `ReasoningDelta`) and is never saved or
  pushed into session memory.
- `app/ollama_client.py` is the legacy facade: `chat`/`chat_stream` branch on `LLM_PROVIDER` —
  `nvidia` delegates to the gateway (profile applies; `model` ignored), `ollama` uses per-mode Ollama
  models (profile ignored). `embed()` is always Ollama.

### Recipe: add a new LLM call

1. Pick an existing profile. Add a new one to `_BUILTIN` only if no profile fits its latency/determinism
   needs. Public profiles appear in the UI via `GET /api/v1/llm/profiles`.
2. Call `get_chat_gateway().complete(user=..., system=..., profile=...)`. If the code must also run under
   `LLM_PROVIDER=ollama`, go through `get_ollama_client().chat(..., profile=...)` instead.
3. Pass `temperature=None` on NVIDIA so the profile decides (see `CodingAgent._temperature`).
4. Catch `LLMGatewayError`; its message is safe to show and never contains the key.
5. Test with the fake `AsyncOpenAI` pattern in `tests/unit/test_llm_gateway.py` — no test may reach NVIDIA.

### Behaviours to preserve

- Retries only for 408/409/425/429/5xx and stream-embedded 503; never 4xx.
- `stream()` retries **only before the first event** — after that a retry would repeat text already shown.
- A thinking model that burns its whole `max_tokens` thinking raises instead of returning an empty
  "success". Fix by raising the profile budget or disabling thinking, not by swallowing the error.
- Thinking switch key differs by family (`enable_thinking` for Nemotron/Qwen, `thinking` for DeepSeek);
  the wrong one is silently ignored.

## Step 3 — Prompts

Where to edit, per path from Step 1:

| Path | Edit here |
|---|---|
| Default streaming chat (brain) | `_STREAM_SYSTEM` in `cognitive_integration/pipeline.py` |
| Orchestrator | `intelligence/prompt/composer.py` (V2, used) + `prompts/registry.py` modules. `prompts/composer.py` is the legacy composer, exported but not used by the graph |
| DIP answers | `document_platform/conversation/prompts.py` (`PromptBuilder`, `REFUSAL_SENTENCE`, `CITATION_REMINDER`) |
| Invoice extraction | `document_platform/vlm/prompts.py` — versioned; add a new version, select with `DOCUMENT_VLM_PROMPT_VERSION`. Adapters must never compose or prepend prompts |
| Cognitive reasoning faculty | `_SYSTEM` in `cognitive_integration/reasoning_port.py` |

Prompt-writing lessons **measured on the deployed models here** (see comments in `pipeline.py` and
`conversation/prompts.py`):

- **State the wanted behaviour, don't quote the unwanted one.** Banning a stock phrase made it the most
  common opener in 4/6 samples; quoting a too-short reply as the failure reproduced it 5/5. A positive
  rule for the first move cut a bad opener from 6/6 to 2/6.
- **Restate critical rules after long context.** Citation rules only at the top of the system prompt
  produced no `[S#]`; the same rule restated after the sources and question produced citations.
- Send history as real `{role, content}` turns. A transcript pasted into the user message made the model
  greet the user again every turn.

## Step 4 — Retrieval and embeddings

**Code RAG** (`indexing/` → `retrieval/`): tree-sitter AST chunks (`MAX_CHUNK_TOKENS=2000`, 3-line
overlap on split) → embed text prefixed `"{language} {chunk_type}: {name}\nFile: ..."` → Chroma
collection `code_{repo_id}` (cosine) → fetch 20 → MMR (λ=0.7) → top 8 → `ContextBuilder`. Keep AST
chunking; it is why retrieval is 30–40% better than text chunking. Retrieval is skipped for intent `chat`
or when no repo is attached.

**DIP RAG** (`document_platform/`): structure-aware chunks (target 400 / max 600 tokens, never crossing a
section, tables as their own chunks) → embeddings registered in `EmbeddingRegistry` → per-org
collections → `RetrievalEngine` (embeds the question with `purpose="query"`) → `RankingEngine` →
`ContextBuilder(DIP_CONTEXT_TOKEN_BUDGET)`. The planner doubles `top_k` for summaries, ×1.5 for comparisons.

Traps:

- **Score scales differ.** Code store: `1 - distance/2` (0..1). DIP store: `1 - distance`. Never reuse a
  threshold across the two.
- **Vectors are not interchangeable across models/providers.** Changing `OLLAMA_EMBED_MODEL` or
  `DIP_EMBEDDING_PROVIDER` means re-embedding everything already stored — plan a reindex, don't just flip it.
- `OllamaEmbeddingProvider` ignores `purpose`; only NVIDIA sends `input_type` query/passage.
- `OllamaClient.embed` posts one text per request to `/api/embeddings`; `batch_size` does not batch the HTTP calls.
- Chroma Cloud (`vector_store/chroma_cloud.py`) queries don't return embeddings, so code-retrieval MMR
  silently falls back to Jaccard token overlap there.
- `chromadb` is pinned to 0.5.20 to match the local server; Cloud goes through the REST client instead.
- Tokens are estimated as `len(text) // 4` throughout; there is no tokenizer.

## Step 5 — Invariants (tests enforce them)

| Invariant | Enforced by |
|---|---|
| DIP answers must cite `[S#]` that resolve, and pass `DIP_GROUNDING_MIN_SCORE`. A `REFUSAL_SENTENCE` reply is **valid with `grounded=false`**, not an error | `conversation/validator.py`, `tests/document_platform/` |
| Missing or invented markers may be recovered by evidence (`attribution.py`, `DIP_ATTRIBUTION_MIN_SUPPORT`); a low grounding score may **not** | `gateway._recoverable` |
| No provider name (`nvidia`, `ollama`, `openai`, …) in `document_platform/vlm/` or the extraction API; providers register themselves | `tests/document_vlm/test_architecture.py`, `test_provider_switching.py` |
| Cognitive kernel is pure stdlib; engines never import each other; ledger has no update/delete | `tests/cognitive_*/test_architecture.py` |
| Intelligence engine never calls the LLM; a policy block or clarification short-circuits before any LLM call | `AgentOrchestrator._after_intelligence` (by construction; no dedicated test — add one if you touch it) |
| Brain failure falls back to the orchestrator; high-stakes turns are escalated, never auto-answered | `tests/cognitive_integration/test_cognitive_chat_slice.py` |
| Generated code only runs in the network-less sandbox; document rows never leave the machine | `execution/sandbox.py` |

**Never "fix" a refusal by lowering `DIP_GROUNDING_MIN_SCORE`, letting uncited text through, or catching
the validator's rejection.** Find out why retrieval or citation failed.

### Recipe: add a document VLM provider

Write `app/adapters/document_vlm/<name>.py` implementing `DocumentVLMPort` (subclass
`HttpDocumentVLMAdapter`), call `register_document_vlm_provider("<name>", factory, describe=...)`, add a
`tests/document_vlm/test_<name>_adapter.py`. No edit in `app/document_platform/`, the API, or `config.py`
beyond the adapter's own settings. Run `tests/document_vlm`.

## Config traps (verify in `app/config.py` before trusting)

- `LLM_PROVIDER` defaults to **`nvidia`**; `NVIDIA_TEMPERATURE` / `NVIDIA_MAX_TOKENS` are **not read by the
  gateway** — profiles own those.
- `COGNITIVE_BRAIN_ENABLED` defaults **True**; the docstring in `flag.py` says otherwise.
- `OLLAMA_HOST` and `OLLAMA_BASE_URL` default to a LAN IP; `CHROMA_PORT` defaults to 8000 (the API's own
  port) — set 8001 locally.
- Some comments disagree with the values next to them: `DOCUMENT_VLM_TEMPERATURE=1.00` ("not a creative
  task") and `DOCUMENT_VLM_MAX_OUTPUT_TOKENS=32768` (comment argues 8192 and warns the full window returns
  HTTP 400). Check the deployed `.env` and measure before relying on either.
- `pipeline._select_model` reads `dip_chat_model`, which does not exist, so it falls back to
  `OLLAMA_AUTO_MODEL`. On NVIDIA the model argument is ignored anyway.
- The self-hosted UnityWorks endpoint decodes ~11 tok/s, answers in one shot (streaming is sliced after
  the fact) and reports no token counts — output budgets there are latency budgets.
- `DOCUMENT_VLM_MAX_PAGES=4`: each page image costs ~3.3k prompt tokens; five pages fail outright.

## Vision evaluation (CV)

`tools/vision_eval/` scores Vision OS perception against human ground truth in `datasets/`. It trains
nothing and writes no labels. `app/vision_os/` is migrated verbatim — don't lint or redesign it.

```powershell
.\venv\Scripts\python.exe -m tools.vision_eval.run_baseline datasets/kitchen-01 --tag baseline --cache
```

Results land in `<dataset>/results/<tag>.json`; compare a change against a stored baseline, never against
memory. Splits are grouped to prevent leakage (`LeakageError`). The four states
`PRESENT`/`ABSENT`/`NOT_VISIBLE`/`UNKNOWN` stay distinct in every metric.

## Verification

Subset runs need `--no-cov` (the 75% gate is in `addopts`):

```powershell
.\venv\Scripts\python.exe -m pytest tests/unit/test_llm_gateway.py tests/unit/test_llm_stream_errors.py --no-cov
.\venv\Scripts\python.exe -m pytest tests/unit/test_retriever.py tests/unit/test_chunker.py --no-cov
.\venv\Scripts\python.exe -m pytest tests/document_platform tests/document_vlm --no-cov
.\venv\Scripts\python.exe -m pytest tests/cognitive_integration tests/unit/intelligence --no-cov
.\venv\Scripts\python.exe -m ruff check <files you touched>
```

Known failures on the main workstation (2026-09-17) — compare against these before blaming your change:

| Failure | Cause |
|---|---|
| `test_chunker.py::test_rust_chunker`, `test_c_chunker`, `test_cpp_chunker` | `tree_sitter_rust` / C / C++ grammars not installed in the venv (environment) |
| `test_nvidia_adapter.py::…default_model…`, `test_ollama_adapter.py` factory/endpoint cases | Tests read the local `.env` (model and `OLLAMA_HOST` overridden) — tests are not isolated from `.env` |
| `test_confidence_evaluator.py` / `test_all_reasoning.py` `…no_chunks_gives_very_low_repo_match` | Code returns `MEDIUM`, test expects `VERY_LOW` — real mismatch, unresolved |

For a behaviour change to a prompt or threshold, tests are not enough: run the real path (e.g.
`scripts/e2e_dip_*.py`, `scripts/e2e_chat_docs.py`) several times and record the observed rates in the
code comment. One sample proves nothing.

## Common mistakes

| Mistake | Instead |
|---|---|
| Editing `prompts/modules/` to change normal chat replies | Confirm the path (Step 1); default chat uses `_STREAM_SYSTEM` |
| Hard-coding a model name, temperature or `max_tokens` at a call site | Name a profile; use `LLM_PROFILE_OVERRIDES` |
| Flipping `DIP_LLM_PROVIDER` to change the document model | `DOCUMENT_VLM_PROVIDER` decides it |
| Branching on provider name inside `document_platform/` | Register an adapter |
| Lowering the grounding threshold because answers get refused | Debug retrieval, citations, attribution |
| Switching embedding model without reindexing | Re-embed; old and new vectors can't be compared |
| Blank reply "fixed" by catching the error | Raise the profile's token budget or turn thinking off |
| Quoting bad example output in a prompt as "don't do this" | Describe the required behaviour positively |
| Mixing reasoning text into the saved answer or memory | Keep `reasoning` events separate |
| Changing a threshold on intuition | Measure on real data; write the numbers in the comment |
