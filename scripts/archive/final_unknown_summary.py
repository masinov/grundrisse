#!/usr/bin/env python3
"""Summarize the final remaining unknown works."""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "ingest_service" / "src"))

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import (
    Work, Author, Edition, WorkDateDerived, WorkMetadataEvidence
)
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
    print(f"FINAL REMAINING UNKNOWN WORKS: {len(unknown_works)}")
    print("="*80)

    # Analyze by evidence count
    with_evidence = sum(1 for _, _, _, _, ec in unknown_works if ec > 0)
    without_evidence = len(unknown_works) - with_evidence

    print(f"\nWith evidence but still unknown: {with_evidence}")
    print(f"Without evidence: {without_evidence}")

    # Analyze by author
    author_dist = Counter()
    for _, author, _, _, _ in unknown_works:
        author_dist[author] += 1

    print(f"\nBy author:")
    for author, count in author_dist.most_common(20):
        print(f"  {author}: {count}")

    # Show just the works with evidence (these are interesting cases)
    print(f"\nWorks with evidence but still marked unknown ({with_evidence}):")
    for work_id, title, author, urls, evidence_count in unknown_works:
        if evidence_count > 0:
            print(f"  - {author}: {title[:50]}... ({evidence_count} evidence rows)")

    # Sample some without-evidence works for manual review
    print(f"\nSample works without evidence ({without_evidence} total):")
    without_list = [(w, t, a, u) for w, t, a, u, ec in unknown_works if ec == 0]
    for work_id, title, author, urls in without_list[:20]:
        url = urls[0] if urls else "NO URL"
        print(f"  - {author}: {title[:50]}")
        print(f"    {url}")
