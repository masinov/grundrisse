"""
Illocutionary connection - Anchors locutions to propositions.

Captures 'what is done' with the text (asserting, denying, attributing, etc.).
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field

IllocutionType = Literal[
    "assert",
    "deny",
    "question",
    "define",
    "distinguish",
    "attribute",
    "concede",
    "ironic",
    "hypothetical",
    "prescriptive",
]


class IllocutionaryEdge(BaseModel):
    """
    The link between L-Node (locution) and I-Node (proposition).

    Captures the pragmatic force - what is being done with the text.
    This is critical for Marxist texts where irony, attribution, and
    implicit opponents are common.
    """

    illoc_id: str = Field(..., description="Unique illocution identifier")
    source_loc_id: str = Field(..., description="Source locution (L-node)")
    target_prop_id: str = Field(..., description="Target proposition (I-node)")
    force: IllocutionType = Field(..., description="Illocutionary force")

    # Attribution: Critical for philosophical texts
    attributed_to: Optional[str] = Field(
        None,
        description="Person/School being attributed (e.g., 'Ricardo', 'The Vulgar Economists')",
    )
    is_implicit_opponent: bool = Field(
        default=False,
        description="True if target is an abstract/unnamed opponent",
    )

    # Metadata
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Classification confidence"
    )
