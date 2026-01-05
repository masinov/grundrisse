"""Stats endpoint for landing page."""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select, union

from api.deps import DbSession
from grundrisse_core.db.models import (
    Author,
    ClaimEvidence,
    ConceptMention,
    Edition,
    Paragraph,
    SentenceSpan,
    SpanGroup,
    Work,
)

router = APIRouter()


class StatsResponse(BaseModel):
    """Corpus statistics."""

    author_count: int
    work_count: int
    paragraph_count: int
    works_with_extractions: int
    extraction_coverage_percent: float


@router.get("/stats", response_model=StatsResponse)
def get_stats(db: DbSession) -> StatsResponse:
    """Get corpus statistics for the landing page."""
    author_count = db.scalar(select(func.count()).select_from(Author)) or 0
    work_count = db.scalar(select(func.count()).select_from(Work)) or 0
    paragraph_count = db.scalar(select(func.count()).select_from(Paragraph)) or 0

    works_with_concepts_sq = (
        select(Edition.work_id.label("work_id"))
        .select_from(Edition)
        .join(SentenceSpan, SentenceSpan.edition_id == Edition.edition_id)
        .join(ConceptMention, ConceptMention.span_id == SentenceSpan.span_id)
        .distinct()
    )
    works_with_claims_sq = (
        select(Edition.work_id.label("work_id"))
        .select_from(Edition)
        .join(SpanGroup, SpanGroup.edition_id == Edition.edition_id)
        .join(ClaimEvidence, ClaimEvidence.group_id == SpanGroup.group_id)
        .distinct()
    )
    works_union = union(works_with_concepts_sq, works_with_claims_sq).subquery()

    works_with_extractions = db.scalar(select(func.count(func.distinct(works_union.c.work_id)))) or 0

    coverage = (works_with_extractions / work_count * 100) if work_count > 0 else 0.0

    return StatsResponse(
        author_count=author_count,
        work_count=work_count,
        paragraph_count=paragraph_count,
        works_with_extractions=works_with_extractions,
        extraction_coverage_percent=round(coverage, 3),
    )
