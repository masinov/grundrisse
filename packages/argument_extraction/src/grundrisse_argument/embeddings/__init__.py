"""
Vector embeddings for semantic retrieval.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §16.3.3:

Encodes propositions, concepts, and entities for vector similarity search.
Uses Z.ai GLM embedding API for consistency with LLM provider.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic_settings import BaseSettings


# =============================================================================
# Configuration
# =============================================================================

class EmbeddingSettings(BaseSettings):
    """Z.ai embedding API settings."""

    api_key: str
    base_url: str = "https://api.z.ai/api/paas/v4"
    model: str = "embedding-2"
    timeout: float = 30.0
    dimension: int = 1024  # Default for embedding-2

    class Config:
        env_prefix = "GRUNDRISSE_EMBEDDING_"


# =============================================================================
# Embedding Encoder
# =============================================================================

class EmbeddingEncoder:
    """
    Z.ai GLM embedding encoder.

    Encodes:
    - Propositions (for retrieval and equivalence detection)
    - Concepts (for drift detection)
    - Entities (for disambiguation)
    """

    def __init__(self, settings: EmbeddingSettings | None = None):
        self.settings = settings or EmbeddingSettings()
        self._dimension = self.settings.dimension

    @property
    def dimension(self) -> int:
        """Get the embedding dimension."""
        return self._dimension

    def encode(self, texts: list[str]) -> list[list[float]]:
        """
        Encode texts to vector embeddings.

        Args:
            texts: List of text strings to encode

        Returns:
            List of embedding vectors
        """
        import httpx

        embeddings = []
        batch_size = 10  # Z.ai typically allows multiple texts per request

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = self._encode_batch(batch)
            embeddings.extend(response)

        return embeddings

    def encode_single(self, text: str) -> list[float]:
        """Encode a single text to vector embedding."""
        result = self.encode([text])
        return result[0] if result else []

    def _encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode a batch of texts."""
        import httpx

        if not texts:
            return []

        url = f"{self.settings.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.settings.model,
            "input": texts,
            "encoding_format": "float",
        }

        try:
            with httpx.Client(timeout=self.settings.timeout) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

                # Extract embeddings from response
                # Z.ai format: {"data": [{"embedding": [...], "index": 0}, ...]}
                embeddings = []
                if "data" in data:
                    # Sort by index to ensure order is preserved
                    sorted_data = sorted(data["data"], key=lambda x: x.get("index", 0))
                    embeddings = [item["embedding"] for item in sorted_data]
                elif "embedding" in data:
                    # Single embedding returned
                    embeddings = [data["embedding"]]

                return embeddings

        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Embedding API error: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            raise RuntimeError(f"Embedding request failed: {e}")

    def encode_proposition(
        self,
        text_summary: str,
        concept_labels: list[str] | None = None,
        entity_ids: list[str] | None = None,
    ) -> list[float]:
        """
        Encode a proposition with its semantic context.

        Includes concepts and entities for better semantic retrieval.
        """
        # Build enriched text for encoding
        parts = [text_summary]

        if concept_labels:
            parts.append(f"Concepts: {', '.join(concept_labels)}")

        if entity_ids:
            parts.append(f"Entities: {', '.join(entity_ids)}")

        enriched_text = " | ".join(parts)
        return self.encode_single(enriched_text)

    def encode_concept(
        self,
        label: str,
        gloss: str | None = None,
        temporal_scope: str | None = None,
    ) -> list[float]:
        """Encode a concept with its definition."""
        parts = [label]

        if gloss:
            parts.append(f"Definition: {gloss}")

        if temporal_scope:
            parts.append(f"Period: {temporal_scope}")

        text = " | ".join(parts)
        return self.encode_single(text)

    def encode_entity(
        self,
        name: str,
        entity_type: str | None = None,
    ) -> list[float]:
        """Encode an entity for disambiguation."""
        parts = [name]

        if entity_type:
            parts.append(f"Type: {entity_type}")

        text = " | ".join(parts)
        return self.encode_single(text)


# =============================================================================
# Convenience Functions
# =============================================================================

def create_embedding_encoder(api_key: str | None = None) -> EmbeddingEncoder:
    """
    Create an embedding encoder with default settings.

    Args:
        api_key: Optional API key (otherwise from env var)
    """
    settings = EmbeddingSettings() if not api_key else EmbeddingSettings(api_key=api_key)
    return EmbeddingEncoder(settings)


__all__ = [
    "EmbeddingSettings",
    "EmbeddingEncoder",
    "create_embedding_encoder",
]
