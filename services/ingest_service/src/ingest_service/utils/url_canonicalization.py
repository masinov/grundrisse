"""URL canonicalization utilities for crawler."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def canonicalize_url(url: str, *, preserve_query: bool = False) -> str:
    """
    Canonicalize a URL by:
    - removing fragments (#...)
    - removing whitespace/newlines
    - normalizing scheme/host
    - optionally removing query string (unless it creates a new Edition version)

    Args:
        url: The URL to canonicalize
        preserve_query: If True, keep query strings (for Edition versioning)

    Returns:
        Canonicalized URL string
    """
    # Remove whitespace/newlines (users may paste wrapped URLs)
    url = "".join(url.split())

    # Parse URL
    parsed = urlparse(url)

    # Normalize components
    scheme = parsed.scheme.lower() if parsed.scheme else "https"
    netloc = parsed.netloc.lower()
    path = parsed.path
    params = parsed.params
    query = parsed.query if preserve_query else ""
    fragment = ""  # Always remove fragments

    # Reconstruct canonical URL
    canonical = urlunparse((scheme, netloc, path, params, query, fragment))

    return canonical


def is_same_directory(url1: str, url2: str) -> bool:
    """
    Check if two URLs are in the same directory.
    Used for work directory detection.

    Args:
        url1: First URL
        url2: Second URL

    Returns:
        True if both URLs share the same directory prefix
    """
    parsed1 = urlparse(url1)
    parsed2 = urlparse(url2)

    # Different hosts = different directories
    if parsed1.netloc != parsed2.netloc:
        return False

    # Get directory paths (remove filename)
    dir1 = "/".join(parsed1.path.rstrip("/").split("/")[:-1])
    dir2 = "/".join(parsed2.path.rstrip("/").split("/")[:-1])

    return dir1 == dir2


def get_directory_prefix(url: str) -> str:
    """
    Extract the directory prefix from a URL.

    Args:
        url: URL to extract directory from

    Returns:
        Directory prefix (without filename)
    """
    parsed = urlparse(url)
    path_parts = parsed.path.rstrip("/").split("/")[:-1]
    directory = "/".join(path_parts)

    return urlunparse((parsed.scheme, parsed.netloc, directory, "", "", ""))


def is_html_url(url: str) -> bool:
    """
    Check if URL likely points to an HTML page.

    Args:
        url: URL to check

    Returns:
        True if URL appears to be HTML
    """
    url_lower = url.lower()

    # Check for explicit HTML extensions
    if url_lower.endswith((".htm", ".html")):
        return True

    # Check for index pages (often no extension)
    if url_lower.endswith(("/", "/index")):
        return True

    # Exclude obvious non-HTML resources
    non_html_extensions = (
        ".pdf", ".txt", ".jpg", ".jpeg", ".png", ".gif", ".svg",
        ".css", ".js", ".json", ".xml", ".zip", ".tar", ".gz",
        ".mp3", ".mp4", ".avi", ".mov", ".wav"
    )
    if any(url_lower.endswith(ext) for ext in non_html_extensions):
        return False

    return True


def is_marxists_org_url(url: str) -> bool:
    """
    Check if URL is from marxists.org domain.

    Args:
        url: URL to check

    Returns:
        True if URL is from marxists.org
    """
    parsed = urlparse(url)
    netloc_lower = parsed.netloc.lower()

    return netloc_lower in ("www.marxists.org", "marxists.org")
