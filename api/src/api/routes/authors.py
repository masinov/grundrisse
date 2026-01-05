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
            Work.publication_date,
            func.coalesce(para_count_sq.c.language, Work.original_language).label("language"),
            func.coalesce(para_count_sq.c.paragraph_count, 0).label("paragraph_count"),
            (func.coalesce(concept_sq.c.concept_mentions, 0) + func.coalesce(claim_sq.c.claims, 0)).label(
                "extraction_signal"
            ),
        )
        .select_from(Work)
        .outerjoin(para_count_sq, para_count_sq.c.work_id == Work.work_id)
        .outerjoin(concept_sq, concept_sq.c.work_id == Work.work_id)
        .outerjoin(claim_sq, claim_sq.c.work_id == Work.work_id)
        .where(Work.author_id == author_id)
        .order_by(Work.title)
    )

    rows = db.execute(works_query).all()
    works: list[WorkSummary] = []
    for row in rows:
        pub_date = row.publication_date if isinstance(row.publication_date, dict) else {}
        year = pub_date.get("year") if isinstance(pub_date.get("year"), int) else None
        conf = pub_date.get("confidence")
        conf_f = float(conf) if isinstance(conf, (int, float)) else None
        method = str(pub_date.get("method") or "").strip().lower()
        date_confidence = None
        if year is not None:
            date_confidence = "heuristic" if method in {"", "heuristic_url_year"} and (conf_f is None or conf_f <= 0.3) else "evidence"

        works.append(
            WorkSummary(
                work_id=row.work_id,
                title=row.title,
                title_canonical=row.title_canonical,
                publication_year=year,
                date_confidence=date_confidence,
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
