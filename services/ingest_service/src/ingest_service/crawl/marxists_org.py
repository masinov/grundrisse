"""Multi-stage crawler for marxists.org corpus."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from grundrisse_core.hashing import sha256_hex
from ingest_service.crawl.catalog import UrlCatalog, WorkCatalog
from ingest_service.crawl.http_client import RateLimitedHttpClient
from ingest_service.utils.url_canonicalization import (
    canonicalize_url,
    get_directory_prefix,
    is_html_url,
    is_marxists_org_url,
    is_same_directory,
)


class MarxistsOrgCrawler:
    """
    Multi-stage crawler for marxists.org.

    Implements:
    1. Seed discovery (landing page -> language roots)
    2. Language-level discovery (author indexes)
    3. Author-level discovery (work TOCs)
    4. Work-level discovery (page URLs within work directory)
    """

    def __init__(
        self,
        session: Session,
        crawl_run_id: uuid.UUID,
        http_client: RateLimitedHttpClient,
        data_dir: Path,
    ):
        """
        Initialize crawler.

        Args:
            session: Database session
            crawl_run_id: Current crawl run ID
            http_client: HTTP client for fetching
            data_dir: Directory for raw snapshots
        """
        self.session = session
        self.crawl_run_id = crawl_run_id
        self.http_client = http_client
        self.data_dir = data_dir
        self.url_catalog = UrlCatalog(session, crawl_run_id)
        self.work_catalog = WorkCatalog(session, crawl_run_id)

    def discover_seed_urls(self) -> list[str]:
        """
        Discover seed URLs (language roots) from marxists.org landing page.

        Returns:
            List of language root URLs
        """
        seed_url = "https://www.marxists.org/"
        result = self.http_client.fetch(seed_url)

        if result.status_code != 200 or not result.content:
            return []

        # Parse HTML to find language links
        soup = BeautifulSoup(result.content, "lxml")
        language_urls: Set[str] = set()

        # Look for links that point to language-specific areas
        # Common patterns: /archive/, /espanol/, /francais/, etc.
        for link in soup.find_all("a", href=True):
            href = link["href"]
            full_url = urljoin(seed_url, href)

            if not is_marxists_org_url(full_url):
                continue

            # Language roots often have these path patterns
            path = urlparse(full_url).path.lower()
            if any(pattern in path for pattern in ["/archive/", "/espanol/", "/francais/", "/deutsch/", "/italiano/"]):
                language_urls.add(full_url)

        return list(language_urls)

    def discover_author_pages(self, language_root_url: str, max_pages: int = 100) -> list[str]:
        """
        Discover author index/archive pages from a language root.

        Args:
            language_root_url: URL of language root
            max_pages: Maximum pages to discover

        Returns:
            List of author page URLs
        """
        result = self.http_client.fetch(language_root_url)

        if result.status_code != 200 or not result.content:
            return []

        soup = BeautifulSoup(result.content, "lxml")
        author_urls: Set[str] = set()

        # Find links within the same language area
        for link in soup.find_all("a", href=True):
            href = link["href"]
            full_url = urljoin(language_root_url, href)

            if not is_marxists_org_url(full_url) or not is_html_url(full_url):
                continue

            # Author pages are typically in /archive/author/ or similar
            path = urlparse(full_url).path
            if "/archive/" in path.lower():
                author_urls.add(full_url)

            if len(author_urls) >= max_pages:
                break

        return list(author_urls)

    def discover_work_directories(self, author_page_url: str, max_works: int = 50) -> list[dict]:
        """
        Discover work directories from an author page.

        Args:
            author_page_url: URL of author page
            max_works: Maximum works to discover

        Returns:
            List of work metadata dicts with root_url, author, title, language
        """
        result = self.http_client.fetch(author_page_url)

        if result.status_code != 200 or not result.content:
            return []

        soup = BeautifulSoup(result.content, "lxml")
        works: list[dict] = []

        # Extract author name from page (heuristic)
        author_name = self._extract_author_name(soup, author_page_url)

        # Extract language from URL path
        language = self._extract_language(author_page_url)

        # Find work links
        work_urls: Set[str] = set()
        for link in soup.find_all("a", href=True):
            href = link["href"]
            full_url = urljoin(author_page_url, href)

            if not is_marxists_org_url(full_url) or not is_html_url(full_url):
                continue

            # Skip if same as author page
            if full_url == author_page_url:
                continue

            # Work directories are typically subdirectories
            if full_url.startswith(author_page_url.rstrip("index.htm").rstrip("index.html")):
                work_urls.add(full_url)

        # For each unique directory, create work metadata
        seen_dirs: Set[str] = set()
        for url in work_urls:
            dir_prefix = get_directory_prefix(url)
            if dir_prefix in seen_dirs:
                continue

            seen_dirs.add(dir_prefix)

            # Try to extract title from link text or directory name
            work_title = self._extract_work_title(url)

            works.append({
                "root_url": url,
                "author_name": author_name,
                "work_title": work_title,
                "language": language,
            })

            if len(works) >= max_works:
                break

        return works

    def discover_work_pages(self, root_url: str, max_pages: int = 100) -> list[str]:
        """
        Discover all pages within a work directory.

        Args:
            root_url: Root URL of the work
            max_pages: Maximum pages to discover

        Returns:
            List of page URLs in the work
        """
        from ingest_service.crawl.discover import discover_work_urls

        # Reuse existing work URL discovery logic
        result = discover_work_urls(root_url, max_pages=max_pages)
        return result.urls

    def snapshot_url(self, url: str) -> tuple[str, str] | None:
        """
        Fetch and snapshot a URL to disk.

        Args:
            url: URL to snapshot

        Returns:
            Tuple of (sha256, raw_path) if successful, None otherwise
        """
        # Get existing entry to check for ETag/Last-Modified
        entry = self.url_catalog.get_url(url)
        etag = entry.etag if entry else None
        last_modified = entry.last_modified if entry else None

        # Fetch URL
        result = self.http_client.fetch(url, etag=etag, last_modified=last_modified)

        # Handle 304 Not Modified
        if result.status_code == 304:
            self.url_catalog.update_fetch_result(
                url,
                status_code=304,
                content_sha256=entry.content_sha256 if entry else None,
                raw_path=entry.raw_path if entry else None,
            )
            return (entry.content_sha256, entry.raw_path) if entry else None

        # Handle errors
        if result.status_code != 200 or not result.content:
            self.url_catalog.update_fetch_result(
                url,
                status_code=result.status_code,
                error_message=result.error,
            )
            return None

        # Compute checksum
        checksum = sha256_hex(result.content)

        # Write to disk
        raw_path = self.data_dir / f"{checksum}.html"
        raw_path.write_bytes(result.content)

        # Write metadata
        meta_path = self.data_dir / f"{checksum}.meta.json"
        import json

        meta = {
            "url": url,
            "fetched_at": result.fetched_at.isoformat(),
            "status_code": result.status_code,
            "content_type": result.content_type,
            "etag": result.etag,
            "last_modified": result.last_modified,
        }
        meta_path.write_text(json.dumps(meta, indent=2))

        # Update catalog
        self.url_catalog.update_fetch_result(
            url,
            status_code=result.status_code,
            content_sha256=checksum,
            content_type=result.content_type,
            etag=result.etag,
            last_modified=result.last_modified,
            raw_path=str(raw_path),
        )

        return (checksum, str(raw_path))

    def _extract_author_name(self, soup: BeautifulSoup, url: str) -> str:
        """Extract author name from page (heuristic)."""
        # Try to find author name in title or h1
        title = soup.find("title")
        if title and title.string:
            # Common pattern: "Author Name Archive"
            title_text = title.string.strip()
            if "Archive" in title_text:
                return title_text.replace("Archive", "").strip()

        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)

        # Fallback: extract from URL path
        path = urlparse(url).path
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            # Typically: /archive/marx/ or similar
            return parts[-1].replace("-", " ").title()

        return "Unknown Author"

    def _extract_language(self, url: str) -> str:
        """Extract language code from URL (heuristic)."""
        path = urlparse(url).path.lower()

        # Common language paths
        if "/espanol/" in path or "/spanish/" in path:
            return "es"
        if "/francais/" in path or "/french/" in path:
            return "fr"
        if "/deutsch/" in path or "/german/" in path:
            return "de"
        if "/italiano/" in path or "/italian/" in path:
            return "it"
        if "/russian/" in path or "/русский/" in path:
            return "ru"
        if "/chinese/" in path or "/中文/" in path:
            return "zh"

        # Default to English
        return "en"

    def _extract_work_title(self, url: str) -> str:
        """Extract work title from URL (heuristic)."""
        path = urlparse(url).path
        parts = [p for p in path.split("/") if p and p not in ("index.htm", "index.html")]

        if parts:
            # Use last directory name as title
            title = parts[-1].replace("-", " ").replace("_", " ").title()
            return title

        return "Untitled Work"
