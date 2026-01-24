"""
Extraction window - Output container for LLM extraction.

Combines all extracted elements from a single processing window.
"""

from typing import List
from pydantic import BaseModel

from grundrisse_argument.models.locution import Locution
from grundrisse_argument.models.proposition import Proposition
from grundrisse_argument.models.illocution import IllocutionaryEdge
from grundrisse_argument.models.relation import ArgumentRelation
from grundrisse_argument.models.transition import Transition


class ExtractionWindow(BaseModel):
    """
    Complete output from a single extraction window.

    A window processes 2-6 paragraphs with overlap and produces
    locutions, propositions, illocutions, relations, and transitions.
    """

    # Metadata
    window_id: str
    doc_id: str
    paragraph_ids: List[str]

    # Extracted elements
    locutions: List[Locution]
    transitions: List[Transition]
    propositions: List[Proposition]
    illocutions: List[IllocutionaryEdge]
    relations: List[ArgumentRelation]

    # Retrieved context (read-only, non-extractible)
    retrieved_propositions: List[str] = []  # List of prop_ids referenced but not extracted

    class Config:
        # For JSON serialization
        json_encoders = {
            # Add custom encoders if needed
        }
