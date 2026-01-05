"""Search endpoint."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from api.deps import DbSession
from grundrisse_core.db.models import Author, Edition, Paragraph, Work

router = APIRouter()


class AuthorSearchResult(BaseModel):
    """Author search result."""

    author_id: UUID
    name_canonical: str
    work_count: int

    model_config = {"from_attributes": True}


class WorkSearchResult(BaseModel):
    """Work search result."""

    work_id: UUID
    title: str
    author_name: str
    publication_year: int | None

    model_config = {"from_attributes": True}


class SearchResponse(BaseModel):
    """Combined search results."""

    query: str
    authors: list[AuthorSearchResult]
    works: list[WorkSearchResult]


@router.get("", response_model=SearchResponse)
def search(
    db: DbSession,
    q: str = Query(min_length=2, description="Search query"),
    type: Literal["all", "authors", "works"] = "all",
    limit: int = Query(default=20, ge=1, le=100),
) -> SearchResponse:
    """Search authors and works by name/title."""
    authors: list[AuthorSearchResult] = []
    works: list[WorkSearchResult] = []

    search_pattern = f"%{q}%"

    if type in ("all", "authors"):
        # Search authors
        author_query = (
            select(
                Author.author_id,
                Author.name_canonical,
                func.count(Work.work_id).label("work_count"),
            )
            .select_from(Author)
            .outerjoin(Work, Work.author_id == Author.author_id)
            .where(Author.name_canonical.ilike(search_pattern))
            .group_by(Author.author_id, Author.name_canonical)
            .order_by(func.count(Work.work_id).desc())
            .limit(limit if type == "authors" else limit // 2)
        )

        author_rows = db.execute(author_query).all()
        authors = [
            AuthorSearchResult(
                author_id=row.author_id,
                name_canonical=row.name_canonical,
                work_count=row.work_count or 0,
            )
            for row in author_rows
        ]

    if type in ("all", "works"):
        # Search works
        work_query = (
            select(
                Work.work_id,
                Work.title,
                Work.publication_date,
                Author.name_canonical.label("author_name"),
            )
            .select_from(Work)
            .join(Author, Author.author_id == Work.author_id)
            .where(Work.title.ilike(search_pattern))
            .order_by(Work.title)
            .limit(limit if type == "works" else limit // 2)
        )

        work_rows = db.execute(work_query).all()
        works = [
            WorkSearchResult(
                work_id=row.work_id,
                title=row.title,
                author_name=row.author_name,
                publication_year=(
                    row.publication_date.get("year")
                    if isinstance(row.publication_date, dict)
                    else None
                ),
            )
            for row in work_rows
        ]

    return SearchResponse(query=q, authors=authors, works=works)
