from __future__ import annotations

__all__ = [
    "AuthorLifespanCandidate",
    "AuthorLifespanResolver",
    "PublicationDateCandidate",
    "PublicationDateResolver",
]

from ingest_service.metadata.author_lifespan_resolver import AuthorLifespanCandidate, AuthorLifespanResolver
from ingest_service.metadata.publication_date_resolver import PublicationDateCandidate, PublicationDateResolver
