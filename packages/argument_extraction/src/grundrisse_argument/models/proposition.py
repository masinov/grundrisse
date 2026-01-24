"""
Proposition (I-node) - Abstract propositional content.

A proposition may be realized by multiple locutions but is separated
from the act of uttering it.
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class ConceptBinding(BaseModel):
    """Binding to a concept for semantic retrieval."""

    concept_label: str = Field(..., description="Concept identifier or label")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Binding confidence")


class EntityBinding(BaseModel):
    """Binding to a named entity (person, school, position)."""

    entity_id: str = Field(..., description="Canonical entity identifier")
    entity_type: Literal["person", "school", "position", "unknown"] = Field(
        ..., description="Type of entity"
    )
    surface_form: str = Field(..., description="Surface form as it appears in text")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Binding confidence")


class Proposition(BaseModel):
    """
    I-Node: Abstract content.

    Separated from the act of uttering it. A proposition can be expressed
    by multiple locutions (e.g., through repetition or paraphrase).
    """

    prop_id: str = Field(..., description="Unique proposition identifier")
    doc_id: str = Field(..., description="Source document identifier")

    # Grounding: A proposition must cite at least one locution
    surface_loc_ids: List[str] = Field(
        ..., min_items=1, description="Must reference at least one locution"
    )

    # Content representation
    text_summary: str = Field(
        ..., description="Self-contained statement of propositional content"
    )

    # Bindings
    concept_bindings: List[ConceptBinding] = Field(
        default_factory=list, description="Concept bindings for retrieval"
    )
    entity_bindings: List[EntityBinding] = Field(
        default_factory=list, description="Entity bindings for attribution"
    )

    # Temporal/Dialectical Tags
    temporal_scope: Optional[str] = Field(
        None, description="e.g., '1844', 'Capitalist Mode', 'Feudalism'"
    )
    is_implicit_reconstruction: bool = Field(
        default=False,
        description="True if reconstructed from enthymeme (implicit premises)",
    )

    # Metadata
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Extraction confidence"
    )
