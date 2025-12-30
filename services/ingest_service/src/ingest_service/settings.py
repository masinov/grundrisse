from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRUNDRISSE_", extra="ignore")

    database_url: str = "postgresql+psycopg://grundrisse:grundrisse@localhost:5432/grundrisse"
    data_dir: Path = Path("data")
    user_agent: str = "grundrisse-ingest/0.1 (provenance-first research crawler)"
    request_timeout_s: float = 30.0
    max_bytes: int = 20_000_000
    crawl_max_pages: int = 200
    crawl_delay_s: float = 0.25


settings = Settings()
