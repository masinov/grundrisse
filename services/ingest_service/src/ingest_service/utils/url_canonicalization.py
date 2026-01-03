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
        ".mp3", ".mp4", ".avi", ".mov", ".wav",
        ".epub", ".mobi", ".azw3", ".prc",  # Ebook formats
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


def is_likely_content_url(url: str) -> bool:
    """
    Filter out navigation/index URLs to focus on actual content.

    This helps reduce the crawl scope by skipping:
    - Subject indexes
    - Alphabetical listings
    - Navigation pages
    - Language selection pages

    Args:
        url: URL to check

    Returns:
        True for URLs likely to contain primary work content
        False for navigation, indexes, and apparatus
    """
    url_lower = url.lower()
    parsed = urlparse(url)
    path = parsed.path.lower()

    # Estimate depth from URL path
    depth_estimate = path.rstrip('/').count('/')

    # FIRST: Check skip patterns (these override everything)
    skip_patterns = [
        "/subject/",           # Subject indexes
        "/history/",           # Historical indexes (unless in archive/author/history path)
        "/glossary/",          # Glossaries
        "/reference/subject",  # Reference materials
        "/admin/",             # Admin pages
        "/search",             # Search pages
        "/browse",             # Browse pages
        "subject-index",       # Subject index pages
        "writer-index",        # Writer index pages
        "title-index",         # Title index pages
        "/images/",            # Image directories
        "/css/",               # Stylesheets
        "/scripts/",           # JavaScript
        "/ebooks/",            # Ebook download directories (epub, mobi, pdf files)
        "/ebook/",             # Alternate ebook directory name
        "/audiobooks/",        # Audiobook directories
        "/audiobook/",         # Alternate audiobook directory name
        "/downloads/",         # Download directories
        "/download/",          # Download directories
        "/works/download/",    # Works download subdirectories
        "/works/pdf/",         # PDF download directories
        "/guide/",             # Study guides and reading guides (secondary)
        "/guides/",            # Alternate guides directory
        "/structure/",         # Structural analysis (secondary)
        "/visitors/",          # Visitor statistics and analytics
        "/reviews-",           # Reviews of works (secondary)
        "/review-",            # Review pages (secondary)
        "/bio/",               # Biographies (secondary - not primary texts)
        "/photo/",             # Photo galleries
        "/photos/",            # Photo directories
        "txtindex.htm",        # Text indexes
        "index-l.htm",         # Letter indexes
        "/works/date/",        # Date-based navigation (duplicates chronological access)
        "/works/subject/",     # Subject-based navigation (duplicates topical access)
        # Non-English language sections (COMPREHENSIVE list - tested and verified)
        # Romance languages
        "/espanol/",           # Spanish
        "/portugues/",         # Portuguese
        "/francais/",          # French
        "/catala/",            # Catalan
        "/italiano/",          # Italian
        # Germanic languages
        "/deutsch/",           # German
        "/nederlands/",        # Dutch
        "/svenska/",           # Swedish
        # Slavic languages
        "/russkij/",           # Russian
        "/russian/",           # Russian (alternate)
        "/polski/",            # Polish
        "/czech/",             # Czech
        # Asian languages
        "/chinese/",           # Chinese
        "/korean/",            # Korean
        "/japanese/",          # Japanese (if exists)
        "/indonesia/",         # Indonesian
        "/tagalog/",           # Tagalog (Filipino)
        "/filipino/",          # Filipino (alternate)
        "/thai/",              # Thai
        "/vietnamese/",        # Vietnamese
        "/hindi/",             # Hindi
        "/urdu/",              # Urdu
        "/tamil/",             # Tamil
        "/bahasa/",            # Bahasa (if exists)
        # Middle Eastern languages
        "/farsi/",             # Farsi (Persian)
        "/persian/",           # Persian (alternate)
        "/arabic/",            # Arabic
        "/hebrew/",            # Hebrew
        "/turkce/",            # Turkish
        "/turkish/",           # Turkish (alternate)
        # Other languages
        "/greek/",             # Greek
        "/esperanto/",         # Esperanto
        "/hungarian/",         # Hungarian (if exists)
        "/finnish/",           # Finnish (if exists)
        # Multilingual navigation
        "/xlang/",             # Cross-language index
    ]

    # Skip if URL contains skip patterns
    for pattern in skip_patterns:
        if pattern in path:
            return False

    # Skip URLs with query parameters (usually navigation/search)
    if "?" in url:
        return False

    # SECOND: Check content indicators (high priority)
    content_indicators = [
        "/archive/",          # Archive content (main content area)
        "/works/",            # Actual works
        "/collected-works/",  # Collected works
        "/letters/",          # Letters
        "/articles/",         # Articles
    ]

    # If it has content indicators, it's probably good
    for indicator in content_indicators:
        if indicator in path:
            return True

    # THIRD: Allow root and very shallow URLs (needed to bootstrap crawl)
    if depth_estimate <= 1:
        return True

    # Allow directory index pages at moderate depth (depth 2-4)
    # These are needed to navigate to content
    if path.endswith('/') or 'index.htm' in path:
        if 2 <= depth_estimate <= 4:
            return True

    # If it ends with .htm/.html and doesn't have skip patterns, allow it
    if url_lower.endswith((".htm", ".html")):
        return True

    # Default: allow if depth is reasonable (let other filters handle the rest)
    return depth_estimate <= 4
