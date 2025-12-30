"""HTTP client with rate limiting, caching, and politeness for crawling."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx


@dataclass
class FetchResult:
    """Result of fetching a URL."""

    url: str
    status_code: int
    content: bytes | None
    content_type: str | None
    etag: str | None
    last_modified: str | None
    fetched_at: datetime
    error: str | None = None
    from_cache: bool = False


class RateLimitedHttpClient:
    """
    HTTP client with rate limiting, caching, and politeness features.

    Features:
    - Fixed crawl delay between requests
    - Respects ETag and Last-Modified headers
    - User-Agent identification
    - Retry logic for transient failures
    - Timeout configuration
    """

    def __init__(
        self,
        crawl_delay: float = 0.5,
        user_agent: str = "grundrisse-crawler/0.1 (marxists.org corpus builder)",
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        """
        Initialize HTTP client.

        Args:
            crawl_delay: Delay in seconds between requests
            user_agent: User-Agent string to identify the crawler
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries for transient failures
        """
        self.crawl_delay = crawl_delay
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_retries = max_retries
        self.last_request_time: float | None = None

        # Create HTTP client with timeout
        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
        )

    def _apply_rate_limit(self) -> None:
        """Apply rate limiting by sleeping if needed."""
        if self.last_request_time is not None:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.crawl_delay:
                time.sleep(self.crawl_delay - elapsed)

        self.last_request_time = time.time()

    def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchResult:
        """
        Fetch a URL with rate limiting and conditional requests.

        Args:
            url: URL to fetch
            etag: Optional ETag for conditional request
            last_modified: Optional Last-Modified for conditional request

        Returns:
            FetchResult with content and metadata
        """
        # Apply rate limiting
        self._apply_rate_limit()

        # Build conditional headers
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        # Retry logic
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.get(url, headers=headers)

                # Handle 304 Not Modified
                if response.status_code == 304:
                    return FetchResult(
                        url=url,
                        status_code=304,
                        content=None,
                        content_type=None,
                        etag=etag,
                        last_modified=last_modified,
                        fetched_at=datetime.utcnow(),
                        from_cache=True,
                    )

                # Success
                if response.status_code == 200:
                    return FetchResult(
                        url=url,
                        status_code=200,
                        content=response.content,
                        content_type=response.headers.get("Content-Type"),
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                        fetched_at=datetime.utcnow(),
                    )

                # Non-200/304 status
                return FetchResult(
                    url=url,
                    status_code=response.status_code,
                    content=None,
                    content_type=None,
                    etag=None,
                    last_modified=None,
                    fetched_at=datetime.utcnow(),
                    error=f"HTTP {response.status_code}",
                )

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    # Exponential backoff
                    time.sleep(2 ** attempt)
                    continue

            except httpx.RequestError as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue

            except Exception as e:
                last_error = e
                break

        # All retries failed
        return FetchResult(
            url=url,
            status_code=0,
            content=None,
            content_type=None,
            etag=None,
            last_modified=None,
            fetched_at=datetime.utcnow(),
            error=str(last_error) if last_error else "Unknown error",
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self) -> RateLimitedHttpClient:
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.close()
