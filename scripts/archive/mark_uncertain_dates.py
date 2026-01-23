#!/usr/bin/env python3
"""
Mark works with unknown dates as 'date_uncertain' in the dates JSON bundle.

This provides transparency for downstream analysis by explicitly flagging
works that should not be included in chronological studies.
"""

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import WorkDateDerived
from sqlalchemy import select

def mark_uncertain_dates(dry_run: bool = False) -> None:
    """
    Add 'status': 'date_uncertain' to works with display_date_field='unknown'.

    Args:
        dry_run: If True, print what would be updated without modifying DB
    """
    with SessionLocal() as session:
        # Find all works with unknown dates
        stmt = select(WorkDateDerived).where(
            WorkDateDerived.display_date_field == 'unknown'
        )
        unknown_works = session.execute(stmt).scalars().all()

        print(f"Found {len(unknown_works)} works with unknown dates")

        if dry_run:
            print("\n[DRY RUN] Would mark these works as date_uncertain:")
            for i, work in enumerate(unknown_works[:5], 1):
                print(f"  {i}. work_id: {work.work_id}")
            if len(unknown_works) > 5:
                print(f"  ... and {len(unknown_works) - 5} more")
            return

        # Update each work's dates JSON to include status
        updated_count = 0
        for work in unknown_works:
            dates = dict(work.dates) if work.dates else {}

            # Add status flag
            dates['status'] = 'date_uncertain'
            dates['status_reason'] = 'no_date_evidence_available'
            dates['status_notes'] = (
                'This work has no publication date information from marxists.org headers, '
                'external sources (Wikidata/OpenLibrary), or heuristic extraction. '
                'Should not be included in chronological analysis without manual verification.'
            )

            work.dates = dates
            updated_count += 1

        session.commit()
        print(f"\n✓ Successfully marked {updated_count} works as date_uncertain")
        print(f"  Updated field: work_date_derived.dates['status'] = 'date_uncertain'")


if __name__ == '__main__':
    import sys

    dry_run = '--dry-run' in sys.argv

    if dry_run:
        print("Running in DRY RUN mode (no changes will be made)\n")
    else:
        print("WARNING: This will update the database.")
        response = input("Continue? [y/N]: ")
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(0)

    mark_uncertain_dates(dry_run=dry_run)
