"""Author endpoints."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from api.deps import DbSession
from grundrisse_core.db.models import Author, AuthorAlias, Edition, ExtractionRun, Paragraph, Work

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

    # Get works with paragraph counts and extraction status
    works_query = (
        select(
            Work.work_id,
            Work.title,
            Work.title_canonical,
            Work.publication_date,
            Edition.edition_id,
            Edition.language,
            func.count(Paragraph.paragraph_id).label("paragraph_count"),
            func.count(ExtractionRun.run_id).label("extraction_count"),
        )
        .select_from(Work)
        .join(Edition, Edition.work_id == Work.work_id)
        .outerjoin(Paragraph, Paragraph.edition_id == Edition.edition_id)
        .outerjoin(ExtractionRun, ExtractionRun.edition_id == Edition.edition_id)
        .where(Work.author_id == author_id)
        .group_by(Work.work_id, Work.title, Work.title_canonical, Work.publication_date, Edition.edition_id, Edition.language)
        .order_by(Work.publication_date["year"].astext.cast(db.bind.dialect.type_descriptor(type(0))).asc().nulls_last())
    )

    rows = db.execute(works_query).all()

    # Deduplicate works (take first edition per work)
    seen_works = set()
    works = []
    for row in rows:
        if row.work_id in seen_works:
            continue
        seen_works.add(row.work_id)

        pub_date = row.publication_date if isinstance(row.publication_date, dict) else {}
        works.append(
            WorkSummary(
                work_id=row.work_id,
                title=row.title,
                title_canonical=row.title_canonical,
                publication_year=pub_date.get("year"),
                date_confidence=pub_date.get("confidence") if pub_date.get("confidence") else (
                    "heuristic" if pub_date.get("year") else None
                ),
                language=row.language,
                paragraph_count=row.paragraph_count or 0,
                has_extractions=row.extraction_count > 0,
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
