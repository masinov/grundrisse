#!/usr/bin/env python3
"""Analyze the final remaining unknown works."""
import sys
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

    # Show all works
    print(f"\nAll remaining unknown works:")
    for work_id, title, author, urls, evidence_count in unknown_works:
        url = urls[0] if urls else "NO URL"
        print(f"  - {author}: {title[:60]}")
        print(f"    URL: {url[-80:]}")
        print(f"    Evidence rows: {evidence_count}")
        print()

    # Show evidence details for those with evidence
    print("="*80)
    print("EVIDENCE DETAILS FOR WORKS WITH EVIDENCE")
    print("="*80)

    for work_id, title, author, urls, evidence_count in unknown_works:
        if evidence_count > 0:
            print(f"\n{author}: {title}")
            evidences = session.execute(
                select(WorkMetadataEvidence)
                .where(WorkMetadataEvidence.work_id == work_id)
                .order_by(WorkMetadataEvidence.score.desc())
            ).all()
            for (ev,) in evidences:
                print(f"  - {ev.source_name}: {ev.extracted} (score: {ev.score})")
                if ev.raw_payload:
                    print(f"    Payload: {ev.raw_payload}")
