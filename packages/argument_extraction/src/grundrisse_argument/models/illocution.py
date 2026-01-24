"""
Illocutionary connection - Anchors locutions to propositions.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §3.5 and Appendix A:

Captures 'what is done' with the text (asserting, denying, attributing, etc.).
Illocutionary force is never inferred solely from polarity; it is grounded in
discourse cues, transitions, and context (§6.2).
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field

# Per Appendix A: 10 illocutionary forces
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

    Per Appendix A schema:
    Captures the pragmatic force - what is being done with the text.

    This is critical for Marxist texts (§6.2) where:
    - Attribution and denial are explicitly modeled
    - Irony is treated as a first-class force
    - Implicit opponents are tracked (§6.3)
    """

    illoc_id: str = Field(..., description="Unique illocution identifier")
    source_loc_id: str = Field(..., description="Source locution (L-node)")
    target_prop_id: str = Field(..., description="Target proposition (I-node)")
    force: IllocutionType = Field(..., description="Illocutionary force")

    # Attribution (§6.3: implicit opponent handling)
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
