"""Work endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Integer, cast, func, select, union

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


class WorkListItem(BaseModel):
    """Work summary for list views."""

    work_id: UUID
    title: str
    author_id: UUID
    author_name: str
    publication_year: int | None
    date_confidence: str | None
    language: str | None
    paragraph_count: int
    has_extractions: bool

    model_config = {"from_attributes": True}


class WorkListResponse(BaseModel):
    """Paginated work list."""

    total: int
    limit: int
    offset: int
    works: list[WorkListItem]


class EditionInfo(BaseModel):
    """Edition information."""

    edition_id: UUID
    language: str | None
    source_url: str | None
    paragraph_count: int


class AuthorInfo(BaseModel):
    """Author information for work detail."""

    author_id: UUID
    name_canonical: str


class ExtractionStats(BaseModel):
    """Extraction statistics for a work."""

    paragraphs_processed: int
    concept_mentions: int
    claims: int


class WorkDetailResponse(BaseModel):
    """Full work detail."""

    work_id: UUID
    title: str
    title_canonical: str | None
    author: AuthorInfo
    publication_year: int | None
    date_confidence: str | None
    source_url: str | None
    editions: list[EditionInfo]
    has_extractions: bool
    extraction_stats: ExtractionStats | None

    model_config = {"from_attributes": True}


class ParagraphSummary(BaseModel):
    """Paragraph summary for work reader."""

    paragraph_id: UUID
    order_in_edition: int
    text_content: str
    has_extractions: bool
    concept_count: int
    claim_count: int

    model_config = {"from_attributes": True}


class WorkParagraphsResponse(BaseModel):
    """Paginated paragraphs for a work."""

    work_id: UUID
    edition_id: UUID
    total: int
    limit: int
    offset: int
    paragraphs: list[ParagraphSummary]


def _pub_year_and_confidence(pub_date: dict | None) -> tuple[int | None, str | None]:
    if not isinstance(pub_date, dict):
        return None, None
    year = pub_date.get("year")
    if not isinstance(year, int):
        return None, None
    method = str(pub_date.get("method") or "").strip().lower()
    confidence = pub_date.get("confidence")
    conf = float(confidence) if isinstance(confidence, (int, float)) else None
    # Minimal labeling for MVP.
    if method in {"heuristic_url_year", ""} and (conf is None or conf <= 0.3):
        return year, "heuristic"
    return year, "evidence"


def _work_aggregates_subqueries():
    # Paragraphs per work
    para_count_sq = (
        select(
            Edition.work_id.label("work_id"),
            func.count(func.distinct(Paragraph.order_index)).label("paragraph_count"),
        )
        .select_from(Edition)
        .outerjoin(Paragraph, Paragraph.edition_id == Edition.edition_id)
        .group_by(Edition.work_id)
        .subquery()
    )

    # Representative language per work (most works have a single edition currently).
    lang_sq = (
        select(
            Edition.work_id.label("work_id"),
            func.min(Edition.language).label("language"),
        )
        .select_from(Edition)
        .group_by(Edition.work_id)
        .subquery()
    )

    # Concept mentions per work via sentence spans.
    concept_sq = (
        select(
            Edition.work_id.label("work_id"),
            func.count(func.distinct(ConceptMention.mention_id)).label("concept_mentions"),
        )
        .select_from(Edition)
        .join(SentenceSpan, SentenceSpan.edition_id == Edition.edition_id)
        .join(ConceptMention, ConceptMention.span_id == SentenceSpan.span_id)
        .group_by(Edition.work_id)
        .subquery()
    )

    # Claims per work via claim evidence groups.
    claim_sq = (
        select(
            Edition.work_id.label("work_id"),
            func.count(func.distinct(ClaimEvidence.claim_id)).label("claims"),
        )
        .select_from(Edition)
        .join(SpanGroup, SpanGroup.edition_id == Edition.edition_id)
        .join(ClaimEvidence, ClaimEvidence.group_id == SpanGroup.group_id)
        .group_by(Edition.work_id)
        .subquery()
    )

    return para_count_sq, lang_sq, concept_sq, claim_sq


@router.get("", response_model=WorkListResponse)
def list_works(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    author_id: UUID | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    language: str | None = None,
    has_extractions: bool | None = None,
    q: str | None = Query(default=None, min_length=1),
) -> WorkListResponse:
    """List works with filters."""
    para_count_sq, lang_sq, concept_sq, claim_sq = _work_aggregates_subqueries()

    year_expr = cast(Work.publication_date["year"].astext, Integer)
    concept_count_expr = func.coalesce(concept_sq.c.concept_mentions, 0)
    claim_count_expr = func.coalesce(claim_sq.c.claims, 0)
    has_extractions_expr = (concept_count_expr + claim_count_expr) > 0

    query = (
        select(
            Work.work_id,
            Work.title,
            Work.author_id,
            Work.publication_date,
            Author.name_canonical.label("author_name"),
            func.coalesce(lang_sq.c.language, Work.original_language).label("language"),
            func.coalesce(para_count_sq.c.paragraph_count, 0).label("paragraph_count"),
            has_extractions_expr.label("has_extractions"),
        )
        .select_from(Work)
        .join(Author, Author.author_id == Work.author_id)
        .outerjoin(para_count_sq, para_count_sq.c.work_id == Work.work_id)
        .outerjoin(lang_sq, lang_sq.c.work_id == Work.work_id)
        .outerjoin(concept_sq, concept_sq.c.work_id == Work.work_id)
        .outerjoin(claim_sq, claim_sq.c.work_id == Work.work_id)
    )

    if author_id:
        query = query.where(Work.author_id == author_id)
    if q:
        query = query.where(Work.title.ilike(f"%{q}%"))
    if language:
        query = query.where(func.coalesce(lang_sq.c.language, Work.original_language) == language)
    if year_min is not None:
        query = query.where(year_expr >= year_min)
    if year_max is not None:
        query = query.where(year_expr <= year_max)
    if has_extractions is not None:
        query = query.where(has_extractions_expr.is_(True) if has_extractions else has_extractions_expr.is_(False))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0

    rows = db.execute(query.order_by(Work.title).limit(limit).offset(offset)).all()

    works: list[WorkListItem] = []
    for r in rows:
        pub_year, date_conf = _pub_year_and_confidence(r.publication_date if isinstance(r.publication_date, dict) else None)
        works.append(
            WorkListItem(
                work_id=r.work_id,
                title=r.title,
                author_id=r.author_id,
                author_name=r.author_name,
                publication_year=pub_year,
                date_confidence=date_conf,
                language=r.language,
                paragraph_count=r.paragraph_count or 0,
                has_extractions=bool(r.has_extractions),
            )
        )

    return WorkListResponse(total=total, limit=limit, offset=offset, works=works)


@router.get("/{work_id}", response_model=WorkDetailResponse)
def get_work(db: DbSession, work_id: UUID) -> WorkDetailResponse:
    """Get work detail."""
    work = db.get(Work, work_id)
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")

    author = db.get(Author, work.author_id)
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    editions_query = (
        select(
            Edition.edition_id,
            Edition.language,
            Edition.source_url,
            func.count(func.distinct(Paragraph.order_index)).label("paragraph_count"),
        )
        .select_from(Edition)
        .outerjoin(Paragraph, Paragraph.edition_id == Edition.edition_id)
        .where(Edition.work_id == work_id)
        .group_by(Edition.edition_id, Edition.language, Edition.source_url)
        .order_by(Edition.language)
    )
    edition_rows = db.execute(editions_query).all()
    editions = [
        EditionInfo(
            edition_id=r.edition_id,
            language=r.language,
            source_url=r.source_url,
            paragraph_count=r.paragraph_count or 0,
        )
        for r in edition_rows
    ]

    edition_ids = [e.edition_id for e in editions]
    source_url = editions[0].source_url if editions else None

    concept_mentions = 0
    claims = 0
    paragraphs_processed = 0
    has_extractions = False

    if edition_ids:
        concept_mentions = db.scalar(
            select(func.count(func.distinct(ConceptMention.mention_id)))
            .select_from(ConceptMention)
            .join(SentenceSpan, SentenceSpan.span_id == ConceptMention.span_id)
            .where(SentenceSpan.edition_id.in_(edition_ids))
        ) or 0

        claims = db.scalar(
            select(func.count(func.distinct(ClaimEvidence.claim_id)))
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .where(SpanGroup.edition_id.in_(edition_ids))
        ) or 0

        has_extractions = (concept_mentions + claims) > 0

        if has_extractions:
            paras_with_concepts = (
                select(SentenceSpan.para_id.label("para_id"))
                .select_from(SentenceSpan)
                .join(ConceptMention, ConceptMention.span_id == SentenceSpan.span_id)
                .where(SentenceSpan.edition_id.in_(edition_ids))
                .where(SentenceSpan.para_id.isnot(None))
                .distinct()
            )
            paras_with_claims = (
                select(SpanGroup.para_id.label("para_id"))
                .select_from(SpanGroup)
                .join(ClaimEvidence, ClaimEvidence.group_id == SpanGroup.group_id)
                .where(SpanGroup.edition_id.in_(edition_ids))
                .where(SpanGroup.para_id.isnot(None))
                .distinct()
            )
            paras_union = union(paras_with_concepts, paras_with_claims).subquery()
            paragraphs_processed = db.scalar(select(func.count(func.distinct(paras_union.c.para_id)))) or 0

    extraction_stats = (
        ExtractionStats(
            paragraphs_processed=paragraphs_processed,
            concept_mentions=concept_mentions,
            claims=claims,
        )
        if has_extractions
        else None
    )

    pub_year, date_conf = _pub_year_and_confidence(work.publication_date if isinstance(work.publication_date, dict) else None)

    return WorkDetailResponse(
        work_id=work.work_id,
        title=work.title,
        title_canonical=work.title_canonical,
        author=AuthorInfo(author_id=author.author_id, name_canonical=author.name_canonical),
        publication_year=pub_year,
        date_confidence=date_conf,
        source_url=source_url,
        editions=editions,
        has_extractions=has_extractions,
        extraction_stats=extraction_stats,
    )


@router.get("/{work_id}/paragraphs", response_model=WorkParagraphsResponse)
def get_work_paragraphs(
    db: DbSession,
    work_id: UUID,
    edition_id: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> WorkParagraphsResponse:
    """Get paragraphs for a work."""
    work = db.get(Work, work_id)
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")

    # Default to first edition if not specified.
    if edition_id:
        edition = db.get(Edition, edition_id)
        if not edition or edition.work_id != work_id:
            raise HTTPException(status_code=404, detail="Edition not found")
    else:
        edition = db.scalar(select(Edition).where(Edition.work_id == work_id).order_by(Edition.language).limit(1))
        if not edition:
            raise HTTPException(status_code=404, detail="No editions found for work")

    total = (
        db.scalar(
            select(func.count(func.distinct(Paragraph.order_index)))
            .select_from(Paragraph)
            .where(Paragraph.edition_id == edition.edition_id)
        )
        or 0
    )

    # Some older ingestions accidentally created duplicate paragraph rows per (edition_id, order_index).
    # To keep the reader usable, aggregate by order_index and pick a stable representative paragraph_id.
    para_dedup_sq = (
        select(
            Paragraph.order_index.label("order_in_edition"),
            func.min(Paragraph.para_id).label("paragraph_id"),
            func.min(Paragraph.text_normalized).label("text_content"),
        )
        .select_from(Paragraph)
        .where(Paragraph.edition_id == edition.edition_id)
        .group_by(Paragraph.order_index)
        .subquery()
    )

    # Extractions are linked via sentence spans and span groups. Aggregate counts by paragraph order_index
    # so duplicates don't suppress extraction signals.
    concept_count_sq = (
        select(
            Paragraph.order_index.label("order_in_edition"),
            func.count(func.distinct(ConceptMention.mention_id)).label("concept_count"),
        )
        .select_from(Paragraph)
        .join(SentenceSpan, SentenceSpan.para_id == Paragraph.para_id)
        .join(ConceptMention, ConceptMention.span_id == SentenceSpan.span_id)
        .where(Paragraph.edition_id == edition.edition_id)
        .group_by(Paragraph.order_index)
        .subquery()
    )
    claim_count_sq = (
        select(
            Paragraph.order_index.label("order_in_edition"),
            func.count(func.distinct(ClaimEvidence.claim_id)).label("claim_count"),
        )
        .select_from(Paragraph)
        .join(SpanGroup, SpanGroup.para_id == Paragraph.para_id)
        .join(ClaimEvidence, ClaimEvidence.group_id == SpanGroup.group_id)
        .where(Paragraph.edition_id == edition.edition_id)
        .group_by(Paragraph.order_index)
        .subquery()
    )

    query = (
        select(
            para_dedup_sq.c.paragraph_id,
            para_dedup_sq.c.order_in_edition,
            para_dedup_sq.c.text_content,
            func.coalesce(concept_count_sq.c.concept_count, 0).label("concept_count"),
            func.coalesce(claim_count_sq.c.claim_count, 0).label("claim_count"),
        )
        .select_from(para_dedup_sq)
        .outerjoin(concept_count_sq, concept_count_sq.c.order_in_edition == para_dedup_sq.c.order_in_edition)
        .outerjoin(claim_count_sq, claim_count_sq.c.order_in_edition == para_dedup_sq.c.order_in_edition)
        .order_by(para_dedup_sq.c.order_in_edition)
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(query).all()

    paragraphs: list[ParagraphSummary] = []
    for r in rows:
        has_extractions = (r.concept_count or 0) > 0 or (r.claim_count or 0) > 0
        paragraphs.append(
            ParagraphSummary(
                paragraph_id=r.paragraph_id,
                order_in_edition=r.order_in_edition,
                text_content=r.text_content,
                has_extractions=has_extractions,
                concept_count=r.concept_count or 0,
                claim_count=r.claim_count or 0,
            )
        )

    return WorkParagraphsResponse(
        work_id=work_id,
        edition_id=edition.edition_id,
        total=total,
        limit=limit,
        offset=offset,
        paragraphs=paragraphs,
    )
