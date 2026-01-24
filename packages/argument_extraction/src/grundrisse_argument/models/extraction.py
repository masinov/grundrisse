"""
Extraction window - Output container for LLM extraction.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §5.4 and Appendix A:

Combines all extracted elements from a single processing window.
Retrieved context is structurally separated and marked as read-only to prevent
context poisoning.
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field

from grundrisse_argument.models.locution import Locution
from grundrisse_argument.models.proposition import Proposition
from grundrisse_argument.models.illocution import IllocutionaryEdge
from grundrisse_argument.models.relation import ArgumentRelation
from grundrisse_argument.models.transition import Transition


class RetrievedContext(BaseModel):
    """
    Retrieved context proposition (read-only, non-extractible).

    Per §5.4: Retrieved context presentation (CRITICAL):
    To prevent context poisoning, retrieved material is:
    - Explicitly marked with [RETRIEVED_CONTEXT]
    - Structurally separated from extraction window
    - Read-only: marked with extractable=False
    - Cannot generate new locutions
    - Relations may cite retrieved props as premises, but retrieved text
      cannot serve as evidence locutions
    """

    prop_id: str = Field(..., description="Proposition identifier (from previous extraction)")
    text_summary: str = Field(..., description="Proposition text summary")
    source_doc_id: str = Field(..., description="Source document of retrieved proposition")
    position: int = Field(..., description="Position in retrieved context list")

    # Retrieval metadata
    retrieval_method: Literal["vector", "concept_overlap", "entity_alignment"] = Field(
        ..., description="How this proposition was retrieved"
    )
    retrieval_score: float = Field(..., ge=0.0, le=1.0, description="Similarity/relevance score")


class ExtractionWindow(BaseModel):
    """
    Complete output from a single extraction window.

    Per Stage 5 specification:
    A window processes 2-6 paragraphs with overlap and produces:
    - Locutions (text spans)
    - Transitions (discourse markers)
    - Propositions (I-nodes)
    - Illocutions (L→P edges)
    - Relations (S-nodes)

    Retrieved context is READ-ONLY and structurally separated per §5.4.
    """

    # Metadata
    window_id: str = Field(..., description="Unique window identifier")
    doc_id: str = Field(..., description="Source document identifier")
    paragraph_ids: List[str] = Field(..., description="Paragraph IDs in window")

    # Extracted elements (from local window text)
    locutions: List[Locution] = Field(default_factory=list)
    transitions: List[Transition] = Field(default_factory=list)
    propositions: List[Proposition] = Field(default_factory=list)
    illocutions: List[IllocutionaryEdge] = Field(default_factory=list)
    relations: List[ArgumentRelation] = Field(default_factory=list)

    # Retrieved context (read-only, non-extractible) per §5.4
    retrieved_context: List[RetrievedContext] = Field(
        default_factory=list,
        description="Previously extracted propositions for cross-window linking (READ-ONLY)",
    )

    # Validation metadata
    extraction_run_id: str = Field(..., description="Extraction run identifier")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Overall extraction confidence")
