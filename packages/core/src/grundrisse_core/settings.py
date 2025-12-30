from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRUNDRISSE_", extra="ignore")

    database_url: str = "postgresql+psycopg://grundrisse:grundrisse@localhost:5432/grundrisse"


settings = Settings()
