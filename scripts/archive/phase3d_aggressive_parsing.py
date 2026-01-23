#!/usr/bin/env python3
"""
Phase 3d: Aggressive HTML Date Extraction

Final attempt to extract dates from remaining unknown works using
more aggressive patterns and heuristics.
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

# More aggressive date patterns
AGGRESSIVE_PATTERNS = [
    # Any 4-digit year in reasonable range (more permissive)
    r"\b(17[0-9]{2}|18[0-9]{2}|19[0-9]{2}|200[0-9]|201[0-9]|202[0-4])\b",

    # Years with common prepositions
    r"\b(?:in|of|from|during|since|circa|ca\.|c\.|about)\s+(?:the\s+)?(?:year\s+)?(17[0-9]{2}|18[0-9]{2}|19[0-9]{2}|200[0-9]|201[0-9]|202[0-4])",

    # Date ranges
    r"\b(17[0-9]{2}|18[0-9]{2}|19[0-9]{2}|200[0-9]|201[0-9]|202[0-4])\s*[-–—to]\s*(?:19|20)?\d{2}",

    # Copyright/publication indicators
    r"\b(?:first|original|earliest)\s+(?:published|printed|issued)\s+(?:in\s+)?(?:the\s+)?(?:year\s+)?(17[0-9]{2}|18[0-9]{2}|19[0-9]{2}|200[0-9]|201[0-9]|202[0-4])",

    # Written/composed indicators
    r"\b(?:written|composed|drafted|authored)\s+(?:in|during|about)\s+(17[0-9]{2}|18[0-9]{2}|19[0-9]{2}|200[0-9]|201[0-9]|202[0-4])",
]


def fetch_and_parse_date_aggressive(url: str) -> dict[str, Any] | None:
    """Fetch HTML and extract date using aggressive patterns."""
    if not url or not url.startswith("http"):
        return None

    try:
        response = httpx.get(url, timeout=15, follow_redirects=True)
        if response.status_code != 200:
            return None

        html = response.text
        years_found = []

        # Search for all year patterns
        for pattern in AGGRESSIVE_PATTERNS:
            matches = re.finditer(pattern, html, re.IGNORECASE)
            for match in matches:
                # Extract the year
                year_match = re.search(r"\b(17[0-9]{2}|18[0-9]{2}|19[0-9]{2}|200[0-9]|201[0-9]|202[0-4])\b", match.group(0))
                if year_match:
                    year = int(year_match.group(1))
                    # Get context
                    start = max(0, match.start() - 80)
                    end = min(len(html), match.end() + 30)
                    context = html[start:end].replace("\n", " ").strip()
                    # Clean up context
                    context = re.sub(r"\s+", " ", context)
                    years_found.append({
                        "year": year,
                        "context": context[:150],
                    })

        if not years_found:
            return None

        # Count year occurrences
        year_counts = {}
        year_contexts = {}
        for y in years_found:
            year = y["year"]
            year_counts[year] = year_counts.get(year, 0) + 1
            if year not in year_contexts:
                year_contexts[year] = []

            # Only keep unique contexts
            ctx = y["context"]
            if ctx not in year_contexts[year]:
                year_contexts[year].append(ctx)

        # Heuristic: prefer years that appear multiple times OR are in meaningful context
        # Filter out obvious "noise" years like 2024, 2023 (likely website footer dates)
        for year in list(year_counts.keys()):
            if year >= 2015:  # Likely website dates, not work dates
                year_counts[year] = max(0, year_counts[year] - 10)  # Penalize heavily

        if not year_counts:
            return None

        best_year = max(year_counts, key=year_counts.get)
        if year_counts[best_year] <= 0:
            return None

        # Calculate confidence based on count and recency penalty
        base_confidence = min(0.6, 0.3 + (year_counts[best_year] * 0.05))
        if best_year >= 2000:
            base_confidence -= 0.2  # Lower confidence for very recent works
        if best_year < 1800:
            base_confidence += 0.1  # Higher confidence for classical works

        confidence = max(0.3, min(0.7, base_confidence))

        return {
            "year": best_year,
            "month": None,
            "day": None,
            "precision": "year",
            "confidence": confidence,
            "context": year_contexts[best_year][0] if year_contexts.get(best_year) else "",
            "all_years": sorted(set(y["year"] for y in years_found))
        }

    except Exception as e:
        return None


def run_phase3d():
    """Run Phase 3d: Aggressive HTML parsing."""
    print("="*80)
    print("PHASE 3D: AGGRESSIVE HTML DATE EXTRACTION")
    print("="*80)

    with SessionLocal() as session:
        run_id = uuid.uuid4()

        # Create run record
        run = WorkMetadataRun(
            run_id=run_id,
            pipeline_version="metadata_completion_v1",
            strategy="phase3d_aggressive_parsing",
            params={},
            sources=["html_content_aggressive"],
            started_at=datetime.now(timezone.utc),
            status="started",
        )
        session.add(run)
        session.commit()

        # Get remaining unknown works
        unknown_works = session.execute(
            select(
                Work.work_id,
                Work.title,
                Author.name_canonical,
                func.array_agg(Edition.source_url.distinct()).label("urls")
            )
            .select_from(Work)
            .join(Author)
            .join(Edition, Edition.work_id == Work.work_id)
            .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
            .where(WorkDateDerived.display_date_field == "unknown")
            .group_by(Work.work_id, Work.title, Author.name_canonical)
            .order_by(Author.name_canonical, Work.title)
        ).all()

        print(f"\nFound {len(unknown_works)} works still marked as unknown")
        print("\nFetching and parsing HTML...")

        results = {"success": [], "failed": [], "total": len(unknown_works)}

        for work_id, title, author, urls in unknown_works:
            url = urls[0] if urls else None
            if not url:
                results["failed"].append({"work_id": work_id, "title": title, "error": "no URL"})
                continue

            date_info = fetch_and_parse_date_aggressive(url)

            if date_info and date_info["confidence"] >= 0.35:
                evidence = WorkMetadataEvidence(
                    evidence_id=uuid.uuid4(),
                    run_id=run_id,
                    work_id=work_id,
                    source_name="html_content_aggressive",
                    source_locator=url,
                    retrieved_at=datetime.now(timezone.utc),
                    extracted={
                        "year": date_info["year"],
                        "month": None,
                        "day": None,
                        "precision": "year",
                    },
                    score=date_info["confidence"],
                    raw_payload={
                        "context": date_info.get("context", ""),
                        "all_years": date_info.get("all_years", []),
                    },
                    notes="Aggressive HTML content parsing"
                )
                session.add(evidence)
                results["success"].append({
                    "work_id": work_id,
                    "title": title,
                    "author": author,
                    "date": date_info
                })
                print(f"  + {author}: {title[:40]}... → {date_info['year']} (conf: {date_info['confidence']:.2f})")
            else:
                results["failed"].append({"work_id": work_id, "title": title, "error": "no date found"})

            # Commit every 10 works
            if len(results["success"]) + len(results["failed"]) % 10 == 0:
                session.commit()

        session.commit()

        # Update run record
        run.works_scanned = len(unknown_works)
        run.works_updated = len(results["success"])
        run.works_failed = len(results["failed"])
        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
        session.commit()

    print(f"\n{'='*80}")
    print("PHASE 3D COMPLETE")
    print(f"{'='*80}")
    print(f"Total scanned: {results['total']}")
    print(f"Successful: {len(results['success'])}")
    print(f"Failed: {len(results['failed'])}")

    return results


if __name__ == "__main__":
    run_phase3d()
