"""
Argumentative relations (AIF S-nodes).

Captures dialectical motion between propositions: support, conflict, rephrase.
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field

RelationType = Literal["support", "conflict", "rephrase"]
ConflictType = Literal["rebut", "undercut", "incompatibility"]


class ArgumentRelation(BaseModel):
    """
    RA/CA/MA Nodes - Captures dialectical motion between I-Nodes.

    Support (RA): Premises support a conclusion
    Conflict (CA): Claims attack each other
    Rephrase (MA): Propositions are equivalent
    """

    rel_id: str = Field(..., description="Unique relation identifier")
    doc_id: str = Field(..., description="Source document identifier")
    relation_type: RelationType = Field(..., description="Type of argumentative relation")

    # Direction
    source_prop_ids: List[str] = Field(
        ..., description="Premises / Attacking Claims (one or more)"
    )
    target_prop_id: str = Field(
        ..., description="Conclusion / Attacked Claim (single)"
    )

    # Conflict detail (only for conflict relations)
    conflict_detail: Optional[ConflictType] = Field(
        None, description="Type of conflict: rebut, undercut, or incompatibility"
    )

    # Undercutting: If attacking the connection rather than the conclusion
    targets_inference: bool = Field(
        default=False,
        description="True if attack targets the inference connection, not the conclusion",
    )

    # Evidence is MANDATORY - must cite text spans licensing the link
    evidence_loc_ids: List[str] = Field(
        ..., min_items=1, description="Text spans (e.g., 'therefore') licensing the link"
    )

    # Scheme type (optional, for support relations)
    scheme_type: Optional[str] = Field(
        None, description="Argument scheme (e.g., 'modus ponens', 'analogy')"
    )

    # Metadata
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Classification confidence"
    )
