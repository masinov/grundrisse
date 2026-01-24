"""
Vector embeddings for semantic retrieval.

Encodes propositions, concepts, and entities for vector similarity search.
"""

from typing import List, Optional
import numpy as np


class EmbeddingEncoder:
    """
    Sentence encoder using sentence-transformers.

    Encodes:
    - Propositions (for retrieval and equivalence detection)
    - Concepts (for drift detection)
    - Entities (for disambiguation)
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._model = None

    def load_model(self):
        """Load the sentence transformer model."""
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        except Exception as e:
            raise ImportError(
                f"Failed to load sentence transformer model: {e}\n"
                f"Install with: pip install sentence-transformers"
            )

    def encode(self, texts: List[str]) -> List[np.ndarray]:
        """
        Encode texts to vector embeddings.

        Args:
            texts: List of text strings to encode

        Returns:
            List of embedding vectors
        """
        if not self._model:
            self.load_model()

        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()

    def encode_single(self, text: str) -> np.ndarray:
        """Encode a single text to vector embedding."""
        return self.encode([text])[0]

    @property
    def dimension(self) -> int:
        """Get the embedding dimension."""
        if not self._model:
            self.load_model()
        return self._model.get_sentence_embedding_dimension()

    # TODO: Implement caching for frequently encoded texts
    # - cached_encode()
    # - invalidate_cache()
