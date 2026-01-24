"""
Vector database integration (Qdrant).

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §16.3.3:

Used ONLY for retrieval, never as ground truth.
All vector-derived links must be confirmed structurally before promotion.

Stores embeddings for:
- Propositions
- Implicit opponent propositions
- Concepts (time-indexed)
- Entities (for disambiguation)

Queries to:
- Propose candidate equivalence clusters
- Retrieve cross-document argumentative neighbors
- Detect potential conceptual continuity or drift
- Support entity disambiguation
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from qdrant_client import QdrantClient as QdrantClientLib
from qdrant_client.models import (
    Distance,
    PointStruct,
    QueryResponse,
    VectorParams,
    Filter, FieldCondition, MatchValue,
)
from pydantic_settings import BaseSettings


# =============================================================================
# Configuration
# =============================================================================

class QdrantSettings(BaseSettings):
    """Qdrant connection settings."""

    host: str = "localhost"
    port: int = 6333
    https: bool = False
    api_key: str | None = None

    class Config:
        env_prefix = "GRUNDRISSE_QDRANT_"


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class PropositionVector:
    """Vector representation of a proposition for retrieval."""
    prop_id: str
    text_summary: str
    embedding: list[float]
    doc_id: str | None = None
    concept_labels: list[str] | None = None
    entity_ids: list[str] | None = None
    temporal_scope: str | None = None
    is_implicit_reconstruction: bool = False
    created_at: datetime | None = None

    def to_payload(self) -> dict[str, Any]:
        """Convert to Qdrant payload format."""
        return {
            "prop_id": self.prop_id,
            "text_summary": self.text_summary,
            "doc_id": self.doc_id,
            "concept_labels": self.concept_labels or [],
            "entity_ids": self.entity_ids or [],
            "temporal_scope": self.temporal_scope,
            "is_implicit_reconstruction": self.is_implicit_reconstruction,
            "created_at": self.created_at or datetime.utcnow().isoformat(),
        }


@dataclass
class ConceptVector:
    """Vector representation of a concept for drift detection."""
    concept_id: str
    label_canonical: str
    embedding: list[float]
    gloss: str | None = None
    temporal_scope: str | None = None
    work_id: str | None = None
    created_at: datetime | None = None

    def to_payload(self) -> dict[str, Any]:
        """Convert to Qdrant payload format."""
        return {
            "concept_id": self.concept_id,
            "label_canonical": self.label_canonical,
            "gloss": self.gloss,
            "temporal_scope": self.temporal_scope,
            "work_id": self.work_id,
            "created_at": self.created_at or datetime.utcnow().isoformat(),
        }


@dataclass
class EntityVector:
    """Vector representation of an entity for disambiguation."""
    entity_id: str
    canonical_name: str
    embedding: list[float]
    entity_type: str | None = None
    surface_forms: list[str] | None = None
    created_at: datetime | None = None

    def to_payload(self) -> dict[str, Any]:
        """Convert to Qdrant payload format."""
        return {
            "entity_id": self.entity_id,
            "canonical_name": self.canonical_name,
            "entity_type": self.entity_type,
            "surface_forms": self.surface_forms or [],
            "created_at": self.created_at or datetime.utcnow().isoformat(),
        }


@dataclass
class RetrievedProposition:
    """A proposition retrieved for context."""
    prop_id: str
    text_summary: str
    similarity: float
    doc_id: str | None = None
    concepts: list[str] | None = None
    entities: list[str] | None = None
    temporal_scope: str | None = None
    is_implicit: bool = False

    def to_retrieved_context_format(self, index: int) -> str:
        """
        Format as retrieved context per §5.4.

        Format: "[N] prop_id: "summary" (context metadata)
        """
        metadata_parts = []
        if self.doc_id:
            metadata_parts.append(f"from {self.doc_id}")
        if self.temporal_scope:
            metadata_parts.append(f"period: {self.temporal_scope}")
        if self.is_implicit:
            metadata_parts.append("implicit reconstruction")

        metadata = f" ({', '.join(metadata_parts)})" if metadata_parts else ""
        return f"[{index}] {self.prop_id}: \"{self.text_summary}\"{metadata}"


@dataclass
class RetrievalResult:
    """Result of a retrieval operation."""
    propositions: list[RetrievedProposition]
    trigger_reason: str | None = None
    query_text: str | None = None
    total_candidates: int = 0


# =============================================================================
# Qdrant Client
# =============================================================================

class QdrantClient:
    """
    Qdrant client for semantic retrieval per §16.3.3.

    Stores embeddings for propositions, concepts, and entities.
    Used for retrieval only - all links must be confirmed structurally.
    """

    # Collection names per §16.3.3
    PROPOSITIONS = "propositions"
    CONCEPTS = "concepts"
    ENTITIES = "entities"

    def __init__(self, settings: QdrantSettings | None = None):
        self.settings = settings or QdrantSettings()
        self._client: QdrantClientLib | None = None

    def connect(self) -> None:
        """Establish connection to Qdrant."""
        url = f"{'https' if self.settings.https else 'http'}://{self.settings.host}:{self.settings.port}"
        self._client = QdrantClientLib(
            url=url,
            api_key=self.settings.api_key,
        )

    def close(self) -> None:
        """Close the connection."""
        self._client = None

    def __enter__(self) -> "QdrantClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def verify_connectivity(self) -> bool:
        """Verify that the connection is working."""
        if not self._client:
            return False
        try:
            collections = self._client.get_collections()
            return collections is not None
        except Exception:
            return False

    # =========================================================================
    # Schema Initialization
    # =========================================================================

    def initialize_collections(self, vector_size: int = 384) -> None:
        """
        Create collections if they don't exist.

        Per §16.3.3: Stores propositions, concepts, entities.
        """
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        for collection_name in [self.PROPOSITIONS, self.CONCEPTS, self.ENTITIES]:
            try:
                self._client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=vector_size,
                        distance=Distance.COSINE,
                    ),
                )
            except Exception:
                # Collection likely exists
                pass

    # =========================================================================
    # Proposition Operations
    # =========================================================================

    def upsert_proposition(self, prop: PropositionVector) -> None:
        """
        Insert or update a proposition embedding.

        Args:
            prop: PropositionVector with embedding and metadata
        """
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        # Use hash of prop_id as point ID
        point_id = hash(prop.prop_id) & 0xFFFFFFFFFFFFFFFF

        self._client.upsert(
            collection_name=self.PROPOSITIONS,
            points=[
                PointStruct(
                    id=point_id,
                    vector=prop.embedding,
                    payload=prop.to_payload(),
                )
            ],
        )

    def upsert_propositions(self, props: list[PropositionVector]) -> None:
        """Batch insert or update proposition embeddings."""
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        points = [
            PointStruct(
                id=hash(p.prop_id) & 0xFFFFFFFFFFFFFFFF,
                vector=p.embedding,
                payload=p.to_payload(),
            )
            for p in props
        ]

        self._client.upsert(
            collection_name=self.PROPOSITIONS,
            points=points,
        )

    def search_propositions(
        self,
        query_embedding: list[float],
        limit: int = 10,
        score_threshold: float = 0.7,
        doc_id: str | None = None,
        exclude_prop_ids: list[str] | None = None,
    ) -> list[RetrievedProposition]:
        """
        Search for similar propositions by vector similarity.

        Args:
            query_embedding: Query vector
            limit: Maximum results to return
            score_threshold: Minimum similarity score (0-1)
            doc_id: Optional filter to specific document
            exclude_prop_ids: Proposition IDs to exclude (e.g., current window)

        Returns:
            List of RetrievedProposition sorted by similarity
        """
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        # Build filter
        filter_conditions = []

        if doc_id:
            filter_conditions.append(
                FieldCondition(key="doc_id", match=MatchValue(value=doc_id))
            )

        if exclude_prop_ids:
            # Note: Qdrant doesn't support "not in" directly
            # We filter results after search
            pass

        search_filter = Filter(must=filter_conditions) if filter_conditions else None

        results = self._client.search(
            collection_name=self.PROPOSITIONS,
            query_vector=query_embedding,
            limit=limit * 2,  # Fetch more to filter
            query_filter=search_filter,
            score_threshold=score_threshold,
        )

        # Convert to RetrievedProposition
        propositions = []
        for result in results:
            prop_id = result.payload.get("prop_id", "")
            if exclude_prop_ids and prop_id in exclude_prop_ids:
                continue

            propositions.append(
                RetrievedProposition(
                    prop_id=prop_id,
                    text_summary=result.payload.get("text_summary", ""),
                    similarity=result.score,
                    doc_id=result.payload.get("doc_id"),
                    concepts=result.payload.get("concept_labels", []),
                    entities=result.payload.get("entity_ids", []),
                    temporal_scope=result.payload.get("temporal_scope"),
                    is_implicit=result.payload.get("is_implicit_reconstruction", False),
                )
            )

            if len(propositions) >= limit:
                break

        return propositions

    def search_by_concepts(
        self,
        concept_labels: list[str],
        limit: int = 10,
        doc_id: str | None = None,
        exclude_prop_ids: list[str] | None = None,
    ) -> list[RetrievedProposition]:
        """
        Search for propositions by concept overlap.

        Per §5.2: Retrieved context selected by concept overlap.

        Args:
            concept_labels: Concepts to search for
            limit: Maximum results
            doc_id: Optional document filter
            exclude_prop_ids: Propositions to exclude

        Returns:
            Propositions containing the specified concepts
        """
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        # Build filter for concept overlap
        # A proposition matches if any of its concepts are in the search list
        filter_conditions = []

        for concept in concept_labels:
            filter_conditions.append(
                FieldCondition(key="concept_labels", match=MatchValue(value=concept))
            )

        if doc_id:
            filter_conditions.append(
                FieldCondition(key="doc_id", match=MatchValue(value=doc_id))
            )

        # Use scroll to get all matches (not a vector search)
        from qdrant_client.models import ScrollRequest

        # Note: This is a simplified approach using scroll
        # For production, consider more sophisticated concept overlap scoring
        results = []
        try:
            # Use scroll with filter
            records, _ = self._client.scroll(
                collection_name=self.PROPOSITIONS,
                limit=limit * 2,
                filter=Filter(must=filter_conditions) if filter_conditions else None,
            )

            for record in records:
                prop_id = record.payload.get("prop_id", "")
                if exclude_prop_ids and prop_id in exclude_prop_ids:
                    continue

                # Calculate overlap score
                prop_concepts = set(record.payload.get("concept_labels", []))
                query_concepts = set(concept_labels)
                overlap = len(prop_concepts & query_concepts)
                if overlap > 0:
                    results.append(
                        RetrievedProposition(
                            prop_id=prop_id,
                            text_summary=record.payload.get("text_summary", ""),
                            similarity=float(overlap) / len(query_concepts),  # Overlap ratio
                            doc_id=record.payload.get("doc_id"),
                            concepts=record.payload.get("concept_labels", []),
                            entities=record.payload.get("entity_ids", []),
                            temporal_scope=record.payload.get("temporal_scope"),
                            is_implicit=record.payload.get("is_implicit_reconstruction", False),
                        )
                    )

            # Sort by overlap score
            results.sort(key=lambda r: r.similarity, reverse=True)
            return results[:limit]

        except Exception:
            # Fallback: empty results
            return []

    # =========================================================================
    # Concept Operations (for drift detection)
    # =========================================================================

    def upsert_concept(self, concept: ConceptVector) -> None:
        """Insert or update a concept embedding."""
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        point_id = hash(f"concept_{concept.concept_id}") & 0xFFFFFFFFFFFFFFFF

        self._client.upsert(
            collection_name=self.CONCEPTS,
            points=[
                PointStruct(
                    id=point_id,
                    vector=concept.embedding,
                    payload=concept.to_payload(),
                )
            ],
        )

    def search_similar_concepts(
        self,
        query_embedding: list[float],
        limit: int = 5,
        work_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for similar concepts (for drift detection).

        Per §16.3.3: Detect potential conceptual continuity or drift.
        """
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        filter_conditions = []
        if work_id:
            filter_conditions.append(
                FieldCondition(key="work_id", match=MatchValue(value=work_id))
            )

        search_filter = Filter(must=filter_conditions) if filter_conditions else None

        results = self._client.search(
            collection_name=self.CONCEPTS,
            query_vector=query_embedding,
            limit=limit,
            query_filter=search_filter,
        )

        return [
            {
                "concept_id": r.payload.get("concept_id"),
                "label_canonical": r.payload.get("label_canonical"),
                "gloss": r.payload.get("gloss"),
                "similarity": r.score,
                "temporal_scope": r.payload.get("temporal_scope"),
            }
            for r in results
        ]

    # =========================================================================
    # Entity Operations (for disambiguation)
    # =========================================================================

    def upsert_entity(self, entity: EntityVector) -> None:
        """Insert or update an entity embedding."""
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        point_id = hash(f"entity_{entity.entity_id}") & 0xFFFFFFFFFFFFFFFF

        self._client.upsert(
            collection_name=self.ENTITIES,
            points=[
                PointStruct(
                    id=point_id,
                    vector=entity.embedding,
                    payload=entity.to_payload(),
                )
            ],
        )

    def search_similar_entities(
        self,
        query_embedding: list[float],
        limit: int = 5,
        entity_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for similar entities (for disambiguation).

        Per §16.3.3: Support entity disambiguation.
        """
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        filter_conditions = []
        if entity_type:
            filter_conditions.append(
                FieldCondition(key="entity_type", match=MatchValue(value=entity_type))
            )

        search_filter = Filter(must=filter_conditions) if filter_conditions else None

        results = self._client.search(
            collection_name=self.ENTITIES,
            query_vector=query_embedding,
            limit=limit,
            query_filter=search_filter,
        )

        return [
            {
                "entity_id": r.payload.get("entity_id"),
                "canonical_name": r.payload.get("canonical_name"),
                "entity_type": r.payload.get("entity_type"),
                "surface_forms": r.payload.get("surface_forms", []),
                "similarity": r.score,
            }
            for r in results
        ]

    # =========================================================================
    # Deletion Operations
    # =========================================================================

    def delete_proposition(self, prop_id: str) -> None:
        """Delete a proposition embedding."""
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        point_id = hash(prop_id) & 0xFFFFFFFFFFFFFFFF
        self._client.delete(
            collection_name=self.PROPOSITIONS,
            points_selector=[point_id],
        )

    def delete_by_document(self, doc_id: str) -> None:
        """Delete all embeddings for a document."""
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        from qdrant_client.models import Filter, FieldCondition, MatchValue

        # Delete from propositions collection
        self._client.delete(
            collection_name=self.PROPOSITIONS,
            points_selector=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
        )

        # Note: Concepts and entities are shared across documents
        # They should only be deleted if no longer referenced anywhere


__all__ = [
    "QdrantSettings",
    "QdrantClient",
    "PropositionVector",
    "ConceptVector",
    "EntityVector",
    "RetrievedProposition",
    "RetrievalResult",
]
