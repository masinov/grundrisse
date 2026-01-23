#!/usr/bin/env python3
"""Analyze remaining unknown works for Phase 3 targeting."""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "ingest_service" / "src"))

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import Work, Author, Edition, WorkDateDerived, WorkMetadataEvidence
from sqlalchemy import select, func

with SessionLocal() as session:
    # Get remaining unknown works
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

    print("="*80)
    print(f"REMAINING UNKNOWN WORKS: {len(unknown_works)}")
    print("="*80)

    # Analyze by evidence count
    evidence_dist = Counter()
    for _, _, _, _, evidence_count in unknown_works:
        if evidence_count == 0:
            evidence_dist["no_external_evidence"] += 1
        elif evidence_count <= 2:
            evidence_dist["low_evidence"] += 1
        else:
            evidence_dist["some_evidence"] += 1

    print("\nBy evidence count:")
    for k, v in evidence_dist.most_common():
        print(f"  {k}: {v}")

    # Analyze by author
    author_dist = Counter()
    for _, author, _, _, _ in unknown_works:
        author_dist[author] += 1

    print(f"\nTop authors with unknowns:")
    for author, count in author_dist.most_common(15):
        print(f"  {author}: {count}")

    # Sample some works for investigation
    print(f"\nSample works (first 20):")
    for work_id, title, author, urls, evidence_count in unknown_works[:20]:
        url_snip = urls[0][-60:] if urls and urls[0] else "no URL"
        print(f"  - {author}: {title[:50]}")
        print(f"    URL: ...{url_snip}")
        print(f"    Evidence: {evidence_count} rows")
