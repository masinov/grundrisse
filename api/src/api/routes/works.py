"""Work endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from api.deps import DbSession
from grundrisse_core.db.models import (
    Author,
    ClaimExtraction,
    ConceptMention,
    Edition,
    ExtractionRun,
    Paragraph,
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
    # Build base query with joins
    query = (
        select(
            Work.work_id,
            Work.title,
            Work.author_id,
            Work.publication_date,
            Author.name_canonical.label("author_name"),
            Edition.language,
            func.count(func.distinct(Paragraph.paragraph_id)).label("paragraph_count"),
            func.count(func.distinct(ExtractionRun.run_id)).label("extraction_count"),
        )
        .select_from(Work)
        .join(Author, Author.author_id == Work.author_id)
        .join(Edition, Edition.work_id == Work.work_id)
        .outerjoin(Paragraph, Paragraph.edition_id == Edition.edition_id)
        .outerjoin(ExtractionRun, ExtractionRun.edition_id == Edition.edition_id)
        .group_by(Work.work_id, Work.title, Work.author_id, Work.publication_date, Author.name_canonical, Edition.language)
    )

    # Apply filters
    if author_id:
        query = query.where(Work.author_id == author_id)
    if q:
        query = query.where(Work.title.ilike(f"%{q}%"))
    if language:
        query = query.where(Edition.language == language)

    # Year filters on JSON field
    if year_min is not None:
        query = query.where(Work.publication_date["year"].astext.cast(db.bind.dialect.type_descriptor(type(0))) >= year_min)
    if year_max is not None:
        query = query.where(Work.publication_date["year"].astext.cast(db.bind.dialect.type_descriptor(type(0))) <= year_max)

    # Execute to get all matching rows, then filter by extraction status if needed
    all_rows = db.execute(query).all()

    # Filter by extraction status
    if has_extractions is not None:
        all_rows = [r for r in all_rows if (r.extraction_count > 0) == has_extractions]

    total = len(all_rows)

    # Paginate
    rows = all_rows[offset : offset + limit]

    works = []
    for row in rows:
        pub_date = row.publication_date if isinstance(row.publication_date, dict) else {}
        works.append(
            WorkListItem(
                work_id=row.work_id,
                title=row.title,
                author_id=row.author_id,
                author_name=row.author_name,
                publication_year=pub_date.get("year"),
                date_confidence="heuristic" if pub_date.get("year") else None,
                language=row.language,
                paragraph_count=row.paragraph_count or 0,
                has_extractions=row.extraction_count > 0,
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

    # Get editions with paragraph counts
    editions_query = (
        select(
            Edition.edition_id,
            Edition.language,
            Edition.source_url,
            func.count(Paragraph.paragraph_id).label("paragraph_count"),
        )
        .select_from(Edition)
        .outerjoin(Paragraph, Paragraph.edition_id == Edition.edition_id)
        .where(Edition.work_id == work_id)
        .group_by(Edition.edition_id, Edition.language, Edition.source_url)
    )
    edition_rows = db.execute(editions_query).all()

    editions = [
        EditionInfo(
            edition_id=row.edition_id,
            language=row.language,
            source_url=row.source_url,
            paragraph_count=row.paragraph_count or 0,
        )
        for row in edition_rows
    ]

    # Check for extractions
    extraction_run = db.scalar(
        select(ExtractionRun)
        .join(Edition, Edition.edition_id == ExtractionRun.edition_id)
        .where(Edition.work_id == work_id)
        .limit(1)
    )

    extraction_stats = None
    if extraction_run:
        # Get extraction counts
        edition_ids = [e.edition_id for e in editions]
        paragraphs_processed = db.scalar(
            select(func.count(func.distinct(Paragraph.paragraph_id)))
            .select_from(Paragraph)
            .join(ConceptMention, ConceptMention.paragraph_id == Paragraph.paragraph_id)
            .where(Paragraph.edition_id.in_(edition_ids))
        ) or 0

        concept_count = db.scalar(
            select(func.count())
            .select_from(ConceptMention)
            .join(Paragraph, Paragraph.paragraph_id == ConceptMention.paragraph_id)
            .where(Paragraph.edition_id.in_(edition_ids))
        ) or 0

        claim_count = db.scalar(
            select(func.count())
            .select_from(ClaimExtraction)
            .join(Paragraph, Paragraph.paragraph_id == ClaimExtraction.paragraph_id)
            .where(Paragraph.edition_id.in_(edition_ids))
        ) or 0

        extraction_stats = ExtractionStats(
            paragraphs_processed=paragraphs_processed,
            concept_mentions=concept_count,
            claims=claim_count,
        )

    pub_date = work.publication_date if isinstance(work.publication_date, dict) else {}
    source_url = editions[0].source_url if editions else None

    return WorkDetailResponse(
        work_id=work.work_id,
        title=work.title,
        title_canonical=work.title_canonical,
        author=AuthorInfo(author_id=author.author_id, name_canonical=author.name_canonical),
        publication_year=pub_date.get("year"),
        date_confidence="heuristic" if pub_date.get("year") else None,
        source_url=source_url,
        editions=editions,
        has_extractions=extraction_run is not None,
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

    # Get edition (first one if not specified)
    if edition_id:
        edition = db.get(Edition, edition_id)
        if not edition or edition.work_id != work_id:
            raise HTTPException(status_code=404, detail="Edition not found")
    else:
        edition = db.scalar(select(Edition).where(Edition.work_id == work_id).limit(1))
        if not edition:
            raise HTTPException(status_code=404, detail="No editions found for work")

    # Count total paragraphs
    total = db.scalar(
        select(func.count()).select_from(Paragraph).where(Paragraph.edition_id == edition.edition_id)
    ) or 0

    # Get paragraphs with extraction counts
    query = (
        select(
            Paragraph.paragraph_id,
            Paragraph.order_in_edition,
            Paragraph.text_content,
            func.count(func.distinct(ConceptMention.mention_id)).label("concept_count"),
            func.count(func.distinct(ClaimExtraction.claim_id)).label("claim_count"),
        )
        .select_from(Paragraph)
        .outerjoin(ConceptMention, ConceptMention.paragraph_id == Paragraph.paragraph_id)
        .outerjoin(ClaimExtraction, ClaimExtraction.paragraph_id == Paragraph.paragraph_id)
        .where(Paragraph.edition_id == edition.edition_id)
        .group_by(Paragraph.paragraph_id, Paragraph.order_in_edition, Paragraph.text_content)
        .order_by(Paragraph.order_in_edition)
        .limit(limit)
        .offset(offset)
    )

    rows = db.execute(query).all()

    paragraphs = [
        ParagraphSummary(
            paragraph_id=row.paragraph_id,
            order_in_edition=row.order_in_edition,
            text_content=row.text_content,
            has_extractions=(row.concept_count > 0 or row.claim_count > 0),
            concept_count=row.concept_count or 0,
            claim_count=row.claim_count or 0,
        )
        for row in rows
    ]

    return WorkParagraphsResponse(
        work_id=work_id,
        edition_id=edition.edition_id,
        total=total,
        limit=limit,
        offset=offset,
        paragraphs=paragraphs,
    )
