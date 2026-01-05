"""Paragraph and extraction endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.deps import DbSession
from grundrisse_core.db.models import ClaimExtraction, ConceptMention, Paragraph

router = APIRouter()


class ConceptMentionInfo(BaseModel):
    """Concept mention in a paragraph."""

    mention_id: UUID
    text: str
    char_start: int | None
    char_end: int | None

    model_config = {"from_attributes": True}


class ClaimInfo(BaseModel):
    """Claim extracted from a paragraph."""

    claim_id: UUID
    text: str
    confidence: float | None

    model_config = {"from_attributes": True}


class ParagraphExtractionsResponse(BaseModel):
    """Extractions for a paragraph."""

    paragraph_id: UUID
    concepts: list[ConceptMentionInfo]
    claims: list[ClaimInfo]


@router.get("/{paragraph_id}/extractions", response_model=ParagraphExtractionsResponse)
def get_paragraph_extractions(db: DbSession, paragraph_id: UUID) -> ParagraphExtractionsResponse:
    """Get concept mentions and claims for a paragraph."""
    paragraph = db.get(Paragraph, paragraph_id)
    if not paragraph:
        raise HTTPException(status_code=404, detail="Paragraph not found")

    # Get concept mentions
    concept_rows = db.execute(
        select(ConceptMention).where(ConceptMention.paragraph_id == paragraph_id)
    ).scalars().all()

    concepts = [
        ConceptMentionInfo(
            mention_id=cm.mention_id,
            text=cm.surface_form or cm.canonical_form or "",
            char_start=cm.char_start,
            char_end=cm.char_end,
        )
        for cm in concept_rows
    ]

    # Get claims
    claim_rows = db.execute(
        select(ClaimExtraction).where(ClaimExtraction.paragraph_id == paragraph_id)
    ).scalars().all()

    claims = [
        ClaimInfo(
            claim_id=ce.claim_id,
            text=ce.claim_text or "",
            confidence=ce.confidence,
        )
        for ce in claim_rows
    ]

    return ParagraphExtractionsResponse(
        paragraph_id=paragraph_id,
        concepts=concepts,
        claims=claims,
    )
