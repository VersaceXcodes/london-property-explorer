from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "London Property Explorer API"
    environment: str = "development"
    database_url: str | None = None
    local_sqlite_path: Path | None = Path("data/local/lpe-local.sqlite3")
    frontend_origin: str = "http://localhost:5174"
    max_points: int = Field(default=25_000, ge=1, le=100_000)
    cell_px: int = Field(default=32, ge=24, le=64)
    cluster_zoom_threshold: int = 12
    statement_timeout_seconds: float = 5.0
    log_level: str = "INFO"

    ai_provider: Literal["anthropic", "openrouter"] = "anthropic"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5"
    openrouter_api_key: str | None = None
    openrouter_model: str = "anthropic/claude-sonnet-4.5"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_app_url: str | None = None
    openrouter_app_title: str = "London Property Explorer"
    pinecone_api_key: str | None = None
    pinecone_index: str = "lpe-knowledge-v1"
    pinecone_namespace: str = "official-evidence-v1"
    pinecone_embed_model: str = "llama-text-embed-v2"
    pinecone_rerank_model: str = "bge-reranker-v2-m3"
    langsmith_api_key: str | None = None
    langsmith_project: str = "london-property-explorer"
    langsmith_tracing: bool = False
    anthropic_input_cost_per_million: float = Field(default=1.0, ge=0)
    anthropic_output_cost_per_million: float = Field(default=5.0, ge=0)
    agent_hard_cost_limit_usd: float = Field(default=0.08, gt=0)
    agent_timeout_seconds: float = Field(default=25.0, gt=0, le=60)

    @field_validator(
        "database_url",
        "local_sqlite_path",
        "anthropic_api_key",
        "openrouter_api_key",
        "openrouter_app_url",
        "pinecone_api_key",
        "langsmith_api_key",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def ai_enabled(self) -> bool:
        if self.ai_provider == "openrouter":
            return bool(self.openrouter_api_key)
        return bool(self.anthropic_api_key)

    @property
    def rag_enabled(self) -> bool:
        return bool(self.pinecone_api_key)

    @property
    def tracing_enabled(self) -> bool:
        return self.langsmith_tracing and bool(self.langsmith_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
