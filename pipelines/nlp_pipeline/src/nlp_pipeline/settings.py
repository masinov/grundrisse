from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GRUNDRISSE_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    database_url: str = "postgresql+psycopg://grundrisse:grundrisse@localhost:5432/grundrisse"

    zai_api_key: str | None = None
    # For some Z.ai accounts, resources are split by endpoint prefix. Examples:
    # - general: https://api.z.ai/api/paas/v4
    # - coding:  https://api.z.ai/api/coding/paas/v4
    zai_base_url: str = "https://api.z.ai/api/paas/v4"
    zai_model: str = "glm-4.7"
    zai_timeout_s: float = 60.0
    zai_thinking_enabled: bool = False
    zai_response_format_json: bool = True

    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048


settings = Settings()
