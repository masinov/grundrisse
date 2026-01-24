"""
Configuration settings for the argument pipeline.

Environment variables:
    GRUNDRISSE_NEO4J_URI         Neo4j Bolt connection URI
    GRUNDRISSE_NEO4J_USER        Neo4j username
    GRUNDRISSE_NEO4J_PASSWORD    Neo4j password
    GRUNDRISSE_QDRANT_HOST       Qdrant host
    GRUNDRISSE_QDRANT_PORT       Qdrant port
    GRUNDRISSE_QDRANT_API_KEY    Qdrant API key (optional)
    GRUNDRISSE_EMBEDDING_MODEL   Sentence transformer model
    GRUNDRISSE_EMBEDDING_DEVICE   Device for embeddings (cpu/cuda)
    GRUNDRISSE_SPACY_MODEL       spaCy model for NER
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Argument pipeline settings."""

    model_config = SettingsConfigDict(env_prefix="GRUNDRISSE_")

    # Neo4j settings
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "grundrisse"

    # Qdrant settings
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str | None = None

    # Embedding settings
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"

    # Entity recognition settings
    spacy_model: str = "en_core_web_trf"

    # LLM settings (reuse from nlp_pipeline)
    zai_api_key: str | None = None
    zai_base_url: str = "https://api.z.ai/api/paas/v4"
    zai_model: str = "glm-4.7"
    zai_timeout_s: float = 60.0

    # Pipeline settings
    window_min_paragraphs: int = 2
    window_max_paragraphs: int = 6
    window_overlap_paragraphs: int = 1

    # Validation settings
    max_retries: int = 3
    stability_threshold: float = 0.7


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
