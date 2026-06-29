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

    # ── MSSQL ────────────────────────────────────────────────────────────────
    db_host: str = "localhost"
    db_port: int = 1433
    db_name: str = "ai_coding_assistant"
    db_user: str = "sa"
    db_password: SecretStr = SecretStr("YourStrong!Password123")
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
    chroma_port: int = 8001
    chroma_auth_token: SecretStr = SecretStr("")

    # ── Ollama ───────────────────────────────────────────────────────────────
    ollama_host: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen2.5-coder:7b"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_timeout: int = 120
    ollama_max_retries: int = 3

    # ── Indexing ─────────────────────────────────────────────────────────────
    index_max_file_size_mb: int = 1
    index_embed_batch_size: int = 32
    index_parallel_workers: int = 4
    index_skip_patterns: str = "node_modules,.git,__pycache__,*.pyc,*.min.js,dist,build"

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
            f"mssql+aioodbc://{self.db_user}:{pwd}@{self.db_host}:{self.db_port}"
            f"/{self.db_name}?driver=ODBC+Driver+17+for+SQL+Server"
            f"&TrustServerCertificate=yes"
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
