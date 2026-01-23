#!/usr/bin/env python3
"""Simple date quality check."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "ingest_service" / "src"))

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import (
    Work, Author, WorkDateDerived, WorkMetadataEvidence
)
from sqlalchemy import select, func

now_year = datetime.now().year

print("="*80)
print("SIMPLE DATE QUALITY CHECK")
print("="*80)

with SessionLocal() as session:
    # Count by date field type
    field_counts = session.execute(
        select(
            WorkDateDerived.display_date_field,
            func.count(Work.work_id)
        )
        .select_from(Work)
        .join(WorkDateDerived)
        .group_by(WorkDateDerived.display_date_field)
        .order_by(func.count(Work.work_id).desc())
    ).all()

    print("\nDate source breakdown:")
    total = sum(count for _, count in field_counts)
    for field, count in field_counts:
        print(f"  {field}: {count:,} ({count/total*100:.1f}%)")

    # Future dates check
    future = session.execute(
        select(func.count(Work.work_id))
        .select_from(Work)
        .join(WorkDateDerived)
        .where(WorkDateDerived.display_year > now_year)
    ).scalar()

    print(f"\n⚠ Future dates: {future}")

    # Dates after author death (within 20 years - possibly posthumous publications)
    posthumous = session.execute(
        select(
            Work.title,
            Author.name_canonical,
            Author.death_year,
            WorkDateDerived.display_year,
            func.count(WorkMetadataEvidence.evidence_id).label("ev_count")
        )
        .select_from(Work)
        .join(Author)
        .join(WorkDateDerived)
        .outerjoin(WorkMetadataEvidence, WorkMetadataEvidence.work_id == Work.work_id)
        .where(WorkDateDerived.display_year > Author.death_year)
        .where(WorkDateDerived.display_year <= Author.death_year + 20)  # Within 20 years
        .where(Author.death_year < 1900)  # Only classical authors
        .group_by(Work.title, Author.name_canonical, Author.death_year, WorkDateDerived.display_year)
        .order_by((WorkDateDerived.display_year - Author.death_year).desc())
        .limit(10)
    ).all()

    if posthumous:
        print("\nRecently published classical works (possibly editions, not originals):")
        for title, author, death, pub, ev in posthumous:
            print(f"  {author}: {title[:40]}... (died {death}, pub {pub})")

print(f"\n{'='*80}")
print(f"Audit complete. Coverage: {(total - future) / total * 100:.1f}% (excluding future dates)")
print("="*80)
