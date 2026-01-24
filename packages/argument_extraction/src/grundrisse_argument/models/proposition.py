"""
Proposition (I-node) - Abstract propositional content.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §3.4 and Appendix A:

A proposition may be realized by multiple locutions but is separated
from the act of uttering it.
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class ConceptBinding(BaseModel):
    """
    Binding to a concept for semantic retrieval.

    Per §9.1: Concept bindings for time-indexed conceptual tracking.
    """

    concept_label: str = Field(..., description="Concept identifier or label")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Binding confidence")


class EntityBinding(BaseModel):
    """
    Binding to a named entity (person, school, position).

    Per §4.3: Entity normalization for stable attribution across windows.
    """

    entity_id: str = Field(..., description="Canonical entity identifier")
    entity_type: Literal["person", "school", "position", "unknown"] = Field(
        ..., description="Type of entity"
    )
    surface_form: str = Field(..., description="Surface form as it appears in text")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Binding confidence")


class Proposition(BaseModel):
    """
    I-Node: Abstract content.

    Per Appendix A schema:
    Separated from the act of uttering it. A proposition can be expressed
    by multiple locutions (e.g., through repetition or paraphrase).

    Per §9.1: A proposition may bind to one or more concepts with:
    - concept_id
    - embedding
    - time_index (document date)
    """

    prop_id: str = Field(..., description="Unique proposition identifier")

    # Grounding: A proposition must cite at least one locution (§12.1 hard constraint)
    surface_loc_ids: List[str] = Field(
        ..., min_items=1, description="Must reference at least one locution"
    )

    # Content representation (self-contained statement of content)
    text_summary: str = Field(
        ..., description="Self-contained statement of propositional content"
    )

    # Bindings (§4.3, §9.1)
    concept_bindings: List[ConceptBinding] = Field(
        default_factory=list, description="Concept bindings for retrieval"
    )
    entity_bindings: List[EntityBinding] = Field(
        default_factory=list, description="Entity bindings for attribution"
    )

    # Temporal/Dialectical Tags (§9.2)
    temporal_scope: Optional[str] = Field(
        None, description="e.g., '1844', 'Capitalist Mode', 'Feudalism'"
    )

    # Implicit reconstruction from enthymeme (§5.3)
    is_implicit_reconstruction: bool = Field(
        default=False,
        description="True if reconstructed from enthymeme (implicit premises)",
    )

    # Optional canonical label (late-stage only, §8)
    canonical_label: Optional[str] = Field(
        None, description="Optional canonical label (late-stage only)"
    )

    # Metadata
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Extraction confidence"
    )
