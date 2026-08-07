# Document VLM Provider — Implementation Report

**Scope.** A `DocumentVLMPort` abstraction for the UnityWorks Document Platform, two
provider implementations (NVIDIA cloud, Ollama local), the invoice extraction pipeline
that consumes them, and one REST endpoint for ERP integration.

**Architectural stance.** The frozen UnityWorks architecture was not modified. This work
is additive: three existing files gained lines (none changed behaviour), and everything
else is new packages that plug into the existing Ports & Adapters arrangement the
platform already runs on.

---

## 1. Architecture Compliance Report

### 1.1 Where everything lives

```
app/api/v1/document_extraction/          ← composition root (the ONLY place a
    dependencies.py                        provider is chosen and wired)
    router.py                            ← HTTP only
    schemas.py

app/adapters/document_vlm/               ← infrastructure (outside the platform)
    base.py         retries, timeouts, error classification, telemetry
    nvidia.py       NvidiaDocumentVLMAdapter
    ollama.py       OllamaDocumentVLMAdapter
    registry.py     env-driven selection + registration for future providers

app/document_platform/vlm/               ← the platform (provider-neutral)
    ports.py            DocumentVLMPort + DTOs
    errors.py           provider-neutral failure taxonomy
    prompts.py          InvoiceExtractionPromptProvider (versioned)
    json_repair.py      parse / repair / never crash
    invoice_schema.py   the invoice contract + validator
    payload.py          upload → payload, reusing the platform's OCR stage
    pipeline.py         DocumentExtractionPipeline
    observability.py    telemetry + redaction
```

The dependency arrow runs one way only:

```
composition root  →  adapters  →  port  ←  pipeline / prompts / schema
```

Adapters import the platform. **The platform imports nothing from `app.adapters`.** The
adapters directory could be deleted and `app/document_platform/vlm` would still import,
still type-check, and still pass its own tests against a scripted provider.

### 1.2 Why adapters sit outside `document_platform`

The brief's requirement — *"The Document Platform must NEVER know NVIDIA / Ollama /
Claude / Gemini / OpenAI"* — is enforceable only if the provider names are physically
absent from the platform package. Placing the concrete adapters in
`app/adapters/document_vlm/` makes that a property a test can check by reading source,
rather than a convention that erodes.

`tests/document_vlm/test_architecture.py` asserts it on every run:

| Assertion | What it prevents |
|---|---|
| No file under `document_platform/vlm` imports `app.adapters` | The platform having to change when a provider does |
| No provider name appears in platform **executable code** (docstrings exempt) | A `if provider == "nvidia"` branch appearing later |
| The platform imports no HTTP client (`httpx`, `requests`, `aiohttp`, `openai`) | Transport opinions leaking into business logic |
| No adapter imports `pipeline` or `invoice_schema` | An adapter learning what an invoice is |
| No adapter imports another adapter | Providers becoming a chain instead of siblings |
| No adapter calls `get_settings()` | Adapters that can't be built twice with two configs (kills A/B) |
| `get_document_vlm(` appears in exactly one file: `dependencies.py` | Provider construction leaking out of the composition root |
| The router and response schema name no provider | The wire contract coupling to a deployment detail |

### 1.3 Consistency with the existing UnityWorks ports

`DocumentVLMPort` is built the same way as `UnderstanderPort`
(`app/vision_os/core/ports/understanding.py`) and the `cognitive_integration` ports: a
`@runtime_checkable` `Protocol` over frozen dataclasses, versioned
(`DOCUMENT_VLM_PORT_VERSION = "1.0.0"`), with a written semantic contract (V1–V7) that
adapters are obliged to honour.

Structural typing rather than inheritance is deliberate and matches the existing
codebase: `ScriptedDocumentVLM` in the test suite satisfies the port without inheriting
anything, which is the proof that the port is at the right altitude.

### 1.4 Reuse rather than reinvention

| Existing abstraction | How it is used | Modified? |
|---|---|---|
| `document_platform.processing.ocr.OcrService` | Injected into `DocumentPayloadBuilder`; the OCR stage of the pipeline | **No** |
| `AbstractOcrProvider` / `NullOcrProvider` / `TesseractOcrProvider` | Selected by `DOCUMENT_OCR_PROVIDER` in the composition root | **No** |
| `document_platform.constants.MAGIC_SIGNATURES` | Content-sniffing the upload | **No** |
| `app.shared.exceptions.AIAssistantError` | Base of the VLM error taxonomy, so escapes still map to HTTP | **No** |
| `app.auth.get_current_user` | Same JWT / `X-API-Key` auth as every other endpoint | **No** |
| `app.observability` (Prometheus, loguru) | Same metric and logging conventions | **No** |
| `pypdf` | PDF text layer + embedded page images (already a dependency) | **No** |

**No new runtime dependency was added.** `httpx`, `pydantic`, `pypdf`, `loguru` and
`prometheus_client` were already in `requirements.txt`.

### 1.5 Files touched

| File | Change |
|---|---|
| `app/config.py` | +47 lines of new settings fields; one validator extended to cover `ollama_base_url`. No existing field altered. |
| `app/main.py` | +2 lines: import and mount the new router. |
| `.env.example` | +43 lines documenting the new variables. |

Everything else is new. `git diff --stat` on the pre-existing files shows 92 insertions,
1 deletion (the deletion is the validator's decorator line being widened to two fields).

---

## 2. Provider Integration Report

### 2.1 The port

```python
class DocumentVLMPort(Protocol):
    def provider_name(self) -> str: ...
    def model_name(self) -> str: ...
    async def extract_document(self, request: VLMExtractionRequest) -> VLMExtractionResult: ...
    async def health(self) -> ProviderHealth: ...
    def estimate_cost(self, request: VLMExtractionRequest) -> CostEstimate: ...
```

Semantic contract, enforced by tests:

| # | Obligation |
|---|---|
| V1 | Returns the model's structured output and the verbatim text it came from. Nothing else. |
| V2 | **Never fabricates.** Timeout, refusal or unparseable answer is a typed error — never a plausible empty invoice. |
| V3 | Applies no business interpretation. |
| V4 | Stateless across calls. |
| V5 | The prompt arrives in the request; adapters never compose one. |
| V6 | Cost is estimable before the call. |
| V7 | Credentials never appear in a return value, error, log line or metric. |

### 2.2 NVIDIA — `NvidiaDocumentVLMAdapter`

* **Endpoint**: `POST {NVIDIA_BASE_URL}/chat/completions` (OpenAI-compatible).
* **Default model**: `nvidia/llama-3.1-nemotron-nano-vl-8b-v1`.
* **Auth**: `Authorization: Bearer {NVIDIA_API_KEY}`.
* **Images**: data-URI content parts by default; `NVIDIA_IMAGE_FORMAT=inline_html`
  switches to the `<img src="data:…"/>` form some NVIDIA VL endpoints expect. Configurable
  because NVIDIA's own vision families disagree, and guessing would be a code change per
  model.
* **Oversized pages**: images beyond `NVIDIA_MAX_INLINE_IMAGE_BYTES` (base64-inflated) are
  dropped *only when text or another page remains*, with a warning. A single oversized page
  with no text is still sent, so the provider's own error surfaces rather than an empty payload.
* **Health**: `GET {base}/models` — proves reachability, credentials and catalogue presence
  without paying for an inference. A model absent from the listing is a warning, not a
  failure (private NIM deployments serve unlisted models).
* **Cost**: token estimate always; a priced figure only when
  `NVIDIA_PRICE_PER_MILLION_*_TOKENS` are configured. Unset reports `currency: "unpriced"`
  rather than a hard-coded rate that would go stale silently.
* **Raw `httpx`, not the `openai` SDK** — the adapter must classify 401 from 429 from 5xx
  from a truncated body precisely and be drivable through `httpx.MockTransport`. An SDK
  hides exactly those seams.

### 2.3 Ollama — `OllamaDocumentVLMAdapter`

* **Endpoint**: `POST {OLLAMA_BASE_URL}/api/chat`.
* **Default model**: `qwen2.5vl:7b`.
* **Images**: base64 strings on the user message (`images: [...]`).
* **Structured output**: `format: "json"`, or the JSON Schema itself when a prompt supplies
  one. The platform still validates — a constrained decoder guarantees shape, never truth.
* **Usage**: `prompt_eval_count` / `eval_count` mapped onto the same `TokenUsage` DTO NVIDIA
  fills from its `usage` block.
* **Model-not-pulled**: Ollama answers 404 (or a 200 with an `error` key). Both are
  translated to `DocumentVLMUnavailableError` carrying `ollama pull <model>` — the single
  most common local failure, which a generic 502 would obscure.
* **Health**: `GET {base}/api/tags`, and the check requires **the configured model to be
  present**, not merely that the daemon answers. A running daemon without the model fails
  on the first real request, hours after a green health check.
* **Cost**: zero, `currency: "none"`, basis `"local inference, no per-call monetary cost"`.

### 2.4 What is shared, and why

`HttpDocumentVLMAdapter` (`base.py`) owns retries, backoff, timeout handling, HTTP status
classification, JSON recovery, refusal detection, telemetry and cost token-counting —
because those are properties of *calling a model over HTTP*, not of any provider. A
concrete adapter supplies four methods:

```python
_endpoint()        where to POST
_headers()         what to authenticate with
_body(request)     the provider's request shape
_read_response()   where text and usage live in the reply
_probe_health()    what "healthy" means here
```

Adding a provider is those five methods plus one registration line. An abstraction that
makes the second implementation cheap and the fifth expensive has not abstracted anything.

### 2.5 Error taxonomy (provider-neutral)

| Error | Trigger | Retryable | HTTP |
|---|---|---|---|
| `DocumentVLMConfigurationError` | Missing key, unknown provider, unregistered prompt version | No | 500 |
| `DocumentVLMUnsupportedProviderError` | `DOCUMENT_VLM_PROVIDER` names nobody | No | 500 |
| `DocumentVLMAuthError` | 401 / 403 | **No** | 502 |
| `DocumentVLMRateLimitError` | 429 (honours `Retry-After`) | Yes | 429 |
| `DocumentVLMTimeoutError` | Read/connect timeout | Yes | 504 |
| `DocumentVLMConnectionError` | DNS, TLS, refused | Yes | 502 |
| `DocumentVLMUpstreamError` | 5xx | Yes | 502 |
| `DocumentVLMBadRequestError` | Other 4xx | No | 502 |
| `DocumentVLMUnavailableError` | Reachable, model absent | No | 503 |
| `DocumentVLMInvalidResponseError` | Body not JSON / no content / unrepairable text | No | 502 |
| `DocumentVLMRefusedError` | Model declined | No | 422 |

A 401 from the provider returns **502, never 401** — the caller authenticated fine, and
returning 401 would send an ERP chasing its own credentials for our misconfiguration.

---

## 3. API Report

### 3.1 Endpoints

```
POST /api/v1/document/extract-invoice   multipart/form-data: file[, prompt_version]
GET  /api/v1/document/vlm/health        provider health (503 when unhealthy)
GET  /api/v1/document/vlm/provider      effective configuration, no credentials
```

Auth is the platform's existing dependency: `Authorization: Bearer <jwt>` or
`X-API-Key: <key>`. The API-key path is what an ERP uses.

### 3.2 Success envelope

```json
{
  "success": true,
  "provider": "nvidia",
  "model": "nvidia/llama-3.1-nemotron-nano-vl-8b-v1",
  "processingTime": 4182.55,
  "data": {
    "document_type": "invoice",
    "invoice_number": "INV-2026-0042",
    "purchase_order_number": "PO-9001",
    "invoice_date": "2026-01-15",
    "due_date": "2026-02-14",
    "currency": "SGD",
    "supplier": { "name": "...", "address": null, "tax_id": "...", "registration_number": null, "email": null, "phone": null },
    "customer": { "name": "...", "...": null },
    "line_items": [
      { "line_number": 1, "description": "Steel bracket", "product_code": null,
        "quantity": 10, "unit": null, "unit_price": 25.0, "discount": null,
        "tax_rate": null, "tax_amount": null, "amount": 250.0 }
    ],
    "totals": { "subtotal": 280.0, "discount_total": null, "tax_total": 25.2,
                "shipping_total": null, "grand_total": 305.2,
                "amount_paid": null, "amount_due": 305.2 },
    "payment_terms": "Net 30", "payment_reference": null,
    "bank_details": null, "notes": null,
    "additional_fields": {}
  },
  "requestId": "0f2c…", "promptVersion": "1.0.0", "schemaVersion": "1.0.0",
  "warnings": [],
  "usage": { "promptTokens": 1200, "completionTokens": 180, "totalTokens": 1380 },
  "retryCount": 0, "jsonRepaired": false,
  "stages": { "payload": 210.4, "prompt": 0.3, "vlm": 3960.1, "validation": 11.7 },
  "document": { "filename": "invoice.pdf", "mediaType": "application/pdf",
                "pageCount": 2, "imagesSent": 2, "textSource": "pdf_text_layer",
                "textChars": 1840, "ocrProvider": "null", "ocrPerformed": false }
}
```

`processingTime` is milliseconds, end to end. `stages` breaks it down so a slow extraction
can be attributed to OCR, the model, or validation without a profiler.

### 3.3 Failure envelope

Same top-level shape, so a client reads `success` first and never guesses:

```json
{
  "success": false,
  "provider": "ollama", "model": "qwen2.5vl:7b",
  "processingTime": 120004.1, "requestId": "0f2c…",
  "error": { "code": "vlm_timeout", "message": "ollama did not respond within 120s",
             "retryable": true, "violations": [] }
}
```

A failure **never carries a `data` key**. An extraction that did not happen is visibly
absent, not quietly empty. `Retry-After` is set on 429 from the provider's own signal.

### 3.4 Status codes

| Code | Meaning |
|---|---|
| 200 | Extracted and validated (may carry `warnings`) |
| 413 | Above `DOCUMENT_VLM_MAX_FILE_SIZE_MB` |
| 415 | Not a PDF or image |
| 422 | Empty document, model refusal, or JSON that is not an invoice |
| 429 | Provider rate limited (with `Retry-After`) |
| 502 | Provider auth / upstream / bad request / unusable response |
| 503 | Provider reachable but cannot serve the model |
| 504 | Provider timeout |

All of these are declared in the OpenAPI schema; a test asserts each one is documented.

### 3.5 ERP integration

One endpoint, one multipart POST, one JSON response. The ERP never learns which provider
answered, never holds a provider credential, and needs no change when the deployment
switches providers. `provider` and `model` in the envelope are for attribution and support,
not for branching — a test asserts the response carries no provider-shaped structures
(`choices`, `eval_count`, …).

---

## 4. Environment Configuration Report

Every value is environment-driven. **No URL and no model name is hard-coded anywhere
except as a documented default in `Settings`.**

### Selection
| Variable | Default | Purpose |
|---|---|---|
| `DOCUMENT_VLM_PROVIDER` | `ollama` | `nvidia` \| `ollama` \| any registered provider |

Typed as `str`, not a `Literal`, precisely so registering a future provider does not require
editing `config.py`. Unknown values fail loudly at startup with the list of registered names.

### NVIDIA
| Variable | Default |
|---|---|
| `NVIDIA_API_KEY` | *(empty — required when provider is nvidia)* |
| `NVIDIA_BASE_URL` | `https://integrate.api.nvidia.com/v1` |
| `NVIDIA_MODEL` | `nvidia/llama-3.1-nemotron-nano-vl-8b-v1` |
| `NVIDIA_IMAGE_FORMAT` | `image_url` (or `inline_html`) |
| `NVIDIA_MAX_INLINE_IMAGE_BYTES` | `180000` |
| `NVIDIA_PRICE_PER_MILLION_INPUT_TOKENS` | `0` (→ "unpriced") |
| `NVIDIA_PRICE_PER_MILLION_OUTPUT_TOKENS` | `0` |

`NVIDIA_API_KEY` and `NVIDIA_BASE_URL` are shared with the existing chat provider — same
account, same endpoint. `NVIDIA_MODEL` is separate because a VLM and a text model are
different deployments.

### Ollama
| Variable | Default |
|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `OLLAMA_MODEL` | `qwen2.5vl:7b` |

Deliberately distinct from the existing `OLLAMA_HOST`, so document vision can run on a GPU
box while chat stays on the app server. `OLLAMA_BASE_URL` inherits the repo's existing
host-normalisation validator (`0.0.0.0:11434` → `http://localhost:11434`).

### Provider-agnostic call policy
`DOCUMENT_VLM_TIMEOUT_SECONDS` (120), `DOCUMENT_VLM_CONNECT_TIMEOUT_SECONDS` (10),
`DOCUMENT_VLM_MAX_RETRIES` (2), `DOCUMENT_VLM_RETRY_BACKOFF_SECONDS` (0.5),
`DOCUMENT_VLM_MAX_OUTPUT_TOKENS` (4096), `DOCUMENT_VLM_TEMPERATURE` (0.0),
`DOCUMENT_VLM_MAX_FILE_SIZE_MB` (20), `DOCUMENT_VLM_MAX_PAGES` (8),
`DOCUMENT_VLM_HEALTH_TIMEOUT_SECONDS` (10), `DOCUMENT_VLM_PROMPT_VERSION` (`1.0.0`),
`DOCUMENT_OCR_PROVIDER` (`null` \| `tesseract`).

Temperature defaults to **0.0**: extraction is not a creative task, and a deterministic
answer is worth more than a fluent one.

---

## 5. Provider Switching Report

### 5.1 The switch

```bash
# local, private, free
DOCUMENT_VLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5vl:7b

# cloud, faster, priced
DOCUMENT_VLM_PROVIDER=nvidia
NVIDIA_API_KEY=nvapi-…
NVIDIA_MODEL=nvidia/llama-3.1-nemotron-nano-vl-8b-v1
```

Restart. Nothing else. No code change, no rebuild, no ERP change, no schema change, no
prompt change.

### 5.2 How the selection works

`app/adapters/document_vlm/registry.py` maps a name to a `_Registration(factory, describe)`.
`build_document_vlm()` looks up the configured name, calls the factory with the whole
`Settings` object, and verifies conformance (`is_document_vlm`) **at binding time** — an
adapter missing `estimate_cost` fails when the app starts, not mid-upload.

A registry rather than an `if/elif` chain: a chain lives in shared code that every provider
would have to edit. Registration inverts the dependency — the provider depends on the
registry, and the registry never learns the provider's name. The same applies to the
`/vlm/provider` endpoint: each provider registers its own `describe` function, so the
registry has never heard of `nvidia_api_key`.

### 5.3 Adding Claude / Gemini / OpenAI / Qwen Cloud

```python
# app/adapters/document_vlm/claude.py
class ClaudeDocumentVLMAdapter(HttpDocumentVLMAdapter):
    provider = "claude"
    def _endpoint(self): ...
    def _headers(self): ...
    def _body(self, request): ...
    def _read_response(self, data): ...
    async def _probe_health(self): ...

# registration
register_document_vlm_provider("claude", build_claude_adapter, describe=describe_claude_config)
```

Files changed in `app/document_platform/**`: **zero**. Files changed in
`app/api/v1/**`: **zero**. Business logic changed: **none**.

`test_provider_switching.py` proves this rather than asserting it: it registers a fictional
`claude` provider, binds it from configuration, and runs the *entire real pipeline* through
a `gemini` provider that did not exist when the pipeline was written.

### 5.4 Equivalence

`test_pipeline.py::TestSubstitutability` states the claim as an equality: given identical
model output, two different providers produce **byte-identical extraction data and
byte-identical warnings**. Only the `provider` label differs.

---

## 6. Testing Report

**328 tests, all passing, in ~1.3 seconds. No API key, no network, no GPU, no database.**

```
tests/document_vlm/
  conftest.py                    fixtures + ScriptedDocumentVLM + RecordingTransport
  test_ports.py              20  port conformance, DTO invariants
  test_json_repair.py        26  recovery and refusal-to-invent
  test_invoice_schema.py     44  normalisation, coercion, rejection, warnings
  test_prompts.py            22  versioning, immutability, rendering
  test_payload.py            16  PDF/image handling, OCR reuse, limits
  test_nvidia_adapter.py     49  request shape, every failure mode, retries, health, cost
  test_ollama_adapter.py     29  same contract, Ollama's wire shape and quirks
  test_pipeline.py           26  end-to-end through a scripted provider
  test_api.py                26  REST contract, error mapping, auth, OpenAPI
  test_observability.py      28  redaction and metrics
  test_architecture.py       20  the regression tests that catch shortcuts
  test_provider_switching.py 22  env-driven selection, caching, future providers
```

### How determinism is achieved

* **`httpx.MockTransport`** injected into adapters (`transport=`) — every status code,
  malformed body and network error is scripted. `RecordingTransport` replays a *sequence*,
  so a retry test can make the second call succeed.
* **Injected `sleep`** (`sleep=`) — retry tests assert `recorded_sleeps == [0.5, 1.0, 2.0]`
  instead of waiting 3.5 seconds.
* **`ScriptedDocumentVLM`** — a `DocumentVLMPort` implementation that answers from a script,
  used wherever the property under test is the platform's behaviour rather than a model's.
* **`Settings(_env_file=None)`** — configuration tests never read the developer's `.env`.
* Temperature 0 and no jitter in backoff — nothing in the design is randomised.

### Coverage by required category

| Required | Where |
|---|---|
| Unit tests | `test_json_repair`, `test_invoice_schema`, `test_prompts`, `test_ports` |
| Provider tests | `test_nvidia_adapter`, `test_ollama_adapter` |
| Mock NVIDIA / Mock Ollama | `RecordingTransport` + `nvidia_response()` / `ollama_response()` |
| Switch provider tests | `test_provider_switching` |
| Configuration tests | `test_provider_switching::TestSelection`, `TestFactory` in both adapter suites |
| Failure tests | 401, 403, 400, 404, 429, 500, 503, non-JSON body, no choices, no content, refusal, JSON array, model-not-pulled |
| Timeout tests | `test_a_timeout_is_classified_as_retryable`, connection failure, per-request budget |
| Retry tests | Bounded count, exponential backoff, `Retry-After`, no-retry on auth and on unparseable output |
| Invoice extraction tests | `test_pipeline` end to end |
| API tests | `test_api` (26) |
| Schema validation tests | `test_invoice_schema` (44) |
| Regression tests | `test_architecture` (20) |

### Existing suites

`tests/vision_os`, `tests/cognitive_*` — **3101 tests, all passing** after these changes
(verified by running them with and without this work in place).
(Note: `tests/integration` and parts of `tests/unit` fail on `ModuleNotFoundError` and a
pytest-asyncio `event_loop` introspection error **before** any of this work; both are
pre-existing. The new suite shadows the root `event_loop` fixture with a function-scoped
one, the same workaround `tests/vision_os/conftest.py` already documents.)

---

## 7. Known Limitations

1. **PDF page rasterisation.** No renderer ships with this build, so PDF pixels come from
   *embedded* images via `pypdf`. This is exactly right for scanned invoices (one full-page
   image per page) and yields only logos for born-digital PDFs — where the text layer is
   authoritative anyway. A PDF that is neither (vector-drawn, no text layer) yields an
   explicit `EmptyDocumentError` rather than a guess. Adding PyMuPDF would close this.

2. **OCR defaults to `NullOcrProvider`.** The platform's existing default records that OCR
   was required without performing it. For image and scanned-PDF uploads the VLM still reads
   the pixels; text-layer-free documents simply reach the model without OCR text.
   `DOCUMENT_OCR_PROVIDER=tesseract` enables real OCR where the binary is installed.

3. **NVIDIA inline image limit.** Images beyond ~180 KB base64 are dropped (with a warning)
   when other content remains. NVIDIA's assets API — a second upload protocol — is not
   implemented. Large single-page scans against NVIDIA will therefore rely on OCR text, or
   surface the provider's own rejection.

4. **No cost table.** `estimate_cost` reports tokens always and money only when rates are
   configured. This is deliberate: an invented price in a budget decision is worse than an
   honest absence.

5. **Single-request extraction.** No batching, no streaming, no async job queue. A 8-page
   scan against a cold cloud model can approach the 120 s default timeout. The platform's
   existing Redis job queue would be the natural home for a `202 Accepted` variant.

6. **Truncation recovers, it does not retry.** A response that hits the output-token ceiling
   is repaired to keep every *complete* field and flagged with a warning. It does not
   automatically re-run with a higher limit — that would double the cost of a document
   silently.

7. **The output-token ceiling is bounded from both sides.** Measured against
   `nvidia/llama-3.1-nemotron-nano-vl-8b-v1`:

   | `DOCUMENT_VLM_MAX_OUTPUT_TOKENS` | Result |
   |---|---|
   | 4096 | ~38 line items before truncation |
   | 8192 (default) | ~80 line items; long invoices need >120 s, hence the 300 s timeout |
   | 16384 | **HTTP 400 on every request** — it is the model's *total* context, shared with the prompt (a page image costs ~4000 prompt tokens) |

   A deployment that raises this must check the target model's context window; the ceiling
   is a completion budget, not a request size.

8. **Long invoices are latency-bound before they are token-bound.** A 55-line invoice runs
   past two minutes on an 8B model. `DOCUMENT_VLM_TIMEOUT_SECONDS` defaults to 300 for that
   reason. Beyond roughly 50 line items this model also begins repeating items — a model
   capability limit, visible in the warnings, not a pipeline defect.

7. **One prompt version ships (`1.0.0`).** The versioning machinery, registration API and
   per-request pinning are complete and tested; only one wording exists so far.

8. **`additional_fields` is unbounded.** Everything a model volunteers outside the schema is
   preserved. That is intentional (discarded output is evidence nobody can review) but means
   a verbose model can inflate the response.

9. **No cross-field business rules.** Totals consistency is reported as *warnings*. Whether a
   3-cent discrepancy blocks a posting is ERP policy, and this platform does not hold ERP
   policy.

---

## 8. Future Extension Points

| Extension | What it takes | What it does **not** touch |
|---|---|---|
| **Claude / Gemini / OpenAI / Qwen Vision** | One adapter module (5 methods) + one `register_document_vlm_provider` call | Platform, pipeline, schema, API, ERP |
| **Other document types** (PO, receipt, delivery order, bank statement) | A schema module + a prompt template; reuse `DocumentExtractionPipeline` | Port, adapters |
| **Prompt A/B testing** | Register `1.1.0`; both versions coexist; every extraction already records which answered | Anything else |
| **Constrained decoding** | `include_json_schema=True` on the prompt provider — Ollama and NVIDIA already forward it | Adapters |
| **Real cost accounting** | Set the `NVIDIA_PRICE_PER_MILLION_*` variables | Code |
| **Provider fallback chain** | A `FallbackDocumentVLMAdapter` that *is itself a `DocumentVLMPort`* wrapping an ordered list, using `error.retryable` to decide | Platform, API |
| **Async extraction** | Enqueue the pipeline call on the existing Redis queue behind a `202` endpoint | Pipeline internals |
| **Page rasterisation** | Swap `_pdf_images` for a renderer | Everything else |
| **Data-residency routing** | `describe_*_config` already reports `data_residency`; a policy could refuse a remote provider at binding time | Adapters |
| **Multi-page batching** | `DocumentPayload.images` is already a sequence; the shape admits it | DTOs |

---

## Final Verification

| Requirement | Status | Evidence |
|---|---|---|
| No UnityWorks architecture modified | ✅ | 3 files touched, all additive (+92/−1); 3101 existing Vision OS + Cognitive tests pass; `TestExistingArchitectureUntouched` |
| Provider selected entirely from env | ✅ | `DOCUMENT_VLM_PROVIDER`; `test_provider_switching::TestSelection` |
| NVIDIA and Ollama implement identical interface | ✅ | `test_ports::TestConformance`; `test_pipeline::TestSubstitutability` |
| API never depends on provider implementation | ✅ | `TestApiDependsOnNeither` — router, schemas name no provider |
| Future providers need no business-logic change | ✅ | `TestFutureProviders` registers `claude`/`gemini`/`qwen` and runs the real pipeline |
| API keys never logged | ✅ | `redact()` chokepoint; `TestAdapterNeverLeaksCredentials` checks errors, health, results, `repr` |
| Errors handled gracefully | ✅ | 11 typed errors; `parse_model_json` never raises; `health()` never raises; telemetry never fails a call |
| Invoice extraction pipeline complete | ✅ | upload → OCR → prompt → port → JSON repair → schema → response |
| ERP integration is one REST API | ✅ | `POST /api/v1/document/extract-invoice`, `X-API-Key` auth |
