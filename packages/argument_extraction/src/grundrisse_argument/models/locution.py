"""
Locution (L-node) - A concrete span of text.

Locutions are immutable and constitute the audit trail of the system.
Every higher-order object MUST reference loc_ids.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class Locution(BaseModel):
    """
    L-Node: An immutable span of text.

    Every higher-order object MUST reference loc_ids.
    """

    loc_id: str = Field(..., description="Unique hash of doc_id + offsets")
    doc_id: str = Field(..., description="Document identifier")
    text: str = Field(..., description="Verbatim text slice")
    start_char: int = Field(..., description="Start offset in document")
    end_char: int = Field(..., description="End offset in document")

    # Structural context
    paragraph_id: str = Field(..., description="Paragraph identifier")
    section_path: List[str] = Field(default_factory=list, description="Section hierarchy")
    is_footnote: bool = Field(default=False, description="True if locution is from a footnote")

    # Normalization
    normalized_text: Optional[str] = Field(None, description="Normalized text for processing")

    class Config:
        frozen = True  # Immutable
