from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ingest_service.settings import settings


@dataclass(frozen=True)
class DiscoverResult:
    root_url: str
    base_prefix: str
    urls: list[str]


def discover_work_urls(root_url: str, *, max_pages: int | None = None) -> DiscoverResult:
    """
    Discover a bounded set of pages that belong to the same "work directory" as root_url.

    Heuristic (Day-1):
    - same scheme+netloc as root_url
    - path starts with the directory prefix of root_url (e.g. .../communist-manifesto/)
    - recursive crawl within that directory (bounded)
    """
    max_pages = max_pages or settings.crawl_max_pages

    root = _normalize_url(root_url)
    parsed_root = urlparse(root)
    base_dir_path = parsed_root.path.rsplit("/", 1)[0] + "/"
    base_prefix = f"{parsed_root.scheme}://{parsed_root.netloc}{base_dir_path}"

    seen: set[str] = set()
    queue: list[str] = [root]

    while queue and len(seen) < max_pages:
        current = queue.pop(0)
        if current in seen:
            continue
        if not _is_in_scope(current, base_prefix=base_prefix, parsed_root=parsed_root):
            continue
        if not _is_html_page(current):
            continue

        seen.add(current)
        html = _fetch_text(current)
        for link in _extract_links(html, base=current):
            if link in seen:
                continue
            if not _is_in_scope(link, base_prefix=base_prefix, parsed_root=parsed_root):
                continue
            if not _is_html_page(link):
                continue
            queue.append(link)

        # Keep crawl deterministic and bounded.
        if len(queue) > max_pages:
            queue = queue[:max_pages]

    urls = _sort_urls(list(seen))

    return DiscoverResult(root_url=root, base_prefix=base_prefix, urls=urls)


def _fetch_text(url: str) -> str:
    headers = {"User-Agent": settings.user_agent}
    with httpx.Client(timeout=settings.request_timeout_s, headers=headers, follow_redirects=True) as client:
        resp = client.get(url)
    resp.raise_for_status()
    time.sleep(settings.crawl_delay_s)
    return resp.text


def _extract_links(html: str, *, base: str) -> Iterable[str]:
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        absolute = urljoin(base, href)
        yield _normalize_url(absolute)


def _normalize_url(url: str) -> str:
    url, _frag = urldefrag(url)
    # URLs must not contain whitespace. Users may paste line-wrapped URLs that
    # include newlines/spaces; strip them to keep discovery robust.
    url = "".join(url.split())
    return url.strip()


def _is_in_scope(url: str, *, base_prefix: str, parsed_root) -> bool:
    pu = urlparse(url)
    if pu.scheme != parsed_root.scheme or pu.netloc != parsed_root.netloc:
        return False
    return url.startswith(base_prefix)


def _is_html_page(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".htm") or path.endswith(".html")


def _sort_urls(urls: list[str]) -> list[str]:
    """
    Deterministic ordering that tends to be more "work-like":
    - index first when present
    - preface next
    - then chapter-like numeric pages (ch01.htm, ch1.htm)
    - then lexical
    """
    import re

    chapter_re = re.compile(r"/ch(\d+)\.htm(?:l)?$", re.IGNORECASE)

    def key(u: str) -> tuple:
        p = urlparse(u).path.lower()
        if p.endswith("/index.htm") or p.endswith("/index.html"):
            return (0, 0, u)
        if p.endswith("/preface.htm") or p.endswith("/preface.html"):
            return (1, 0, u)
        m = chapter_re.search(p)
        if m:
            return (2, int(m.group(1)), u)
        return (9, 0, u)

    return sorted(set(urls), key=key)
