"""
Application configuration.

All settings are loaded from environment variables or a .env file.
SecretStr fields are never logged or included in repr().
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_env: Literal["development", "production", "test"] = "development"
    app_host: str = "0.0.0.0"  # noqa: S104
    app_port: int = 8000
    app_debug: bool = False
    secret_key: SecretStr = SecretStr("change-me")

    # ── Cognitive Operating System integration (Version 1) ───────────────────
    # When False (default) the existing chat pipeline is completely unchanged.
    # When True, the Conversation Platform routes through the Cognitive OS brain.
    cognitive_brain_enabled: bool = True

    # ── Auth ─────────────────────────────────────────────────────────────────
    jwt_algorithm: str = "HS256"
    jwt_private_key_path: str = "./infra/keys/private.pem"
    jwt_public_key_path: str = "./infra/keys/public.pem"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    # ── PostgreSQL ───────────────────────────────────────────────────────────
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "ai_coding_assistant"
    db_user: str = "postgres"
    db_password: SecretStr = SecretStr("postgres")
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # TLS to Postgres, in libpq's sslmode terms. Managed Postgres (Neon) needs
    # "require"; the local Docker Postgres has no TLS, so "disable" there.
    # "prefer" tries TLS and falls back, so a missing setting breaks neither.
    db_ssl_mode: Literal["disable", "prefer", "require", "verify-ca", "verify-full"] = "prefer"

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: SecretStr = SecretStr("")
    redis_ssl: bool = False
    redis_db: int = 0
    redis_max_connections: int = 50

    # ── ChromaDB ─────────────────────────────────────────────────────────────
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_auth_token: SecretStr = SecretStr("")
    # Chroma Cloud, or any server behind TLS and a token: CHROMA_HOST=api.trychroma.com,
    # CHROMA_PORT=443, CHROMA_SSL=true, plus the CHROMA_API_KEY / CHROMA_TENANT /
    # CHROMA_DATABASE the Chroma dashboard shows. Unset, a local server is used as before.
    chroma_ssl: bool = False
    chroma_api_key: SecretStr = SecretStr("")
    chroma_tenant: str = "default_tenant"
    chroma_database: str = "default_database"

    # ── Ollama ───────────────────────────────────────────────────────────────
    # ollama_host: str = "http://localhost:11434"
    ollama_host: str = "http://192.168.6.118:11434"
    # Model per agent mode — swap these to whichever local models you have
    ollama_chat_model: str = "qwen2.5-coder:7b"      # code mode (default)
    ollama_auto_model: str = "llama3.2:3b"            # auto / general chat
    ollama_business_model: str = "llama3.2:3b"        # business mode
    ollama_embed_model: str = "nomic-embed-text"
    ollama_timeout: int = 300          # 5 min — long responses need time
    ollama_max_retries: int = 3
    ollama_num_ctx: int = 16384        # context window (tokens)
    ollama_num_predict: int = 8192     # max output tokens — never truncate
    ollama_chat_temperature: float = 0.3   # slightly creative for richer prose
    ollama_code_temperature: float = 0.15  # more deterministic for code blocks

    # ── LLM Provider ─────────────────────────────────────────────────────────────
    llm_provider: Literal["ollama", "nvidia"] = "nvidia"

    # ── NVIDIA ───────────────────────────────────────────────────────────────────
    nvidia_api_key: SecretStr = SecretStr("")
    # The vision stack carries its own NVIDIA key; the same credential in
    # practice, but named separately so a vision deployment can be rotated
    # without touching the chat one. Either is accepted for code generation.
    vision_nvidia_api_key: SecretStr = SecretStr("")
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    # The two models behind every chat profile in app/llm. Vision has its own
    # model (nvidia_model below); embeddings stay local.
    #   chat      - general, coding, planning, documents, code generation
    #   reasoning - the deep modes a person picks on purpose: reasoning, maths
    # Measured on the hosted tier: Super 120B first token 0.4s, Ultra 550B 167s.
    # Set both to one model to run everything on it; per-profile changes go in
    # LLM_PROFILE_OVERRIDES below.
    nvidia_chat_model: str = "nvidia/nemotron-3-super-120b-a12b"
    nvidia_reasoning_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    nvidia_temperature: float = 1   # 1.0 is a creative-writing setting; it fabricates
    nvidia_top_p: float = 1
    nvidia_max_tokens: int = 4096

    # ── Chat gateway (app/llm) ───────────────────────────────────────────────────
    # Profiles (general, reasoning, math, coding, agent_planning, document,
    # codegen, fast) carry their own temperature, token budget, timeout and
    # thinking default; NVIDIA_TEMPERATURE / NVIDIA_MAX_TOKENS above are no
    # longer consulted by it. Per-profile changes go here, as JSON:
    #   LLM_PROFILE_OVERRIDES={"coding": {"model": "...", "thinking": false}}
    llm_profile_overrides: str = ""
    # Retries for rate limits, timeouts and 5xx. 4xx are never retried.
    llm_max_retries: int = 2
    # Calls in flight at once. The hosted tier limits requests per minute; a
    # burst should queue here briefly rather than fail with 429 all together.
    llm_max_concurrency: int = 8

    # ── Vision ───────────────────────────────────────────────────────────────────
    # Which provider answers chat vision (/chat/stream/vision). Deliberately
    # separate from llm_provider so images can go to a cloud VLM while text chat
    # stays on local Ollama — the same split DOCUMENT_VLM_PROVIDER already allows
    # for invoice extraction. Empty means "follow llm_provider", so a deployment
    # that sets neither behaves exactly as it did before this field existed.
    vision_provider: Literal["", "ollama", "nvidia", "unityworks"] = "nvidia"
    # vision_model: str = "qwen2.5vl:7b"  # Ollama vision model
    vision_model: str = "nvidia/ising-calibration-1.5-31b"  # NVIDIA vision model
    vision_storage_dir: str = "data/vision_uploads"
    vision_max_image_size_mb: int = 20
    vision_max_images_per_message: int = 5

    # ── Attachment Storage ───────────────────────────────────────────────────────
    # local    → files under data/ on this machine (default)
    # s3       → AWS S3 bucket (requires aws_s3_bucket + credentials)
    # firebase → Firebase Storage bucket (requires firebase_storage_bucket)
    storage_backend: Literal["local", "s3", "firebase"] = "local"
    firebase_storage_bucket: str = ""  # e.g. atlas-ai-assistant-1ae91.firebasestorage.app

    # ── AWS S3 ───────────────────────────────────────────────────────────────────
    aws_s3_bucket: str = ""
    aws_region: str = "us-east-1"
    aws_access_key_id: SecretStr = SecretStr("")
    aws_secret_access_key: SecretStr = SecretStr("")

    # ── Documents (PDF / Word / text uploads) ────────────────────────────────────
    document_storage_dir: str = "data/document_uploads"
    document_max_file_size_mb: int = 20
    document_max_per_message: int = 5
    # Max characters of extracted document text injected into the LLM prompt.
    # ~4 chars/token → 24000 chars ≈ 6000 tokens, leaving room in num_ctx=16384.
    document_context_max_chars: int = 24000

    # ── Document Intelligence Platform (Phase 1) ─────────────────────────────────
    dip_max_file_size_mb: int = 50
    dip_signed_url_ttl_seconds: int = 300

    # ── Semantic Intelligence Layer (Phase 3) ────────────────────────────────────
    # Model/endpoint/timeout for the ollama provider reuse the existing
    # ollama_embed_model / ollama_timeout settings above — no duplication.
    # Locally this is nomic-embed-text on Ollama — small (0.3 GB) and fast. A
    # hosted deployment cannot reach that Ollama, so it sets
    # DIP_EMBEDDING_PROVIDER=nvidia and embeds with NVIDIA's hosted model using
    # the chat model's NVIDIA key. Vectors from the two are not interchangeable:
    # switching provider means re-embedding what is already stored.
    dip_embedding_provider: Literal["ollama", "nvidia"] = "ollama"
    nvidia_embed_model: str = "nvidia/nemotron-3-embed-1b"
    dip_embedding_max_retries: int = 3
    dip_vector_store_provider: Literal["chroma"] = "chroma"

    # ── Document VLM (Vision Language Model) ─────────────────────────────────────
    # The Document Platform reaches a VLM only through DocumentVLMPort. Which
    # implementation answers is decided here and nowhere else: changing provider
    # is DOCUMENT_VLM_PROVIDER=<name> and a restart, never a code change.
    #
    # Registering a future provider (claude / gemini / openai / qwen) widens the
    # accepted values through the adapter registry — this field stays a plain str
    # rather than a Literal so a registered provider needs no edit here.
    document_vlm_provider: str = "unityworks"  # nvidia | ollama | unityworks

    # UnityWorks self-hosted VLM (LitServe behind an API key). Serves both
    # DOCUMENT_VLM_PROVIDER=unityworks and VISION_PROVIDER=unityworks.
    #
    # The URL has no default on purpose: a Lightning cloudspace hostname changes
    # whenever the space restarts, so a stale default would point confidently at
    # someone else's deployment rather than failing to start.
    unityworks_base_url: str = ""
    unityworks_api_key: SecretStr = SecretStr("")
    # A label, not a routing key — the deployment serves whatever model it was
    # built with. It exists so telemetry and health have a name to report.
    unityworks_model: str = "unityworks-vlm"

    # NVIDIA cloud VLM. nvidia_api_key / nvidia_base_url are shared with the chat
    # provider above (same account, same endpoint); the *model* is separate
    # because a VLM and a text model are different deployments.
    nvidia_model: str = "nvidia/ising-calibration-1.5-31b"
    # Chat vision (/chat/stream/vision) may need a *different* deployment from
    # document extraction: llama-3.2-11b-vision answers in under a second but
    # rejects any prompt carrying more than one image, which suits chat uploads
    # and not multi-page invoices. Empty means "use nvidia_model".
    nvidia_vision_model: str = ""
    # NVIDIA's vision models disagree about how images arrive: OpenAI-style
    # content parts, or an inline <img src="data:…"/> tag. Configurable rather
    # than guessed.
    nvidia_image_format: Literal["image_url", "inline_html"] = "image_url"
    nvidia_max_inline_image_bytes: int = 180_000
    # Backstop for the model's multimodal embedding budget. Exceeding it returns
    # an opaque HTTP 500, not a degraded answer, so the adapter caps rather than
    # letting the whole extraction fail.
    nvidia_max_images_per_request: int = 4
    # Cost estimation stays honest: unset means "unpriced", never a stale
    # hard-coded rate presented as fact.
    nvidia_price_per_million_input_tokens: float = 0.0
    nvidia_price_per_million_output_tokens: float = 0.0

    # OCR provider for the extraction pipeline's text stage. "null" records
    # that OCR was needed without performing it (the platform default);
    # "tesseract" requires the Tesseract binary on the host.
    document_ocr_provider: Literal["null", "tesseract"] = "null"

    # Ollama local VLM. Kept distinct from ollama_host so the document VLM can
    # point at a different (e.g. GPU) host without moving the chat models.
    # ollama_base_url: str = "http://localhost:11434"
    ollama_base_url: str = "http://192.168.6.118:11434"
    ollama_model: str = "qwen2.5vl:7b"

    # Provider-agnostic call policy — applies to whichever adapter is bound.
    # A long invoice is a long generation: ~100 tokens per line item on an 8B
    # model runs past two minutes well before it runs out of tokens. Matches the
    # 300s the repo already allows Ollama for the same reason.
    document_vlm_timeout_seconds: float = 300.0
    document_vlm_connect_timeout_seconds: float = 10.0
    document_vlm_max_retries: int = 2          # retries *after* the first attempt
    document_vlm_retry_backoff_seconds: float = 0.5
    # Measured at roughly 100 completion tokens per invoice line item: 4096 caps
    # out near 38 lines, and a real supplier invoice regularly exceeds that. A
    # truncated answer is recoverable but lossy, so the ceiling is set where a
    # long invoice fits rather than where a short one does.
    #
    # It cannot simply be maximised: this is the *completion* budget, and it
    # shares a context window with the prompt. Nemotron VL's window is 16384
    # total, and a page image costs ~4000 prompt tokens — so 8192 leaves ample
    # headroom while allowing ~80 line items. Asking for the full window instead
    # produces an immediate HTTP 400 on every request.
    document_vlm_max_output_tokens: int = 32768
    document_vlm_temperature: float = 1.00    # extraction is not a creative task
    document_vlm_max_file_size_mb: int = 20
    # Pages sent to the model per request. Measured against Nemotron VL: each
    # page image costs ~3,330 prompt tokens, and five pages exceed the server's
    # multimodal embedding budget — the request fails outright rather than
    # degrading. Four is what fits. Pages beyond this are reported as a warning
    # on the response, never dropped silently.
    document_vlm_max_pages: int = 4
    document_vlm_health_timeout_seconds: float = 10.0
    document_vlm_prompt_version: str = "1.0.0"

    # ── Conversational Knowledge Intelligence (Phase 4) ──────────────────────────
    # Endpoint/timeout for the ollama LLM provider reuse ollama_host /
    # ollama_timeout / ollama_num_ctx / ollama_num_predict above.
    # The document workspace answers and generates on the self-hosted UnityWorks
    # deployment alone. A Literal of one is the point: local inference on CPU
    # took minutes per answer and streamed with no read timeout, so a slow model
    # left the UI on "Generating answer…" indefinitely. Reads
    # UNITYWORKS_BASE_URL / _API_KEY / _MODEL above.
    dip_llm_provider: Literal["unityworks"] = "unityworks"
    dip_chat_temperature: float = 0.2
    dip_llm_max_retries: int = 2
    # The endpoint answers in one shot and decodes at roughly 11 tokens a
    # second, so this budget is a wait: 8192 tokens is 745s against the 300s
    # ceiling below, which a long generation plan reached as a timeout and
    # the user read as nothing being generated at all. 2048 finishes inside
    # the timeout with room to spare. Conversation answers set their own,
    # smaller ceiling on the prompt; this is the fallback the generation
    # planner uses.
    dip_max_output_tokens: int = 2048
    # A real ceiling, deliberately not None: an unbounded read is what turned a
    # slow model into a spinner that never resolved.
    dip_llm_timeout_seconds: float = 300.0
    dip_retrieval_top_k: int = 8
    dip_context_token_budget: int = 4000
    dip_history_max_turns: int = 6
    # Below this best-hit similarity the platform refuses rather than answers.
    dip_grounding_min_score: float = 0.35

    # Last resort when a correct answer carries no [S#] marker and the model
    # will not add one: the fraction of an answer's content words that must
    # appear in a source before that source is recorded as where it came from.
    # Measured, not guessed. Real grounded summaries of a real document scored
    # 0.64, 0.88 and 0.92 against their source. The failures scored far lower:
    # 0.37 for an answer whose source turned out to be the wrong extraction,
    # 0.29 for a summary carrying invented personal details, 0.18 for an answer
    # about a different document, 0.00 for one from outside knowledge. The gap
    # between 0.37 and 0.64 is where this belongs. A short answer dilutes the
    # score with connective filler - "as indicated by the Class field" - and
    # measured at 0.48 while being entirely correct, so the bar sits below
    # that. It is not the only test: every figure in the passage must also
    # appear in the source, which is what actually separates a summary of
    # this document from a confident summary of a different one.
    dip_attribution_min_support: float = 0.45

    # Drain the document and embedding queues inside the API process as well
    # as (or instead of) the standalone workers. On by default because the
    # failure it prevents is silent and total: with no consumer running, an
    # upload succeeds, the document appears in the sidebar, and every question
    # about it is refused forever for want of a single chunk. Redis gives a
    # queued job to exactly one consumer, so running the standalone workers
    # too is safe - they share the queue rather than duplicating work. Turn
    # this off where the API should serve requests and nothing else.
    dip_inprocess_workers: bool = True

    # Natural-language document tasks: the model writes Python, the sandbox
    # runs it. The image is the one the workers already use - it carries
    # pandas, openpyxl, python-docx and pypdf, so nothing extra is built.
    dip_sandbox_image: str = "ai-coding-assistant:latest"
    dip_sandbox_timeout_seconds: int = 120
    dip_sandbox_memory: str = "2g"
    dip_sandbox_cpus: str = "2"
    # One attempt plus two repairs. A mistyped column is fixed on the first
    # retry; a model still failing on the third has misread the request, and
    # more attempts only make the wait longer.
    dip_task_max_attempts: int = 3

    # The code-writing model follows DOCUMENT_VLM_PROVIDER: 'nvidia' uses the
    # endpoint below, 'unityworks' uses the self-hosted deployment. Measured,
    # same prompt and file and sandbox with only the model varied: the
    # self-hosted 7-8B produced 1251 rows with concatenated codes over three
    # failed attempts; the hosted 31B produced the correct 3136 on the first,
    # in nine seconds.
    dip_codegen_url: str = "https://integrate.api.nvidia.com/v1/chat/completions"
    dip_codegen_model: str = "nvidia/ising-calibration-1.5-31b"
    dip_codegen_timeout_seconds: float = 300.0
    # Sample rows help the model see the shape of the data, and are the only
    # part of the document that would leave the machine. Turn this off and the
    # prompt carries column names and types alone; the rows themselves are
    # never sent either way - they are read inside the offline container.
    dip_codegen_send_samples: bool = True

    @field_validator("ollama_host", "ollama_base_url", mode="before")
    @classmethod
    def normalize_ollama_host(cls, v: str) -> str:
        """Ensure ollama_host always has an http:// prefix.

        Ollama sets OLLAMA_HOST=0.0.0.0:11434 (no protocol) as a system env
        var when running as a service. Pydantic-settings picks that up with
        higher priority than .env, so we normalise it here.
        """
        v = str(v).strip()
        v = v.replace("0.0.0.0", "localhost")
        if v and not v.startswith(("http://", "https://")):
            v = f"http://{v}"
        return v

    # ── Indexing ─────────────────────────────────────────────────────────────
    index_max_file_size_mb: int = 1
    index_embed_batch_size: int = 32
    index_parallel_workers: int = 4
    index_skip_patterns: str = "node_modules,.git,__pycache__,*.pyc,*.min.js,dist,build"

    # ── Multi-tenancy ─────────────────────────────────────────────────────────
    default_org_id: str = "default"
    default_org_name: str = "Atlas"
    default_org_slug: str = "atlas"
    default_org_plan: str = "free"
    default_org_max_repos: int = 10
    default_org_max_users: int = 100
    # Self-service sign-up (name, email, password) into the default org.
    # Addresses are not verified until an email service is configured, so
    # this is the switch to close sign-ups without a code change.
    allow_open_registration: bool = True

    # ── Email (Brevo) ─────────────────────────────────────────────────────────
    # Transactional email for sign-up codes. With no key or no sender, email is
    # off and sign-up creates accounts without verifying the address.
    brevo_api_key: SecretStr = SecretStr("")
    email_sender_address: str = ""   # must be a sender verified in Brevo
    email_sender_name: str = "UnityWorks"
    signup_code_ttl_seconds: int = 600
    signup_resend_cooldown_seconds: int = 60

    # ── Web search (You.com) ──────────────────────────────────────────────────
    # Lets chat answer from the live web. With no key, search is simply off and
    # chat behaves exactly as it did before — never an error.
    web_search_enabled: bool = True
    you_api_key: SecretStr = SecretStr("")
    # You.com's free tier is 100 searches a day. Stopping below it means a busy
    # day degrades to ordinary chat instead of starting a bill.
    web_search_daily_cap: int = 80
    web_search_max_results: int = 6
    web_search_timeout_s: float = 12.0
    web_search_country: str = "SG"

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    rate_limit_chat: str = "20/minute"
    rate_limit_index: str = "5/minute"
    rate_limit_search: str = "60/minute"

    # ── Observability ─────────────────────────────────────────────────────────
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    prometheus_enabled: bool = True
    log_level: str = "INFO"
    log_format: str = "json"

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://localhost:5173,https://atlas-frontend-mauve.vercel.app"

    # ── Computed ─────────────────────────────────────────────────────────────
    @property
    def database_url(self) -> str:
        pwd = self.db_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.db_user}:{pwd}@{self.db_host}:{self.db_port}"
            f"/{self.db_name}"
        )

    @property
    def database_connect_args(self) -> dict[str, str]:
        """asyncpg connection options for the app and migrations alike: TLS per DB_SSL_MODE."""
        return {} if self.db_ssl_mode == "disable" else {"ssl": self.db_ssl_mode}

    @property
    def redis_url(self) -> str:
        pwd = self.redis_password.get_secret_value()
        auth = f":{pwd}@" if pwd else ""
        scheme = "rediss" if self.redis_ssl else "redis"
        return f"{scheme}://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def chroma_url(self) -> str:
        scheme = "https" if self.chroma_ssl else "http"
        return f"{scheme}://{self.chroma_host}:{self.chroma_port}"

    @property
    def nvidia_vision_model_resolved(self) -> str:
        """Model for chat vision: NVIDIA_VISION_MODEL, falling back to NVIDIA_MODEL."""
        return self.nvidia_vision_model or self.nvidia_model

    @property
    def vision_provider_resolved(self) -> str:
        """Provider for chat vision: VISION_PROVIDER, falling back to LLM_PROVIDER."""
        return self.vision_provider or self.llm_provider

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def index_skip_patterns_list(self) -> list[str]:
        return [p.strip() for p in self.index_skip_patterns.split(",") if p.strip()]

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance. Use as a FastAPI dependency."""
    return Settings()


# Module-level singleton for non-dependency-injection contexts
settings = get_settings()

