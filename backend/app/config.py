from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings from environment variables or .env."""

    # Reads the repo-root .env when run from backend/ (local dev); platform env vars win in prod.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://ritam:ritam@localhost:5432/ritam"
    # Empty = no Redis: jobs run in-process (Render free tier). Set it to use the ARQ worker.
    redis_url: str | None = "redis://localhost:6379/0"

    # Neo4j is a read projection rebuilt from Postgres; the core works without it.
    neo4j_uri: str | None = "bolt://localhost:7687"
    # Aura calls it NEO4J_USERNAME; the value is the instance id.
    neo4j_user: str = Field(
        default="neo4j", validation_alias=AliasChoices("NEO4J_USERNAME", "NEO4J_USER")
    )
    neo4j_password: SecretStr | None = None
    # Aura HTTPS Query API (port 443): used if the bolt port (7687) is unreachable.
    neo4j_query_api_url: str | None = None

    gemini_api_key: SecretStr | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    # Backup providers; routes without a key are skipped.
    groq_api_key: SecretStr | None = None
    mistral_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    # Optional web search for source discovery.
    tavily_api_key: SecretStr | None = None
    search_daily_budget: int = 30  # Tavily calls per day (free plan: 1,000/month)

    # Fallback order per task. Extraction sends whole documents, so large-context routes come
    # first; Groq's small free TPM makes it a backup for short reasoning calls.
    llm_extract_chain: list[str] = [
        "gemini:gemini-3.5-flash-lite",
        "gemini:gemini-3.5-flash",
        "mistral:ministral-14b-latest",
        "gemini:gemini-2.5-flash",
        "mistral:mistral-large-4",
        "groq:openai/gpt-oss-120b",
        "gemini:gemma-4-31b-it",
        "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free",
    ]
    llm_reason_chain: list[str] = [
        "gemini:gemini-3.5-flash",
        "groq:openai/gpt-oss-120b",
        "mistral:mistral-large-4",
        "gemini:gemini-2.5-flash",
        "groq:qwen/qwen3.8-27b",
        "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free",
    ]
    # Requests per minute per route in this process; override with LLM_RPM.
    llm_rpm: dict[str, int] = {"gemini": 10, "groq": 30, "mistral": 50, "openrouter": 20}
    llm_timeout_s: float = 60.0
    # Daily call budget per provider (well under each free quota). Routes over budget are skipped;
    # when all are within `llm_reserve_fraction` of their budget, new live audits are refused.
    llm_daily_budget: dict[str, int] = {
        "gemini": 400,
        "groq": 300,
        "mistral": 300,
        "openrouter": 40,
    }
    llm_reserve_fraction: float = 0.15
    llm_max_attempts_per_route: int = 3

    raw_store_dir: str = "data/raw"
    # JavaScript-only pages: auto = Playwright if installed, else Jina Reader (remote rendering).
    js_fallback: Literal["auto", "playwright", "jina", "none"] = "auto"
    max_upload_bytes: int = 20 * 1024 * 1024
    max_pdf_pages: int = 80
    max_text_chars: int = 200_000
    parse_timeout_s: float = 30.0

    cors_origins: list[str] = ["http://localhost:3000"]
    # e.g. r"https://ritam(-[a-z0-9-]+)?\.vercel\.app" to allow Vercel production + previews
    cors_origin_regex: str | None = None
    # Shared secret for /internal/* (scheduled jobs). Empty disables those endpoints.
    internal_token: SecretStr | None = None
    # Neon can take a few seconds to wake from suspend.
    dependency_timeout_s: float = 6.0

    @field_validator("redis_url", "cors_origin_regex")
    @classmethod
    def _empty_is_none(cls, v: str | None) -> str | None:
        return v or None

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, v: str) -> str:
        from app.db import normalize_database_url

        return normalize_database_url(v)


@lru_cache
def get_settings() -> Settings:
    return Settings()
