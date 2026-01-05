"""API configuration from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """API settings loaded from environment."""

    database_url: str = "postgresql://grundrisse:grundrisse@localhost:5432/grundrisse"
    cors_origins: str = "http://localhost:3000"
    debug: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    model_config = {"env_prefix": "API_", "env_file": ".env"}


settings = Settings()
