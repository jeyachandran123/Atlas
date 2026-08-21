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

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: SecretStr = SecretStr("")
    redis_db: int = 0
    redis_max_connections: int = 50

    # ── ChromaDB ─────────────────────────────────────────────────────────────
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_auth_token: SecretStr = SecretStr("")

    # ── Ollama ───────────────────────────────────────────────────────────────
    ollama_host: str = "http://localhost:11434"
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
    llm_provider: Literal["ollama", "nvidia"] = "ollama"

    # ── NVIDIA ───────────────────────────────────────────────────────────────────
    nvidia_api_key: SecretStr = SecretStr("")
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_chat_model: str = "openai/gpt-oss-120b"
    nvidia_temperature: float = 1   # 1.0 is a creative-writing setting; it fabricates
    nvidia_top_p: float = 1
    nvidia_max_tokens: int = 4096

    # ── Vision ───────────────────────────────────────────────────────────────────
    vision_model: str = "qwen2.5vl:7b"  # Ollama vision model
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
    dip_embedding_provider: Literal["ollama"] = "ollama"
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
    document_vlm_provider: str = "ollama"

    # NVIDIA cloud VLM. nvidia_api_key / nvidia_base_url are shared with the chat
    # provider above (same account, same endpoint); the *model* is separate
    # because a VLM and a text model are different deployments.
    nvidia_model: str = "nvidia/llama-3.1-nemotron-nano-vl-8b-v1"
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
    ollama_base_url: str = "http://localhost:11434"
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
    document_vlm_max_output_tokens: int = 8192
    document_vlm_temperature: float = 0.0      # extraction is not a creative task
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
    dip_llm_provider: Literal["ollama"] = "ollama"
    dip_chat_model: str = "qwen3:8b"
    dip_chat_temperature: float = 0.2
    dip_llm_max_retries: int = 2
    dip_retrieval_top_k: int = 8
    dip_context_token_budget: int = 4000
    dip_history_max_turns: int = 6
    # Below this best-hit similarity the platform refuses rather than answers.
    dip_grounding_min_score: float = 0.35

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
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # ── Computed ─────────────────────────────────────────────────────────────
    @property
    def database_url(self) -> str:
        pwd = self.db_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.db_user}:{pwd}@{self.db_host}:{self.db_port}"
            f"/{self.db_name}"
        )

    @property
    def redis_url(self) -> str:
        pwd = self.redis_password.get_secret_value()
        auth = f":{pwd}@" if pwd else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def chroma_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"

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
