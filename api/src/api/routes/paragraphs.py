"""Paragraph and extraction endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.deps import DbSession
from grundrisse_core.db.models import Claim, ClaimEvidence, ConceptMention, Paragraph, SentenceSpan, SpanGroup

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

    # Some older ingestions accidentally created duplicate paragraph rows per (edition_id, order_index).
    # Resolve extractions by (edition_id, order_index) so the reader sees the full set.
    edition_id = paragraph.edition_id
    order_index = paragraph.order_index

    # Concept mentions are attached to sentence spans; sentence spans carry para_index (= paragraph order).
    concept_rows = db.execute(
        select(ConceptMention)
        .select_from(ConceptMention)
        .join(SentenceSpan, SentenceSpan.span_id == ConceptMention.span_id)
        .where(SentenceSpan.edition_id == edition_id)
        .where(SentenceSpan.para_index == order_index)
    ).scalars().all()

    concepts = [
        ConceptMentionInfo(
            mention_id=cm.mention_id,
            text=cm.surface_form or "",
            char_start=cm.start_char_in_sentence,
            char_end=cm.end_char_in_sentence,
        )
        for cm in concept_rows
    ]

    # Claims are attached via ClaimEvidence -> SpanGroup(para_id) -> Paragraph(order_index) -> Claim.
    claim_rows = db.execute(
        select(Claim)
        .select_from(Claim)
        .join(ClaimEvidence, ClaimEvidence.claim_id == Claim.claim_id)
        .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
        .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
        .where(Paragraph.edition_id == edition_id)
        .where(Paragraph.order_index == order_index)
        .distinct()
    ).scalars().all()

    claims = [
        ClaimInfo(
            claim_id=c.claim_id,
            text=c.claim_text_canonical or "",
            confidence=c.confidence,
        )
        for c in claim_rows
    ]

    return ParagraphExtractionsResponse(
        paragraph_id=paragraph_id,
        concepts=concepts,
        claims=claims,
    )
