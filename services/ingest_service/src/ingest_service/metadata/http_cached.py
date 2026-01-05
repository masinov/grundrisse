from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class CachedResponse:
    url: str
    status_code: int
    headers: dict[str, str]
    text: str | None
    content: bytes | None
    from_cache: bool


class CachedHttpClient:
    """
    Simple disk-cache + crawl-delay HTTP client.

    Designed for metadata lookups (Wikidata/OpenLibrary/HTML pages) where we want:
    - deterministic replays during debugging
    - bounded politeness (sleep between requests)
    - no dependency on crawler URL catalog tables
    """

    def __init__(
        self,
        *,
        cache_dir: Path,
        user_agent: str,
        timeout_s: float = 30.0,
        delay_s: float = 0.5,
        max_cache_age_s: float | None = 7 * 24 * 3600,
        max_retries: int = 3,
    ) -> None:
        self.cache_dir = cache_dir
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.delay_s = delay_s
        self.max_cache_age_s = max_cache_age_s
        self.max_retries = max_retries
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=timeout_s, read=timeout_s, write=timeout_s),
            headers={"User-Agent": user_agent},
            follow_redirects=True,
        )
        self._last_request_at: float | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CachedHttpClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str | None = None,
        as_bytes: bool = False,
    ) -> CachedResponse:
        cache_key = _cache_key(url, params=params, accept=accept, as_bytes=as_bytes)
        meta_path, body_path = _cache_paths(self.cache_dir, cache_key, as_bytes=as_bytes)
        cached = _try_read_cache(meta_path, body_path, max_age_s=self.max_cache_age_s)
        if cached is not None:
            return CachedResponse(
                url=cached["url"],
                status_code=cached["status_code"],
                headers=cached.get("headers") or {},
                text=None if as_bytes else cached.get("text"),
                content=None if not as_bytes else body_path.read_bytes(),
                from_cache=True,
            )

        self._polite_delay()
        headers: dict[str, str] = {}
        if accept:
            headers["Accept"] = accept
        resp: httpx.Response | None = None
        last_exc: Exception | None = None
        for attempt in range(1, max(1, self.max_retries) + 1):
            try:
                resp = self._client.get(url, params=params, headers=headers)
                last_exc = None
                break
            except httpx.RequestError as exc:
                last_exc = exc
                # basic exponential backoff
                time.sleep(0.8 * attempt)
                continue
        if resp is None:
            raise last_exc or httpx.RequestError("Request failed", request=None)
        # store
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        meta_path.parent.mkdir(parents=True, exist_ok=True)

        meta: dict[str, Any] = {
            "url": str(resp.request.url),
            "status_code": resp.status_code,
            "headers": {k.lower(): v for k, v in resp.headers.items()},
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "as_bytes": as_bytes,
        }
        if as_bytes:
            body_path.write_bytes(resp.content)
        else:
            meta["text"] = resp.text
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return CachedResponse(
            url=str(resp.request.url),
            status_code=resp.status_code,
            headers={k.lower(): v for k, v in resp.headers.items()},
            text=None if as_bytes else resp.text,
            content=None if not as_bytes else resp.content,
            from_cache=False,
        )

    def _polite_delay(self) -> None:
        if self.delay_s <= 0:
            return
        now = time.time()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            remaining = self.delay_s - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.time()


def _cache_key(url: str, *, params: dict[str, Any] | None, accept: str | None, as_bytes: bool) -> str:
    payload = {
        "url": url,
        "params": params or {},
        "accept": accept or "",
        "as_bytes": as_bytes,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return sha256(raw).hexdigest()


def _cache_paths(cache_dir: Path, key: str, *, as_bytes: bool) -> tuple[Path, Path]:
    # keep directory fanout shallow for large caches
    prefix = key[:2]
    meta_path = cache_dir / prefix / f"{key}.json"
    body_ext = "bin" if as_bytes else "txt"
    body_path = cache_dir / prefix / f"{key}.{body_ext}"
    return meta_path, body_path


def _try_read_cache(meta_path: Path, body_path: Path, *, max_age_s: float | None) -> dict[str, Any] | None:
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    fetched_at = meta.get("fetched_at")
    if max_age_s is not None and isinstance(fetched_at, str):
        try:
            dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - dt).total_seconds()
            if age > max_age_s:
                return None
        except Exception:
            pass

    if meta.get("as_bytes"):
        if not body_path.exists():
            return None
    return meta
