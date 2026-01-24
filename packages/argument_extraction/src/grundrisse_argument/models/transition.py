"""
Transition - Discourse transitions between locutions.

Transitions are persisted and queryable as first-class objects.
They encode rhetorical motion independent of argument structure.
"""

from typing import Literal
from pydantic import BaseModel, Field

TransitionHint = Literal["contrast", "inference", "concession", "continuation", "narrative"]


class Transition(BaseModel):
    """
    Discourse transition between locutions.

    Persisted for query and analytically valuable for:
    - Identifying discourse boundaries
    - Recovering authorial intent
    - Supporting fine-grained navigation

    Transitions are not arguments themselves but signal likely
    illocutionary and argumentative structure.
    """

    transition_id: str = Field(..., description="Unique transition identifier")
    doc_id: str = Field(..., description="Source document identifier")
    from_loc_id: str = Field(..., description="Source locution (L-node)")
    to_loc_id: str = Field(..., description="Target locution (L-node)")

    marker: str = Field(..., description="Discourse marker (e.g., 'however', 'therefore')")
    function_hint: TransitionHint = Field(
        ..., description="Functional classification of the transition"
    )

    # Position in text (for ordering)
    position: int = Field(..., description="Sequential position in document")
