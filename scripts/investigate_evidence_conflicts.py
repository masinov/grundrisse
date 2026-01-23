#!/usr/bin/env python3
"""Investigate evidence conflicts for works with evidence but still unknown."""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "ingest_service" / "src"))

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import (
    Work, Author, WorkDateDerived, WorkMetadataEvidence
)
from sqlalchemy import select

with SessionLocal() as session:
    # Get works with evidence but still unknown
    works_with_evidence = session.execute(
        select(Work.work_id, Work.title, Author.name_canonical)
        .select_from(Work)
        .join(Author)
        .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
        .join(WorkMetadataEvidence, WorkMetadataEvidence.work_id == Work.work_id)
        .where(WorkDateDerived.display_date_field == "unknown")
        .distinct()
        .order_by(Author.name_canonical, Work.title)
    ).all()

    print("="*80)
    print(f"WORKS WITH EVIDENCE BUT STILL UNKNOWN: {len(works_with_evidence)}")
    print("="*80)

    for work_id, title, author in works_with_evidence:
        print(f"\n{author}: {title}")
        print("-" * 60)

        evidences = session.execute(
            select(WorkMetadataEvidence)
            .where(WorkMetadataEvidence.work_id == work_id)
            .order_by(WorkMetadataEvidence.score.desc())
        ).all()

        # Group by extracted year
        years = {}
        for (ev,) in evidences:
            extracted = ev.extracted
            if isinstance(extracted, dict):
                year = extracted.get("year")
                if year:
                    if year not in years:
                        years[year] = []
                    years[year].append({
                        "source": ev.source_name,
                        "score": ev.score,
                        "extracted": extracted,
                    })

        if years:
            print(f"  Found {len(evidences)} evidence rows with {len(years)} different years:")
            for year, items in sorted(years.items()):
                print(f"\n  Year {year}: {len(items)} source(s)")
                for item in items:
                    print(f"    - {item['source']} (score: {item['score']})")
                    if item['extracted'].get('month'):
                        print(f"      {item['extracted']['year']}-{item['extracted']['month']:02d}")
        else:
            print(f"  No year data found in {len(evidences)} evidence rows")
            for (ev,) in evidences[:3]:
                print(f"    - {ev.source_name}: {ev.extracted}")
