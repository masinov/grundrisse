"""Author endpoints."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from api.deps import DbSession
from grundrisse_core.db.models import (
    Author,
    AuthorAlias,
    ClaimEvidence,
    ConceptMention,
    Edition,
    Paragraph,
    SentenceSpan,
    SpanGroup,
    Work,
    WorkDateDerived,
)

router = APIRouter()


class AuthorSummary(BaseModel):
    """Author summary for list views."""

    author_id: UUID
    name_canonical: str
    birth_year: int | None
    death_year: int | None
    work_count: int

    model_config = {"from_attributes": True}


class AuthorListResponse(BaseModel):
    """Paginated author list."""

    total: int
    limit: int
    offset: int
    authors: list[AuthorSummary]


class WorkSummary(BaseModel):
    """Work summary for author detail."""

    work_id: UUID
    title: str
    title_canonical: str | None
    publication_year: int | None
    date_confidence: str | None
    display_date_field: str | None
    language: str | None
    paragraph_count: int
    has_extractions: bool

    model_config = {"from_attributes": True}


class AuthorDetailResponse(BaseModel):
    """Full author detail with works."""

    author_id: UUID
    name_canonical: str
    birth_year: int | None
    death_year: int | None
    aliases: list[str]
    work_count: int
    works: list[WorkSummary]

    model_config = {"from_attributes": True}


def _display_year_and_confidence(
    *,
    display_year: int | None,
    display_date: dict | None,
    display_date_field: str | None,
) -> tuple[int | None, str | None, str | None]:
    if isinstance(display_year, int):
        dd = display_date if isinstance(display_date, dict) else {}
        source = str(dd.get("source") or "").strip().lower()
        confidence = dd.get("confidence")
        conf = float(confidence) if isinstance(confidence, (int, float)) else None
        field = display_date_field if isinstance(display_date_field, str) else None
        if source == "heuristic_url_year" or field == "heuristic_publication_year" or (
            conf is not None and conf <= 0.3
        ):
            return display_year, "heuristic", field
        return display_year, "evidence", field

    return None, None, None


@router.get("", response_model=AuthorListResponse)
def list_authors(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort: Literal["name", "works", "birth_year"] = "works",
    order: Literal["asc", "desc"] = "desc",
    q: str | None = Query(default=None, min_length=1),
) -> AuthorListResponse:
    """List authors with work counts."""
    # Subquery for work counts
    work_count_sq = (
        select(Work.author_id, func.count(Work.work_id).label("work_count"))
        .group_by(Work.author_id)
        .subquery()
    )

    # Base query
    query = (
        select(
            Author.author_id,
            Author.name_canonical,
            Author.birth_year,
            Author.death_year,
            func.coalesce(work_count_sq.c.work_count, 0).label("work_count"),
        )
        .outerjoin(work_count_sq, Author.author_id == work_count_sq.c.author_id)
    )

    # Filter by name if provided
    if q:
        query = query.where(Author.name_canonical.ilike(f"%{q}%"))

    # Count total before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query) or 0

    # Sort
    sort_col = {
        "name": Author.name_canonical,
        "works": func.coalesce(work_count_sq.c.work_count, 0),
        "birth_year": Author.birth_year,
    }[sort]

    if order == "desc":
        query = query.order_by(sort_col.desc().nulls_last())
    else:
        query = query.order_by(sort_col.asc().nulls_last())

    # Paginate
    query = query.limit(limit).offset(offset)
    rows = db.execute(query).all()

    authors = [
        AuthorSummary(
            author_id=row.author_id,
            name_canonical=row.name_canonical,
            birth_year=row.birth_year,
            death_year=row.death_year,
            work_count=row.work_count,
        )
        for row in rows
    ]

    return AuthorListResponse(total=total, limit=limit, offset=offset, authors=authors)


@router.get("/{author_id}", response_model=AuthorDetailResponse)
def get_author(db: DbSession, author_id: UUID) -> AuthorDetailResponse:
    """Get author detail with works."""
    author = db.get(Author, author_id)
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    # Get aliases
    aliases = db.scalars(
        select(AuthorAlias.name_variant).where(AuthorAlias.author_id == author_id)
    ).all()

    para_count_sq = (
        select(
            Edition.work_id.label("work_id"),
            func.count(func.distinct(Paragraph.order_index)).label("paragraph_count"),
            func.min(Edition.language).label("language"),
        )
        .select_from(Edition)
        .outerjoin(Paragraph, Paragraph.edition_id == Edition.edition_id)
        .group_by(Edition.work_id)
        .subquery()
    )
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

    works_query = (
        select(
            Work.work_id,
            Work.title,
            Work.title_canonical,
            WorkDateDerived.display_year,
            WorkDateDerived.display_date,
            WorkDateDerived.display_date_field,
            func.coalesce(para_count_sq.c.language, Work.original_language).label("language"),
            func.coalesce(para_count_sq.c.paragraph_count, 0).label("paragraph_count"),
            (func.coalesce(concept_sq.c.concept_mentions, 0) + func.coalesce(claim_sq.c.claims, 0)).label(
                "extraction_signal"
            ),
        )
        .select_from(Work)
        .outerjoin(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
        .outerjoin(para_count_sq, para_count_sq.c.work_id == Work.work_id)
        .outerjoin(concept_sq, concept_sq.c.work_id == Work.work_id)
        .outerjoin(claim_sq, claim_sq.c.work_id == Work.work_id)
        .where(Work.author_id == author_id)
        .order_by(Work.title)
    )

    rows = db.execute(works_query).all()
    works: list[WorkSummary] = []
    for row in rows:
        year, date_confidence, display_field = _display_year_and_confidence(
            display_year=row.display_year,
            display_date=row.display_date if isinstance(row.display_date, dict) else None,
            display_date_field=row.display_date_field,
        )

        works.append(
            WorkSummary(
                work_id=row.work_id,
                title=row.title,
                title_canonical=row.title_canonical,
                publication_year=year,
                date_confidence=date_confidence,
                display_date_field=display_field,
                language=row.language,
                paragraph_count=row.paragraph_count or 0,
                has_extractions=(row.extraction_signal or 0) > 0,
            )
        )

    return AuthorDetailResponse(
        author_id=author.author_id,
        name_canonical=author.name_canonical,
        birth_year=author.birth_year,
        death_year=author.death_year,
        aliases=list(aliases),
        work_count=len(works),
        works=works,
    )
