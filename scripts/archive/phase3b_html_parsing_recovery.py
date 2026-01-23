#!/usr/bin/env python3
"""
Phase 3b: HTML Content Parsing for Date Recovery

Fetches actual HTML from marxists.org and extracts dates from:
1. Document headers/preambles
2. Copyright/publication statements
3. Source references at bottom of pages
4. Metadata in HTML head or title tags
"""
import re
import sys
import uuid
import httpx
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, func

sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "ingest_service" / "src"))

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import (
    Work, Author, Edition, WorkDateDerived, WorkMetadataRun, WorkMetadataEvidence
)

# Date patterns to search in HTML content
DATE_PATTERNS = [
    # Year patterns
    r"\b(1[5-9]\d{2}|20[0-2]\d)\s",  # 1500-2029 followed by space
    r"\b(1[5-9]\d{2}|20[0-2]\d)[,\.\)]",  # year with punctuation

    # Month+Year patterns
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)[,\s]+(\d{4})",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+(\d{4})",

    # Written dates
    r"(?:Written|Published|First published|Delivered|Composed)\s+(?:in\s+)?(?:the\s+)?(?:year\s+)?(?:of\s+)?(\d{4})",
    r"(?:Written|Published|First published|Delivered|Complied)\s+(?:in\s+)?(?:the\s+)?(?:spring|summer|autumn|winter)\s+of\s+(\d{4})",
    r"(?:Written|Published|First published|Delivered)\s+(?:in|during)\s+(\d{4})",

    # Source citations
    r"Source:\s*[^<\n]{1,200}?(\d{4})",  # Source: ... with year
    r"Originally\s+published\s+in\s+[^<\n]{1,100}?(\d{4})",
    r"From\s+[^<\n]{1,100}?(\d{4})",

    # Copyright statements
    r"Copyright\s+(?:©|\(c\))\s*(\d{4})",
    r"©\s*(\d{4})",

    # German date formats
    r"\bgeschrieben\s+(\d{4})",
    r"\bveröffentlicht\s+(\d{4})",
    r"\b(\d{4})\s*(?:geschrieben|veröffentlicht)",

    # French date formats
    r"\bécrit\s+(?:en\s+)?(\d{4})",
    r"\bpublié\s+(?:en\s+)?(\d{4})",
    r"\b(\d{4})\s*(?:écrit|publié)",
]


def fetch_and_parse_date(url: str) -> dict[str, Any] | None:
    """Fetch HTML and extract publication date."""
    if not url or not url.startswith("http"):
        return None

    try:
        response = httpx.get(url, timeout=15, follow_redirects=True)
        if response.status_code != 200:
            return None

        html = response.text
        results = []

        # Search for date patterns
        for pattern in DATE_PATTERNS:
            matches = re.finditer(pattern, html, re.IGNORECASE)
            for match in matches:
                year_str = match.group(1) if match.lastindex and match.group(1) else match.group(0)
                # Extract just the year from the matched text
                year_match = re.search(r"\b(1[5-9]\d{2}|20[0-2]\d)\b", year_str)
                if year_match:
                    year = int(year_match.group(1))
                    if 1500 <= year <= 2029:
                        # Get context around match
                        start = max(0, match.start() - 50)
                        end = min(len(html), match.end() + 50)
                        context = html[start:end].replace("\n", " ").strip()

                        results.append({
                            "year": year,
                            "context": context[:200],
                            "pattern": pattern[:30] + "..." if len(pattern) > 30 else pattern
                        })

        if not results:
            return None

        # Heuristic: most frequent year is likely correct
        year_counts = {}
        for r in results:
            year = r["year"]
            year_counts[year] = year_counts.get(year, 0) + 1

        # Get most common year
        best_year = max(year_counts, key=year_counts.get)
        confidence = min(0.9, 0.4 + (year_counts[best_year] * 0.1))

        # Get best context
        best_context = next((r["context"] for r in results if r["year"] == best_year), "")

        return {
            "year": best_year,
            "month": None,
            "day": None,
            "precision": "year",
            "confidence": confidence,
            "context": best_context,
            "all_years_found": year_counts
        }

    except Exception as e:
        print(f"    Error fetching {url[:50]}...: {e}")
        return None


def run_phase3b():
    """Run Phase 3b: HTML content parsing for date recovery."""
    print("="*80)
    print("PHASE 3B: HTML CONTENT PARSING FOR DATE RECOVERY")
    print("="*80)

    with SessionLocal() as session:
        run_id = uuid.uuid4()

        # Create run record
        run = WorkMetadataRun(
            run_id=run_id,
            pipeline_version="metadata_completion_v1",
            strategy="phase3b_html_parsing",
            params={},
            sources=["marxists_html_content"],
            started_at=datetime.now(timezone.utc),
            status="started",
        )
        session.add(run)
        session.commit()

        # Get works with NO external evidence (highest priority)
        unknown_works = session.execute(
            select(
                Work.work_id,
                Work.title,
                Author.name_canonical,
                func.array_agg(Edition.source_url.distinct()).label("urls"),
                func.count(WorkMetadataEvidence.evidence_id).label("evidence_count")
            )
            .select_from(Work)
            .join(Author)
            .join(Edition, Edition.work_id == Work.work_id)
            .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
            .outerjoin(WorkMetadataEvidence, WorkMetadataEvidence.work_id == Work.work_id)
            .where(WorkDateDerived.display_date_field == "unknown")
            .group_by(Work.work_id, Work.title, Author.name_canonical)
            .order_by(Author.name_canonical, Work.title)
        ).all()

        works_to_fetch = [
            {
                "work_id": str(w.work_id),
                "title": w.title,
                "author": w.name_canonical,
                "url": w.urls[0] if w.urls else None,
            }
            for w in unknown_works
        ]

        print(f"\nFound {len(works_to_fetch)} works still marked as unknown")
        print("\nFetching and parsing HTML...")

        client = httpx.Client(timeout=30)
        results = {"success": [], "failed": [], "total": len(works_to_fetch)}

        for i, work in enumerate(works_to_fetch, 1):
            url = work.get("url")
            if not url:
                results["failed"].append({**work, "error": "no URL"})
                continue

            date_info = fetch_and_parse_date(url)

            if date_info and date_info["confidence"] >= 0.5:
                # Store evidence
                evidence = WorkMetadataEvidence(
                    evidence_id=uuid.uuid4(),
                    run_id=run_id,
                    work_id=work["work_id"],
                    source_name="html_content_parsing",
                    source_locator=url,
                    retrieved_at=datetime.now(timezone.utc),
                    extracted={
                        "year": date_info["year"],
                        "month": date_info.get("month"),
                        "day": date_info.get("day"),
                        "precision": date_info["precision"],
                    },
                    score=date_info["confidence"],
                    raw_payload={
                        "context": date_info.get("context", ""),
                        "all_years_found": date_info.get("all_years_found", {}),
                    },
                    notes="Extracted from HTML content"
                )
                session.add(evidence)
                results["success"].append({**work, "date": date_info})
                print(f"  [{i}/{len(works_to_fetch)}] {work['author']}: {work['title'][:40]}... → {date_info['year']}")
            else:
                results["failed"].append({**work, "error": "no date found"})

            # Commit every 10 works
            if i % 10 == 0:
                session.commit()
                print(f"  Progress: {i}/{len(works_to_fetch)} | Success: {len(results['success'])}")

        session.commit()

        # Update run record
        run.works_scanned = len(works_to_fetch)
        run.works_updated = len(results["success"])
        run.works_failed = len(results["failed"])
        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
        session.commit()

    print(f"\n{'='*80}")
    print("PHASE 3B COMPLETE")
    print(f"{'='*80}")
    print(f"Total scanned: {results['total']}")
    print(f"Successful: {len(results['success'])}")
    print(f"Failed: {len(results['failed'])}")

    if results["success"]:
        print(f"\nRecovered works:")
        for r in results["success"][:10]:
            print(f"  - {r['author']}: {r['title'][:50]} → {r['date']['year']}")

    return results


if __name__ == "__main__":
    run_phase3b()
