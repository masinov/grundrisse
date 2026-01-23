#!/usr/bin/env python3
"""Check post-recovery status."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "ingest_service" / "src"))

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import WorkDateDerived
from sqlalchemy import select, func

with SessionLocal() as session:
    # Check new status
    status_counts = session.execute(
        select(
            WorkDateDerived.display_date_field,
            func.count(WorkDateDerived.work_id)
        )
        .group_by(WorkDateDerived.display_date_field)
        .order_by(func.count(WorkDateDerived.work_id).desc())
    ).all()

    print("="*80)
    print("POST-RECOVERY STATUS")
    print("="*80)
    total = sum(count for _, count in status_counts)
    for status, count in status_counts:
        pct = count / total * 100
        print(f"  {status}: {count:,} ({pct:.1f}%)")

    # Count unknown remaining
    unknown_count = session.execute(
        select(func.count(WorkDateDerived.work_id))
        .where(WorkDateDerived.display_date_field == "unknown")
    ).scalar()

    print(f"\nRemaining unknown: {unknown_count:,}")
    print(f"\nImprovement: 3477 -> {unknown_count} ({3477 - unknown_count} works recovered)")
    print(f"New coverage: {(total - unknown_count) / total * 100:.1f}%")
