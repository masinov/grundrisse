"""
Locution (L-node) - A concrete span of text.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md Appendix A:

Locutions are immutable and constitute the audit trail of the system.
Every higher-order object MUST reference loc_ids.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class Locution(BaseModel):
    """
    L-Node: An immutable span of text.

    Per Appendix A schema:
    Every higher-order object MUST reference loc_ids.
    """

    loc_id: str = Field(..., description="Unique hash of doc_id + offsets")
    text: str = Field(..., description="Verbatim text slice")
    start_char: int = Field(..., description="Start offset in document")
    end_char: int = Field(..., description="End offset in document")

    # Structural context (§4.1: DOM-aware ingestion)
    paragraph_id: str = Field(..., description="Paragraph identifier")
    section_path: List[str] = Field(default_factory=list, description="Section hierarchy")

    # Footnote handling (footnotes are often polemical/definitional)
    is_footnote: bool = Field(default=False, description="True if locution is from a footnote")
    footnote_links: List[str] = Field(default_factory=list, description="Linked loc_ids (for cross-references)")

    class Config:
        frozen = True  # Immutable
