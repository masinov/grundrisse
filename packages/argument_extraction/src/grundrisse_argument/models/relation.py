"""
Argumentative relations (AIF S-nodes).

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §3.6 and Appendix A:

Captures dialectical motion between propositions: support, conflict, rephrase.
Evidence is MANDATORY (§12.1 hard constraint) - all relations must cite text spans.
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field

# Per Appendix A
RelationType = Literal["support", "conflict", "rephrase"]
ConflictType = Literal["rebut", "undercut", "incompatibility"]


class ArgumentRelation(BaseModel):
    """
    RA/CA/MA Nodes - Captures dialectical motion between I-Nodes.

    Per Appendix A schema:
    - Support (RA): Premises support a conclusion
    - Conflict (CA): Claims attack each other
    - Rephrase (MA): Propositions are equivalent

    Per §7.3: Undercutting
    If a proposition attacks the connection between premises and conclusion
    rather than the conclusion itself, the conflict is represented as
    targeting an inference node.
    """

    rel_id: str = Field(..., description="Unique relation identifier")
    relation_type: RelationType = Field(..., description="Type of argumentative relation")

    # Direction (per Appendix A)
    source_prop_ids: List[str] = Field(
        ..., description="Premises / Attacking Claims (one or more)"
    )
    target_prop_id: str = Field(
        ..., description="Conclusion / Attacked Claim (single)"
    )

    # Conflict detail (per Appendix A)
    conflict_detail: Optional[ConflictType] = Field(
        None, description="Type of conflict: rebut, undercut, or incompatibility"
    )

    # Evidence is MANDATORY (§12.1 hard constraint)
    evidence_loc_ids: List[str] = Field(
        ..., min_items=1, description="Text spans (e.g., 'therefore') licensing the link"
    )

    # Metadata
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Classification confidence"
    )
