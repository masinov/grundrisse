#!/usr/bin/env python3
"""
Fix clearly incorrect dates from HTML parsing artifacts.
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "ingest_service" / "src"))

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import (
    Work, Author, WorkDateDerived, WorkMetadataRun, WorkMetadataEvidence
)
from sqlalchemy import select

print("="*80)
print("FIXING INCORRECT DATES")
print("="*80)

with SessionLocal() as session:
    run_id = uuid.uuid4()

    # Create run record
    run = WorkMetadataRun(
        run_id=run_id,
        pipeline_version="metadata_completion_v1",
        strategy="data_quality_correction",
        params={"action": "remove_spurious_dates"},
        sources=["manual_correction"],
        started_at=datetime.now(timezone.utc),
        status="started",
    )
    session.add(run)
    session.commit()

    # Get all evidence from HTML parsing
    all_html_evidence = session.execute(
        select(WorkMetadataEvidence, Work, Author, WorkDateDerived)
        .select_from(WorkMetadataEvidence)
        .join(Work, Work.work_id == WorkMetadataEvidence.work_id)
        .join(Author, Author.author_id == Work.author_id)
        .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
        .where(WorkMetadataEvidence.source_name.in_(["html_content_parsing", "html_content_aggressive"]))
    ).all()

    print(f"\nChecking {len(all_html_evidence)} HTML evidence entries...")

    removed = 0
    kept = 0

    for ev, work, author, derived in all_html_evidence:
        year = ev.extracted.get('year') if ev.extracted else None
        if not year:
            continue

        # Flag bad evidence:
        # 1. Date > 2000 and author died before 1950 (spurious website date)
        # 2. Date > author's death year + 50 years (likely edition date, not original)
        is_bad = False
        reason = None

        if year > 2000 and author.death_year and author.death_year < 1950:
            is_bad = True
            reason = f"future date {year} for author who died {author.death_year}"
        elif author.death_year and year > author.death_year + 50:
            is_bad = True
            reason = f"date {year} is {year - author.death_year} years after author's death ({author.death_year})"

        if is_bad:
            print(f"  X Removing: {author.name_canonical}: {work.title[:40]}... (evidence year={year})")
            print(f"    Reason: {reason}")
            session.delete(ev)
            removed += 1
        else:
            kept += 1

    # Also remove web_research_manual evidence with very low confidence (< 0.4)
    low_conf = session.execute(
        select(WorkMetadataEvidence, Work, Author)
        .select_from(WorkMetadataEvidence)
        .join(Work, Work.work_id == WorkMetadataEvidence.work_id)
        .join(Author, Author.author_id == Work.author_id)
        .where(WorkMetadataEvidence.source_name == "web_research_manual")
        .where(WorkMetadataEvidence.score < 0.4)
    ).all()

    print(f"\nFound {len(low_conf)} low-confidence web research entries to remove")

    for ev, work, author in low_conf:
        year = ev.extracted.get('year') if ev.extracted else None
        print(f"  X Removing: {author.name_canonical}: {work.title[:40]}... (score={ev.score:.2f}, year={year})")
        session.delete(ev)
        removed += 1

    session.commit()

    # Update run record
    run.works_scanned = len(all_html_evidence) + len(low_conf)
    run.works_updated = removed
    run.status = "completed"
    run.finished_at = datetime.now(timezone.utc)
    session.commit()

    print(f"\n{'='*80}")
    print(f"REMOVED {removed} bad evidence entries")
    print(f"KEPT {kept} valid HTML evidence entries")
    print(f"{'='*80}")

print("\nNext step: Run 'grundrisse-ingest derive-work-dates --force --limit 20000'")
