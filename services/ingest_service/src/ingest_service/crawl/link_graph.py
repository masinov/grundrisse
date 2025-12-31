"""Link graph builder for Phase 1 discovery."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from grundrisse_core.db.models import UrlCatalogEntry
from grundrisse_core.hashing import sha256_hex
from ingest_service.crawl.http_client import RateLimitedHttpClient
from ingest_service.utils.url_canonicalization import (
    canonicalize_url,
    is_html_url,
    is_marxists_org_url,
)


class LinkGraphBuilder:
    """
    Phase 1: Build complete hyperlink graph without classification.

    This is the cheap phase - just HTTP requests to discover structure.
    No LLM calls, just URL discovery and link graph construction.
    """

    def __init__(
        self,
        session: Session,
        crawl_run_id: uuid.UUID,
        http_client: RateLimitedHttpClient,
        data_dir: Path,
        *,
        scope_filter: callable = None,
    ):
        """
        Initialize link graph builder.

        Args:
            session: Database session
            crawl_run_id: Current crawl run ID
            http_client: HTTP client for fetching
            data_dir: Directory for raw snapshots
            scope_filter: Optional callable(url) -> bool to filter URLs
        """
        self.session = session
        self.crawl_run_id = crawl_run_id
        self.http_client = http_client
        self.data_dir = data_dir
        self.scope_filter = scope_filter or is_marxists_org_url

    def build_graph(
        self,
        seed_url: str,
        max_depth: int = 10,
        max_urls: int = 10000,
    ) -> dict:
        """
        Crawl entire site and build parent-child relationships.

        Args:
            seed_url: Starting URL
            max_depth: Maximum depth to crawl
            max_urls: Maximum total URLs to discover

        Returns:
            Statistics dictionary
        """
        queue: list[tuple[str, int, uuid.UUID | None]] = [(seed_url, 0, None)]
        seen_urls: Set[str] = set()
        stats = {
            "urls_discovered": 0,
            "urls_fetched": 0,
            "urls_failed": 0,
            "max_depth_reached": 0,
        }

        while queue and len(seen_urls) < max_urls:
            url, depth, parent_id = queue.pop(0)

            # Canonicalize URL
            url_canonical = canonicalize_url(url)

            # Skip if already seen
            if url_canonical in seen_urls:
                continue

            # Skip if out of scope
            if not self.scope_filter(url_canonical):
                continue

            # Skip if exceeds max depth
            if depth > max_depth:
                continue

            # Skip non-HTML URLs
            if not is_html_url(url_canonical):
                continue

            seen_urls.add(url_canonical)
            stats["max_depth_reached"] = max(stats["max_depth_reached"], depth)

            # Check if URL already in catalog
            existing = self.session.execute(
                select(UrlCatalogEntry).where(UrlCatalogEntry.url_canonical == url_canonical)
            ).scalar_one_or_none()

            if existing:
                # Update depth and parent if this is a shorter path
                if depth < existing.depth:
                    existing.depth = depth
                    existing.parent_url_id = parent_id
                continue

            # Add to catalog
            entry = UrlCatalogEntry(
                url_canonical=url_canonical,
                discovered_from_url=self._get_parent_url(parent_id) if parent_id else None,
                crawl_run_id=self.crawl_run_id,
                depth=depth,
                parent_url_id=parent_id,
                status="new",
            )
            self.session.add(entry)
            self.session.flush()

            stats["urls_discovered"] += 1

            # Fetch and extract links
            try:
                result = self.http_client.fetch(url_canonical)

                if result.status_code == 200 and result.content:
                    # Store snapshot
                    checksum = sha256_hex(result.content)
                    raw_path = self.data_dir / f"{checksum}.html"
                    raw_path.write_bytes(result.content)

                    # Update entry
                    entry.status = "fetched"
                    entry.http_status = result.status_code
                    entry.content_type = result.content_type
                    entry.etag = result.etag
                    entry.last_modified = result.last_modified
                    entry.content_sha256 = checksum
                    entry.raw_path = str(raw_path)
                    entry.fetched_at = result.fetched_at

                    stats["urls_fetched"] += 1

                    # Extract links
                    child_urls = self._extract_links(result.content, base_url=url_canonical)
                    entry.child_count = len(child_urls)

                    # Add children to queue
                    for child_url in child_urls:
                        child_canonical = canonicalize_url(child_url)
                        if child_canonical not in seen_urls:
                            queue.append((child_canonical, depth + 1, entry.url_id))

                else:
                    # Failed fetch
                    entry.status = "error"
                    entry.http_status = result.status_code
                    entry.error_message = result.error
                    stats["urls_failed"] += 1

            except Exception as e:
                entry.status = "error"
                entry.error_message = str(e)
                stats["urls_failed"] += 1

            # Commit periodically
            if stats["urls_discovered"] % 100 == 0:
                self.session.commit()

        # Final commit
        self.session.commit()

        return stats

    def _extract_links(self, html_content: bytes, base_url: str) -> list[str]:
        """Extract all links from HTML content."""
        try:
            soup = BeautifulSoup(html_content, "lxml")
            links = []

            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]

                # Skip anchors, mailto, javascript
                if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
                    continue

                # Make absolute
                absolute_url = urljoin(base_url, href)
                links.append(absolute_url)

            return links

        except Exception:
            return []

    def _get_parent_url(self, parent_id: uuid.UUID) -> str | None:
        """Get parent URL from catalog."""
        parent = self.session.get(UrlCatalogEntry, parent_id)
        return parent.url_canonical if parent else None
