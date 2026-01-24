"""
Retrieval orchestrator for argument extraction.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §5:

§5.2: Retrieved context from previously processed propositions
      - Selected by concept overlap, vector similarity, definitional tags

§5.3: Mandatory retrieval triggers
      - Conclusion markers without local premises
      - Evaluative claims with missing support

§5.4: Retrieved context presentation (critical)
      - Explicit marking: [RETRIEVED_CONTEXT] prefix
      - Read-only constraint: non-extractible flag
      - Evidence separation: retrieved text cannot be evidence locutions
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from grundrisse_argument.embeddings import EmbeddingEncoder
from grundrisse_argument.vector import (
    QdrantClient,
    RetrievedProposition,
    RetrievalResult,
)


# =============================================================================
# Mandatory Retrieval Triggers (§5.3)
# =============================================================================

CONCLUSION_MARKERS = [
    "therefore", "thus", "it follows", "consequently", "hence",
    "accordingly", "so", "as a result", "for this reason",
    "ergo", "whence", "wherefore", "thence",
]

EVALUATIVE_MARKERS = [
    "this shows", "this proves", "this demonstrates", "this indicates",
    "this reveals", "this establishes", "this confirms",
]

DEFINITIONAL_FORCE_TAGS = ["define", "distinguish", "classify", "categorize"]


@dataclass
class RetrievalConfig:
    """Configuration for retrieval behavior."""
    enabled: bool = True
    top_k: int = 5
    similarity_threshold: float = 0.7
    max_retrieved_contexts: int = 3
    use_vector_search: bool = True
    use_concept_search: bool = True
    enable_mandatory_triggers: bool = True


@dataclass
class RetrievedContext:
    """
    Retrieved context formatted per §5.4.

    Contains both the presentation string and metadata for LLM.
    """
    formatted: str  # The formatted string to present to LLM
    propositions: list[RetrievedProposition]
    trigger_reason: str | None = None
    is_mandatory: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for LLM prompt construction."""
        return {
            "formatted": self.formatted,
            "proposition_ids": [p.prop_id for p in self.propositions],
            "trigger_reason": self.trigger_reason,
            "is_mandatory": self.is_mandatory,
            "count": len(self.propositions),
        }


# =============================================================================
# Retrieval Orchestrator
# =============================================================================

class RetrievalOrchestrator:
    """
    Orchestrates semantic retrieval for argument extraction.

    Per §5.2: Retrieved context from previously processed propositions.
    Per §5.3: Mandatory retrieval when conclusion markers without local premises.
    Per §5.4: Critical presentation format to prevent context poisoning.
    """

    def __init__(
        self,
        qdrant: QdrantClient,
        encoder: EmbeddingEncoder,
        config: RetrievalConfig | None = None,
    ):
        """
        Initialize the retrieval orchestrator.

        Args:
            qdrant: Qdrant client for vector search
            encoder: Embedding encoder for encoding queries
            config: Retrieval configuration
        """
        self.qdrant = qdrant
        self.encoder = encoder
        self.config = config or RetrievalConfig()

        # Pre-compile regex patterns for trigger detection
        self._conclusion_pattern = re.compile(
            r'\b(' + '|'.join(re.escape(m) for m in CONCLUSION_MARKERS) + r')\b',
            re.IGNORECASE
        )
        self._evaluative_pattern = re.compile(
            r'\b(' + '|'.join(re.escape(m) for m in EVALUATIVE_MARKERS) + r')\b',
            re.IGNORECASE
        )

    # =========================================================================
    # Trigger Detection (§5.3)
    # =========================================================================

    def has_conclusion_marker(self, text: str) -> bool:
        """Check if text contains conclusion markers."""
        return bool(self._conclusion_pattern.search(text))

    def has_evaluative_marker(self, text: str) -> bool:
        """Check if text contains evaluative claim markers."""
        return bool(self._evaluative_pattern.search(text))

    def has_mandatory_trigger(
        self,
        window_text: str,
        local_premises_count: int,
    ) -> tuple[bool, str | None]:
        """
        Check if mandatory retrieval is triggered per §5.3.

        Mandatory if window contains conclusion/evaluative markers
        AND no local premises are detected.

        Returns:
            (should_retrieve, reason)
        """
        if not self.config.enable_mandatory_triggers:
            return False, None

        has_conclusion = self.has_conclusion_marker(window_text)
        has_evaluative = self.has_evaluative_marker(window_text)

        if has_conclusion and local_premises_count == 0:
            return True, "conclusion_marker_without_local_premises"

        if has_evaluative and local_premises_count == 0:
            return True, "evaluative_marker_without_local_premises"

        return False, None

    # =========================================================================
    # Retrieval Operations
    # =========================================================================

    def retrieve_for_window(
        self,
        window_text: str,
        window_concepts: list[str] | None = None,
        doc_id: str | None = None,
        exclude_prop_ids: list[str] | None = None,
        force_retrieve: bool = False,
    ) -> RetrievedContext:
        """
        Retrieve relevant propositions for a window.

        Args:
            window_text: The text of the current window
            window_concepts: Concepts found in the window
            doc_id: Current document ID (for cross-document retrieval)
            exclude_prop_ids: Proposition IDs to exclude from results
            force_retrieve: Force retrieval even without triggers

        Returns:
            RetrievedContext with formatted presentation
        """
        if not self.config.enabled:
            return RetrievedContext(
                formatted="",
                propositions=[],
                trigger_reason=None,
                is_mandatory=False,
            )

        # Check for mandatory triggers
        has_trigger, trigger_reason = self.has_mandatory_trigger(
            window_text=window_text,
            local_premises_count=0,  # TODO: Detect from window
        )

        # Only retrieve if mandatory trigger or forced
        if not (has_trigger or force_retrieve):
            return RetrievedContext(
                formatted="",
                propositions=[],
                trigger_reason=None,
                is_mandatory=False,
            )

        # Perform retrieval
        propositions = self._retrieve(
            query_text=window_text,
            concepts=window_concepts or [],
            doc_id=doc_id,
            exclude_prop_ids=exclude_prop_ids,
        )

        # Format per §5.4
        formatted = self._format_retrieved_context(propositions, trigger_reason)

        return RetrievedContext(
            formatted=formatted,
            propositions=propositions,
            trigger_reason=trigger_reason,
            is_mandatory=has_trigger,
        )

    def _retrieve(
        self,
        query_text: str,
        concepts: list[str],
        doc_id: str | None,
        exclude_prop_ids: list[str] | None,
    ) -> list[RetrievedProposition]:
        """
        Internal retrieval combining vector and concept search.
        """
        all_results: dict[str, RetrievedProposition] = {}

        # Vector similarity search
        if self.config.use_vector_search:
            try:
                query_embedding = self.encoder.encode_single(query_text)
                vector_results = self.qdrant.search_propositions(
                    query_embedding=query_embedding,
                    limit=self.config.top_k,
                    score_threshold=self.config.similarity_threshold,
                    doc_id=doc_id,
                    exclude_prop_ids=exclude_prop_ids,
                )
                for prop in vector_results:
                    all_results[prop.prop_id] = prop
            except Exception:
                # Continue with concept search if vector fails
                pass

        # Concept overlap search
        if self.config.use_concept_search and concepts:
            try:
                concept_results = self.qdrant.search_by_concepts(
                    concept_labels=concepts,
                    limit=self.config.top_k,
                    doc_id=doc_id,
                    exclude_prop_ids=exclude_prop_ids,
                )
                for prop in concept_results:
                    # Merge scores if already present
                    if prop.prop_id in all_results:
                        # Average the scores
                        existing = all_results[prop.prop_id]
                        prop.similarity = (existing.similarity + prop.similarity) / 2
                    all_results[prop.prop_id] = prop
            except Exception:
                pass

        # Sort by combined similarity and return top-k
        results = sorted(
            all_results.values(),
            key=lambda r: r.similarity,
            reverse=True,
        )[:self.config.max_retrieved_contexts]

        return results

    def _format_retrieved_context(
        self,
        propositions: list[RetrievedProposition],
        trigger_reason: str | None,
    ) -> str:
        """
        Format retrieved context per §5.4.

        Format:
        --- RETRIEVED CONTEXT (read-only, non-extractible) ---
        [1] prop_id: "summary" (metadata)
        [2] prop_id: "summary" (metadata)
        ...
        """
        if not propositions:
            return ""

        lines = [
            "--- RETRIEVED CONTEXT (read-only, non-extractible) ---",
        ]

        if trigger_reason:
            lines.append(f"Trigger: {trigger_reason}")

        for i, prop in enumerate(propositions, start=1):
            lines.append(prop.to_retrieved_context_format(i))

        lines.append(
            "NOTE: Retrieved propositions above may be cited as premises, "
            "but cannot generate new locutions or serve as evidence locutions."
        )

        return "\n".join(lines)

    # =========================================================================
    # Proposition Indexing (after extraction)
    # =========================================================================

    def index_proposition(
        self,
        prop_id: str,
        text_summary: str,
        concept_labels: list[str] | None = None,
        entity_ids: list[str] | None = None,
        doc_id: str | None = None,
        temporal_scope: str | None = None,
        is_implicit: bool = False,
    ) -> None:
        """
        Index a proposition for retrieval after successful extraction.

        Encodes and stores the proposition in Qdrant.
        """
        from grundrisse_argument.vector import PropositionVector

        # Encode with semantic context
        embedding = self.encoder.encode_proposition(
            text_summary=text_summary,
            concept_labels=concept_labels,
            entity_ids=entity_ids,
        )

        # Create vector record
        prop_vector = PropositionVector(
            prop_id=prop_id,
            text_summary=text_summary,
            embedding=embedding,
            doc_id=doc_id,
            concept_labels=concept_labels,
            entity_ids=entity_ids,
            temporal_scope=temporal_scope,
            is_implicit_reconstruction=is_implicit,
        )

        # Store in Qdrant
        self.qdrant.upsert_proposition(prop_vector)

    def index_propositions_batch(
        self,
        propositions: list[dict[str, Any]],
    ) -> None:
        """Batch index multiple propositions."""
        from grundrisse_argument.vector import PropositionVector

        if not propositions:
            return

        # Encode all summaries
        summaries = [p["text_summary"] for p in propositions]
        embeddings = self.encoder.encode(summaries)

        # Create vector records
        prop_vectors = []
        for i, prop in enumerate(propositions):
            prop_vectors.append(
                PropositionVector(
                    prop_id=prop["prop_id"],
                    text_summary=prop["text_summary"],
                    embedding=embeddings[i],
                    doc_id=prop.get("doc_id"),
                    concept_labels=prop.get("concept_labels"),
                    entity_ids=prop.get("entity_ids"),
                    temporal_scope=prop.get("temporal_scope"),
                    is_implicit_reconstruction=prop.get("is_implicit", False),
                )
            )

        # Batch upsert
        self.qdrant.upsert_propositions(prop_vectors)

    # =========================================================================
    # Concept and Entity Indexing
    # =========================================================================

    def index_concept(
        self,
        concept_id: str,
        label_canonical: str,
        gloss: str | None = None,
        temporal_scope: str | None = None,
        work_id: str | None = None,
    ) -> None:
        """Index a concept for drift detection."""
        from grundrisse_argument.vector import ConceptVector

        embedding = self.encoder.encode_concept(
            label=label_canonical,
            gloss=gloss,
            temporal_scope=temporal_scope,
        )

        concept_vector = ConceptVector(
            concept_id=concept_id,
            label_canonical=label_canonical,
            embedding=embedding,
            gloss=gloss,
            temporal_scope=temporal_scope,
            work_id=work_id,
        )

        self.qdrant.upsert_concept(concept_vector)

    def index_entity(
        self,
        entity_id: str,
        canonical_name: str,
        entity_type: str | None = None,
        surface_forms: list[str] | None = None,
    ) -> None:
        """Index an entity for disambiguation."""
        from grundrisse_argument.vector import EntityVector

        embedding = self.encoder.encode_entity(
            name=canonical_name,
            entity_type=entity_type,
        )

        entity_vector = EntityVector(
            entity_id=entity_id,
            canonical_name=canonical_name,
            embedding=embedding,
            entity_type=entity_type,
            surface_forms=surface_forms,
        )

        self.qdrant.upsert_entity(entity_vector)


__all__ = [
    "RetrievalConfig",
    "RetrievedContext",
    "RetrievalOrchestrator",
    "CONCLUSION_MARKERS",
    "EVALUATIVE_MARKERS",
    "DEFINITIONAL_FORCE_TAGS",
]
