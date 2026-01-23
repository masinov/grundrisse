#!/usr/bin/env python3
"""Final report on metadata completion."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "ingest_service" / "src"))

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import (
    Work, Author, Edition, WorkDateDerived
)
from sqlalchemy import select, func

print("="*80)
print("METADATA COMPLETION FINAL REPORT")
print("="*80)

with SessionLocal() as session:
    # Total works
    total_works = session.execute(
        select(func.count(Work.work_id))
    ).scalar()

    # Status breakdown
    status_counts = session.execute(
        select(
            WorkDateDerived.display_date_field,
            func.count(WorkDateDerived.work_id)
        )
        .group_by(WorkDateDerived.display_date_field)
        .order_by(func.count(WorkDateDerived.work_id).desc())
    ).all()

    print(f"\nTotal works in corpus: {total_works:,}")
    print(f"\nDate source breakdown:")
    for status, count in status_counts:
        pct = count / total_works * 100
        print(f"  {status}: {count:,} ({pct:.1f}%)")

    # Remaining unknown works
    unknown_count = session.execute(
        select(func.count(WorkDateDerived.work_id))
        .where(WorkDateDerived.display_date_field == "unknown")
    ).scalar()

    print(f"\n{'='*80}")
    print(f"FINAL RESULTS")
    print(f"{'='*80}")
    print(f"Original unknown works: 3,477 (18.2%)")
    print(f"Final unknown works: {unknown_count} ({unknown_count/total_works*100:.1f}%)")
    print(f"Works recovered: 3,477 - {unknown_count} = {3477 - unknown_count}")
    print(f"Recovery rate: {(3477 - unknown_count) / 3477 * 100:.1f}%")
    print(f"Final coverage: {(total_works - unknown_count) / total_works * 100:.1f}%")

    # Show remaining unknown works
    if unknown_count > 0:
        print(f"\n{'='*80}")
        print(f"REMAINING UNKNOWN WORKS ({unknown_count})")
        print(f"{'='*80}")

        remaining = session.execute(
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

        for work_id, title, author, urls in remaining:
            url = urls[0] if urls else "NO URL"
            print(f"\n  - {author}: {title}")
            print(f"    URL: {url}")

print(f"\n{'='*80}")
