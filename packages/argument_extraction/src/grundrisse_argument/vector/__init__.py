"""
Vector database integration (Qdrant).

Used for semantic candidate generation, NOT as ground truth.
All vector-derived links must be confirmed structurally.
"""

from typing import Optional, List, Dict, Any
from pydantic import SecretStr

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from pydantic_settings import BaseSettings


class QdrantSettings(BaseSettings):
    """Qdrant connection settings."""

    host: str = "localhost"
    port: int = 6333
    https: bool = False
    api_key: Optional[SecretStr] = None

    class Config:
        env_prefix = "GRUNDRISSE_QDRANT_"


class QdrantClient:
    """
    Qdrant client for semantic retrieval.

    Stores embeddings for:
    - Propositions
    - Concepts (time-indexed)
    - Entities (for disambiguation)
    """

    # Collection names
    PROPOSITIONS = "propositions"
    CONCEPTS = "concepts"
    ENTITIES = "entities"

    def __init__(self, settings: Optional[QdrantSettings] = None):
        self.settings = settings or QdrantSettings()
        self._client: Optional[QdrantClient] = None

    def connect(self):
        """Establish connection to Qdrant."""
        url = f"{'https' if self.settings.https else 'http'}://{self.settings.host}:{self.settings.port}"
        self._client = QdrantClient(
            url=url,
            api_key=self.settings.api_key.get_secret_value() if self.settings.api_key else None,
        )

    def close(self):
        """Close the connection."""
        # Qdrant client doesn't need explicit closing
        pass

    def initialize_collections(self, vector_size: int = 384):
        """Create collections if they don't exist."""
        for collection_name in [self.PROPOSITIONS, self.CONCEPTS, self.ENTITIES]:
            try:
                self._client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                )
            except Exception:
                # Collection likely exists
                pass

    # TODO: Implement CRUD operations
    # - upsert_proposition()
    # - upsert_concept()
    # - search_neighbors()
    # - delete_points()
