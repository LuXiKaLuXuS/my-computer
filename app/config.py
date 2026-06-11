from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "My Computer"
    app_version: str = "1.6.0"
    debug: bool = False
    secret_key: str = "dev-secret-change-in-production"
    database_url: str = "postgresql+asyncpg://postgres@127.0.0.1:5432/postgres"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    algorithm: str = "HS256"
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection_prefix: str = "mycomputer"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    grok_api_key: str = ""
    grok_model: str = "grok-2-latest"
    llm_provider: str = "auto"
    llm_fallback_chain: str = "openai,anthropic,grok,mock"
    embedding_provider: str = "sentence-transformers"
    embedding_model: str = "all-MiniLM-L6-v2"
    rate_limit_per_minute: int = 60
    cors_origins: List[str] = ["http://localhost:8000", "http://localhost:3000"]
    webhook_timeout_seconds: int = 10
    webhook_max_retries: int = 3
    meta_agent_enabled: bool = True
    meta_agent_source_root: str = "/home/lukpak/my-computer"
    meta_agent_require_approval: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()