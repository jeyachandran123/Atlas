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
    nvidia_chat_model: str = "deepseek-ai/deepseek-v4-pro"
    nvidia_temperature: float = 1.0
    nvidia_top_p: float = 0.95
    nvidia_max_tokens: int = 16384

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

    @field_validator("ollama_host", mode="before")
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
