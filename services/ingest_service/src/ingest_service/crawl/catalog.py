"""URL catalog manager for tracking discovered URLs and crawl state."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from grundrisse_core.db.models import CrawlRun, UrlCatalogEntry, WorkDiscovery
from ingest_service.utils.url_canonicalization import canonicalize_url


class UrlCatalog:
    """
    Manager for URL catalog operations.

    Handles:
    - URL discovery and deduplication
    - Status tracking
    - Conditional fetching based on ETag/Last-Modified
    """

    def __init__(self, session: Session, crawl_run_id: uuid.UUID):
        """
        Initialize URL catalog.

        Args:
            session: Database session
            crawl_run_id: ID of the current crawl run
        """
        self.session = session
        self.crawl_run_id = crawl_run_id

    def add_url(
        self,
        url: str,
        *,
        discovered_from_url: str | None = None,
        status: str = "new",
    ) -> UrlCatalogEntry | None:
        """
        Add a URL to the catalog if not already present.

        Args:
            url: URL to add
            discovered_from_url: URL where this was discovered from
            status: Initial status (default: "new")

        Returns:
            UrlCatalogEntry if newly added, None if already exists
        """
        url_canonical = canonicalize_url(url)

        # Check if URL already exists
        existing = self.session.execute(
            select(UrlCatalogEntry).where(UrlCatalogEntry.url_canonical == url_canonical)
        ).scalar_one_or_none()

        if existing:
            return None

        # Create new entry
        entry = UrlCatalogEntry(
            url_canonical=url_canonical,
            discovered_from_url=discovered_from_url,
            discovered_at=datetime.utcnow(),
            crawl_run_id=self.crawl_run_id,
            status=status,
        )

        self.session.add(entry)
        return entry

    def get_url(self, url: str) -> UrlCatalogEntry | None:
        """
        Get URL entry from catalog.

        Args:
            url: URL to look up

        Returns:
            UrlCatalogEntry if found, None otherwise
        """
        url_canonical = canonicalize_url(url)
        return self.session.execute(
            select(UrlCatalogEntry).where(UrlCatalogEntry.url_canonical == url_canonical)
        ).scalar_one_or_none()

    def update_fetch_result(
        self,
        url: str,
        *,
        status_code: int,
        content_sha256: str | None = None,
        content_type: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        raw_path: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """
        Update URL entry with fetch results.

        Args:
            url: URL that was fetched
            status_code: HTTP status code
            content_sha256: SHA256 of content
            content_type: Content-Type header
            etag: ETag header
            last_modified: Last-Modified header
            raw_path: Path to raw snapshot file
            error_message: Error message if fetch failed
        """
        url_canonical = canonicalize_url(url)
        entry = self.get_url(url_canonical)

        if not entry:
            return

        # Determine status based on results
        if status_code == 200:
            new_status = "fetched"
        elif status_code == 304:
            new_status = "cached"
        elif status_code == 404:
            new_status = "not_found"
        elif status_code >= 400:
            new_status = "error"
        else:
            new_status = "skipped"

        # Update entry
        entry.http_status = status_code
        entry.status = new_status
        entry.content_sha256 = content_sha256
        entry.content_type = content_type
        entry.etag = etag
        entry.last_modified = last_modified
        entry.raw_path = raw_path
        entry.fetched_at = datetime.utcnow()
        entry.error_message = error_message

    def get_urls_by_status(self, status: str, limit: int = 100) -> Sequence[UrlCatalogEntry]:
        """
        Get URLs with a specific status.

        Args:
            status: Status to filter by
            limit: Maximum number of URLs to return

        Returns:
            List of UrlCatalogEntry objects
        """
        return (
            self.session.execute(
                select(UrlCatalogEntry)
                .where(UrlCatalogEntry.status == status)
                .where(UrlCatalogEntry.crawl_run_id == self.crawl_run_id)
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def get_pending_urls(self, limit: int = 100) -> Sequence[UrlCatalogEntry]:
        """
        Get URLs that need to be fetched.

        Args:
            limit: Maximum number of URLs to return

        Returns:
            List of UrlCatalogEntry objects with status "new"
        """
        return self.get_urls_by_status("new", limit)


class WorkCatalog:
    """
    Manager for work discovery catalog.

    Tracks discovered works and their ingestion status.
    """

    def __init__(self, session: Session, crawl_run_id: uuid.UUID):
        """
        Initialize work catalog.

        Args:
            session: Database session
            crawl_run_id: ID of the current crawl run
        """
        self.session = session
        self.crawl_run_id = crawl_run_id

    def add_work(
        self,
        root_url: str,
        author_name: str,
        work_title: str,
        language: str,
        page_urls: list[str],
    ) -> WorkDiscovery:
        """
        Add a discovered work to the catalog.

        Args:
            root_url: Root URL for the work
            author_name: Canonical author name
            work_title: Work title
            language: Language code
            page_urls: List of page URLs in the work

        Returns:
            WorkDiscovery entry
        """
        work = WorkDiscovery(
            crawl_run_id=self.crawl_run_id,
            root_url=root_url,
            author_name=author_name,
            work_title=work_title,
            language=language,
            page_urls=page_urls,
            discovered_at=datetime.utcnow(),
            ingestion_status="pending",
        )

        self.session.add(work)
        return work

    def get_pending_works(self, limit: int = 100) -> Sequence[WorkDiscovery]:
        """
        Get works that need to be ingested.

        Args:
            limit: Maximum number of works to return

        Returns:
            List of WorkDiscovery objects
        """
        return (
            self.session.execute(
                select(WorkDiscovery)
                .where(WorkDiscovery.ingestion_status == "pending")
                .where(WorkDiscovery.crawl_run_id == self.crawl_run_id)
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def mark_work_ingested(self, discovery_id: uuid.UUID, edition_id: uuid.UUID) -> None:
        """
        Mark a work as successfully ingested.

        Args:
            discovery_id: Work discovery ID
            edition_id: Edition ID from ingestion
        """
        work = self.session.get(WorkDiscovery, discovery_id)
        if work:
            work.ingestion_status = "ingested"
            work.edition_id = edition_id

    def mark_work_failed(self, discovery_id: uuid.UUID, error: str) -> None:
        """
        Mark a work as failed to ingest.

        Args:
            discovery_id: Work discovery ID
            error: Error message
        """
        work = self.session.get(WorkDiscovery, discovery_id)
        if work:
            work.ingestion_status = "failed"
