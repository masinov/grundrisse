from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from grundrisse_core.hashing import sha256_hex
from ingest_service.settings import settings


@dataclass(frozen=True)
class Snapshot:
    url: str
    fetched_at: datetime
    content_type: str | None
    content: bytes
    sha256: str
    raw_path: Path
    meta_path: Path


def snapshot_url(url: str) -> Snapshot:
    """
    Day-1 contract:
    - Fetch raw bytes from `url` and compute checksum.
    - Persist raw snapshot (object storage path or local spool) and record `IngestRun`.

    Networking/persistence are intentionally not implemented in the scaffold.
    """
    raw_dir = settings.data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": settings.user_agent}
    with httpx.Client(timeout=settings.request_timeout_s, headers=headers, follow_redirects=True) as client:
        resp = client.get(url)
    resp.raise_for_status()

    content = resp.content
    if len(content) > settings.max_bytes:
        raise RuntimeError(f"Refusing to store {len(content)} bytes (max_bytes={settings.max_bytes})")

    digest = sha256_hex(content)
    raw_path = raw_dir / f"{digest}.html"
    meta_path = raw_dir / f"{digest}.json"

    if not raw_path.exists():
        raw_path.write_bytes(content)
    if not meta_path.exists():
        meta_path.write_text(
            (
                "{\n"
                f'  "url": {url!r},\n'
                f'  "fetched_at": {datetime.utcnow().isoformat()!r},\n'
                f'  "status_code": {resp.status_code},\n'
                f'  "content_type": {resp.headers.get("content-type")!r},\n'
                f'  "sha256": {digest!r}\n'
                "}\n"
            ),
            encoding="utf-8",
        )

    return Snapshot(
        url=url,
        fetched_at=datetime.utcnow(),
        content_type=resp.headers.get("content-type"),
        content=content,
        sha256=digest,
        raw_path=raw_path,
        meta_path=meta_path,
    )
