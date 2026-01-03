"""HTTP client with rate limiting, caching, and politeness for crawling."""

from __future__ import annotations

import os
import subprocess
import sys
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
    - WSL fallback to Windows curl.exe when network is unreachable
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

        # Detect WSL and find Windows curl.exe for fallback
        self.is_wsl = self._detect_wsl()
        self.windows_curl_path = self._find_windows_curl() if self.is_wsl else None
        if self.is_wsl and self.windows_curl_path:
            print(f"   💡 WSL detected: Will use {self.windows_curl_path} as fallback for network issues", file=sys.stderr)

    def _detect_wsl(self) -> bool:
        """Detect if running in WSL environment."""
        return os.path.exists("/proc/version") and "microsoft" in open("/proc/version").read().lower()

    def _find_windows_curl(self) -> str | None:
        """Find Windows curl.exe in WSL environment."""
        # Common Windows curl.exe paths in WSL
        candidates = [
            "/mnt/c/WINDOWS/system32/curl.exe",
            "/mnt/c/Windows/System32/curl.exe",
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    def _apply_rate_limit(self) -> None:
        """Apply rate limiting by sleeping if needed."""
        if self.last_request_time is not None:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.crawl_delay:
                time.sleep(self.crawl_delay - elapsed)

        self.last_request_time = time.time()

    def _fetch_with_windows_curl(self, url: str) -> FetchResult:
        """
        Fallback: Fetch using Windows curl.exe from WSL.

        This is used when httpx fails with network errors in WSL.
        """
        if not self.windows_curl_path:
            return FetchResult(
                url=url,
                status_code=0,
                content=None,
                content_type=None,
                etag=None,
                last_modified=None,
                fetched_at=datetime.utcnow(),
                error="Windows curl not available",
            )

        try:
            # Build curl command
            cmd = [
                self.windows_curl_path,
                "-s",  # Silent
                "-i",  # Include headers in output
                "-L",  # Follow redirects
                "-A", self.user_agent,  # User-Agent
                "--max-time", str(int(self.timeout)),
                url,
            ]

            # Run curl
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.timeout + 5,  # Add buffer to subprocess timeout
            )

            if result.returncode != 0:
                error_msg = result.stderr.decode('utf-8', errors='replace').strip()
                return FetchResult(
                    url=url,
                    status_code=0,
                    content=None,
                    content_type=None,
                    etag=None,
                    last_modified=None,
                    fetched_at=datetime.utcnow(),
                    error=f"curl failed: {error_msg or 'unknown error'}",
                )

            # Parse response (headers + body)
            response_bytes = result.stdout

            # Split headers from body
            parts = response_bytes.split(b'\r\n\r\n', 1)
            if len(parts) != 2:
                # Try with just \n\n
                parts = response_bytes.split(b'\n\n', 1)

            if len(parts) != 2:
                return FetchResult(
                    url=url,
                    status_code=0,
                    content=None,
                    content_type=None,
                    etag=None,
                    last_modified=None,
                    fetched_at=datetime.utcnow(),
                    error="Failed to parse curl response",
                )

            headers_raw, body = parts

            # Parse status code from first line
            headers_text = headers_raw.decode('utf-8', errors='replace')
            first_line = headers_text.split('\n')[0]
            status_code = 0
            if 'HTTP/' in first_line:
                status_parts = first_line.split()
                if len(status_parts) >= 2:
                    try:
                        status_code = int(status_parts[1])
                    except ValueError:
                        pass

            # Parse headers
            content_type = None
            etag = None
            last_modified = None

            for line in headers_text.split('\n')[1:]:
                if ':' not in line:
                    continue
                key, value = line.split(':', 1)
                key_lower = key.strip().lower()
                value = value.strip()

                if key_lower == 'content-type':
                    content_type = value
                elif key_lower == 'etag':
                    etag = value
                elif key_lower == 'last-modified':
                    last_modified = value

            return FetchResult(
                url=url,
                status_code=status_code,
                content=body if status_code == 200 else None,
                content_type=content_type,
                etag=etag,
                last_modified=last_modified,
                fetched_at=datetime.utcnow(),
                error=None if status_code == 200 else f"HTTP {status_code}",
            )

        except subprocess.TimeoutExpired:
            return FetchResult(
                url=url,
                status_code=0,
                content=None,
                content_type=None,
                etag=None,
                last_modified=None,
                fetched_at=datetime.utcnow(),
                error="curl timeout",
            )
        except Exception as e:
            return FetchResult(
                url=url,
                status_code=0,
                content=None,
                content_type=None,
                etag=None,
                last_modified=None,
                fetched_at=datetime.utcnow(),
                error=f"curl error: {str(e)}",
            )

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
                # Check if this is a network error that might work with Windows curl
                if self.windows_curl_path and "Network is unreachable" in str(e):
                    print(f"   🔄 httpx failed with network error, trying Windows curl...", file=sys.stderr)
                    return self._fetch_with_windows_curl(url)

                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue

            except Exception as e:
                last_error = e
                break

        # All retries failed - try Windows curl as last resort if available
        if self.windows_curl_path and last_error:
            error_str = str(last_error)
            if "Network is unreachable" in error_str or "Connection" in error_str:
                print(f"   🔄 All httpx retries failed, trying Windows curl as fallback...", file=sys.stderr)
                return self._fetch_with_windows_curl(url)

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
