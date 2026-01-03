"""Link graph builder for Phase 1 discovery."""

from __future__ import annotations

import sys
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
        *,
        resume: bool = False,
    ) -> dict:
        """
        Crawl entire site and build parent-child relationships.

        Args:
            seed_url: Starting URL
            max_depth: Maximum depth to crawl
            max_urls: Maximum total URLs to discover
            resume: If True, resume from existing URLs in this crawl run

        Returns:
            Statistics dictionary
        """
        queue: list[tuple[str, int, uuid.UUID | None]] = []
        seen_urls: Set[str] = set()
        stats = {
            "urls_discovered": 0,
            "urls_fetched": 0,
            "urls_failed": 0,
            "max_depth_reached": 0,
        }

        if resume:
            print(f"🔄 Resuming link graph build for crawl run {self.crawl_run_id}", file=sys.stderr)
            print(f"   Loading existing URLs...", file=sys.stderr)

            # Load all existing URLs for this crawl run
            existing_entries = self.session.execute(
                select(UrlCatalogEntry)
                .where(UrlCatalogEntry.crawl_run_id == self.crawl_run_id)
            ).scalars().all()

            # Add all URLs to seen set
            for entry in existing_entries:
                seen_urls.add(entry.url_canonical)

            # Rebuild queue:
            # 1. Retry failed URLs (for 403 errors, rate limits, etc.)
            # 2. Re-extract links from fetched URLs to find new children
            failed_urls_to_retry = []
            for entry in existing_entries:
                # Retry failed URLs (403, timeouts, network errors, etc.)
                if entry.status == "error" and entry.depth < max_depth:
                    failed_urls_to_retry.append(entry)
                    # Remove from seen set so it will be retried
                    seen_urls.discard(entry.url_canonical)
                    queue.append((entry.url_canonical, entry.depth, entry.parent_url_id))

                # Re-extract links from successfully fetched URLs
                elif entry.status == "fetched" and entry.depth < max_depth and entry.raw_path:
                    try:
                        # Re-extract links from this URL's content
                        raw_path = Path(entry.raw_path)
                        if raw_path.exists():
                            html_content = raw_path.read_bytes()
                            child_urls = self._extract_links(html_content, base_url=entry.url_canonical)

                            # Add children that haven't been seen yet to the queue
                            for child_url in child_urls:
                                child_canonical = canonicalize_url(child_url)
                                if child_canonical not in seen_urls:
                                    queue.append((child_canonical, entry.depth + 1, entry.url_id))
                    except Exception:
                        # Skip if can't read raw file
                        pass

            if failed_urls_to_retry:
                print(f"   Found {len(failed_urls_to_retry)} failed URLs to retry", file=sys.stderr)

            # Count existing stats
            stats["urls_discovered"] = len(existing_entries)
            stats["urls_fetched"] = sum(1 for e in existing_entries if e.status == "fetched")
            stats["urls_failed"] = sum(1 for e in existing_entries if e.status == "error")
            stats["max_depth_reached"] = max((e.depth for e in existing_entries), default=0)

            print(f"   Loaded {len(seen_urls):,} existing URLs", file=sys.stderr)
            print(f"   Found {len(queue):,} new URLs to explore", file=sys.stderr)
            print(f"   Resuming from depth: {stats['max_depth_reached']}", file=sys.stderr)
            print("", file=sys.stderr)
        else:
            queue = [(seed_url, 0, None)]
            print(f"🌐 Starting link graph build from {seed_url}", file=sys.stderr)
            print(f"   Max depth: {max_depth}, Max URLs: {max_urls}", file=sys.stderr)
            print("", file=sys.stderr)

        while queue and len(seen_urls) < max_urls:
            url, depth, parent_id = queue.pop(0)

            # Canonicalize URL
            url_canonical = canonicalize_url(url)

            # Skip if already seen
            if url_canonical in seen_urls:
                continue

            # Skip if out of scope (but always allow seed URL at depth 0)
            if depth > 0 and not self.scope_filter(url_canonical):
                continue

            # Skip if exceeds max depth
            if depth > max_depth:
                continue

            # Skip non-HTML URLs
            if not is_html_url(url_canonical):
                continue

            seen_urls.add(url_canonical)
            stats["max_depth_reached"] = max(stats["max_depth_reached"], depth)

            # Check if URL already exists (globally - unique constraint)
            existing = self.session.execute(
                select(UrlCatalogEntry)
                .where(UrlCatalogEntry.url_canonical == url_canonical)
            ).scalar_one_or_none()

            if existing:
                # URL exists from a previous crawl or earlier in this crawl
                if existing.crawl_run_id == self.crawl_run_id:
                    # Already in this crawl - update depth if shorter path
                    if depth < existing.depth:
                        existing.depth = depth
                        existing.parent_url_id = parent_id
                    continue
                else:
                    # From a different crawl - reassign to this crawl
                    print(f"   Reusing URL from previous crawl: {url_canonical} (status: {existing.status})", file=sys.stderr)
                    existing.crawl_run_id = self.crawl_run_id
                    existing.depth = depth
                    existing.parent_url_id = parent_id
                    entry = existing
                    stats["urls_discovered"] += 1

                    # Always re-fetch seed URL (depth 0) to get latest links
                    # For other URLs, reuse cached data if available
                    if depth == 0:
                        print(f"   Re-fetching seed URL to get latest links...", file=sys.stderr)
                        # Don't reuse cached data - fall through to fetch below
                    elif existing.status == "fetched" and existing.raw_path:
                        stats["urls_fetched"] += 1
                        # Re-extract links to continue crawling children
                        try:
                            raw_path = Path(existing.raw_path)
                            if raw_path.exists():
                                html_content = raw_path.read_bytes()
                                child_urls = self._extract_links(html_content, base_url=url_canonical)
                                entry.child_count = len(child_urls)

                                print(f"   Reused cached data, found {len(child_urls)} child URLs", file=sys.stderr)

                                # Add children to queue
                                for child_url in child_urls:
                                    child_canonical = canonicalize_url(child_url)
                                    if child_canonical not in seen_urls:
                                        queue.append((child_canonical, depth + 1, entry.url_id))
                            else:
                                print(f"   Warning: raw_path doesn't exist: {raw_path}", file=sys.stderr)
                        except Exception as e:
                            print(f"   Error reusing cached data: {e}", file=sys.stderr)
                        continue  # Skip to next URL in queue
            else:
                # New URL - add to catalog
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

                    # Progress logging
                    if stats["urls_fetched"] % 10 == 0:
                        print(
                            f"✓ Fetched {stats['urls_fetched']:,} URLs | "
                            f"Discovered {stats['urls_discovered']:,} | "
                            f"Failed {stats['urls_failed']} | "
                            f"Queue {len(queue):,} | "
                            f"Depth {depth}/{stats['max_depth_reached']}",
                            file=sys.stderr,
                        )

                else:
                    # Failed fetch
                    entry.status = "error"
                    entry.http_status = result.status_code
                    entry.error_message = result.error
                    stats["urls_failed"] += 1
                    print(f"   ✗ Fetch failed: {url_canonical} (status {result.status_code}): {result.error}", file=sys.stderr)

                    # If 403 Forbidden, add extra backoff to avoid rate limiting
                    if result.status_code == 403:
                        print(f"   ⏸  Rate limit detected (403), adding 5s backoff...", file=sys.stderr)
                        time.sleep(5)

            except Exception as e:
                entry.status = "error"
                entry.error_message = str(e)
                stats["urls_failed"] += 1
                print(f"   ✗ Fetch error: {url_canonical}: {e}", file=sys.stderr)

            # Commit periodically
            if stats["urls_discovered"] % 100 == 0:
                self.session.commit()
                print(f"💾 Checkpoint: Committed {stats['urls_discovered']} URLs to database", file=sys.stderr)

        # Final commit
        self.session.commit()

        print("", file=sys.stderr)
        print("✅ Link graph build complete!", file=sys.stderr)
        print(f"   URLs discovered: {stats['urls_discovered']:,}", file=sys.stderr)
        print(f"   URLs fetched: {stats['urls_fetched']:,}", file=sys.stderr)
        print(f"   URLs failed: {stats['urls_failed']}", file=sys.stderr)
        print(f"   Max depth: {stats['max_depth_reached']}", file=sys.stderr)
        print("", file=sys.stderr)

        return stats

    def _extract_links(self, html_content: bytes, base_url: str) -> list[str]:
        """Extract all links from HTML content."""
        try:
            soup = BeautifulSoup(html_content, "lxml")
            links = []

            # Extract from <a> tags
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]

                # Skip anchors, mailto, javascript
                if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
                    continue

                # Make absolute
                absolute_url = urljoin(base_url, href)
                links.append(absolute_url)

            # Also extract from <area> tags (image maps)
            for area_tag in soup.find_all("area", href=True):
                href = area_tag["href"]

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
