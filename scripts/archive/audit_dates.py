#!/usr/bin/env python3
"""Audit for potentially incorrectly dated works."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "ingest_service" / "src"))

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import (
    Work, Author, Edition, WorkDateDerived, WorkMetadataEvidence
)
from sqlalchemy import select, func, and_

print("="*80)
print("AUDIT: POTENTIALLY INCORRECTLY DATED WORKS")
print("="*80)

with SessionLocal() as session:
    now_year = datetime.now().year

    # Check 1: Works with dates after author's death (impossible)
    print("\n1. Works with publication date AFTER author's death:")
    print("-" * 60)

    impossible_dates = session.execute(
        select(
            Work.work_id,
            Work.title,
            Author.name_canonical,
            Author.death_year,
            WorkDateDerived.display_year,
            WorkDateDerived.display_date_field,
            func.array_agg(WorkMetadataEvidence.source_name.distinct()).label("sources")
        )
        .select_from(Work)
        .join(Author)
        .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
        .outerjoin(WorkMetadataEvidence, WorkMetadataEvidence.work_id == Work.work_id)
        .where(WorkDateDerived.display_date_field != "unknown")
        .where(Author.death_year.isnot(None))
        .where(WorkDateDerived.display_year > Author.death_year)
        .group_by(
            Work.work_id, Work.title, Author.name_canonical,
            Author.death_year, WorkDateDerived.display_year,
            WorkDateDerived.display_date_field
        )
        .order_by((WorkDateDerived.display_year - Author.death_year).desc())
    ).all()

    if impossible_dates:
        for work_id, title, author, death_year, pub_year, date_field, sources in impossible_dates:
            print(f"  ⚠ {author}: {title[:50]}")
            print(f"     Died: {death_year}, Published: {pub_year} ({pub_year - death_year} years after death)")
            print(f"     Sources: {sources if sources else 'none'}")
    else:
        print("  ✓ No impossible dates found")

    # Check 2: Works with dates before author's birth (unlikely unless posthumous)
    print("\n2. Works with publication date BEFORE author's birth:")
    print("-" * 60)

    birth_check = session.execute(
        select(
            Work.work_id,
            Work.title,
            Author.name_canonical,
            Author.birth_year,
            WorkDateDerived.display_year,
            func.count(WorkMetadataEvidence.evidence_id).label("evidence_count")
        )
        .select_from(Work)
        .join(Author)
        .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
        .outerjoin(WorkMetadataEvidence, WorkMetadataEvidence.work_id == Work.work_id)
        .where(WorkDateDerived.display_date_field != "unknown")
        .where(Author.birth_year.isnot(None))
        .where(WorkDateDerived.display_year < Author.birth_year)
        .group_by(
            Work.work_id, Work.title, Author.name_canonical,
            Author.birth_year, WorkDateDerived.display_year
        )
        .order_by((Author.birth_year - WorkDateDerived.display_year).desc())
        .limit(20)
    ).all()

    if birth_check:
        for work_id, title, author, birth_year, pub_year, ev_count in birth_check:
            print(f"  ⚠ {author}: {title[:50]}")
            print(f"     Born: {birth_year}, Published: {pub_year} ({birth_year - pub_year} years before birth)")
            print(f"     Evidence: {ev_count} rows")
    else:
        print("  ✓ No dates before author's birth")

    # Check 3: Works with very low confidence scores (< 0.4)
    print("\n3. Works with LOW confidence evidence (< 0.4):")
    print("-" * 60)

    low_confidence = session.execute(
        select(
            Work.work_id,
            Work.title,
            Author.name_canonical,
            WorkDateDerived.display_year,
            WorkDateDerived.display_date_field,
            func.min(WorkMetadataEvidence.score).label("min_score"),
            func.max(WorkMetadataEvidence.score).label("max_score"),
            func.count(WorkMetadataEvidence.evidence_id).label("evidence_count")
        )
        .select_from(Work)
        .join(Author)
        .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
        .outerjoin(WorkMetadataEvidence, and_(
            WorkMetadataEvidence.work_id == Work.work_id,
            WorkMetadataEvidence.score >= 0
        ))
        .where(WorkDateDerived.display_date_field != "unknown")
        .group_by(Work.work_id, Work.title, Author.name_canonical,
                 WorkDateDerived.display_year, WorkDateDerived.display_date_field)
        .having(func.max(WorkMetadataEvidence.score) < 0.4)
        .order_by(func.max(WorkMetadataEvidence.score))
        .limit(20)
    ).all()

    if low_confidence:
        for work_id, title, author, pub_year, date_field, min_score, max_score, ev_count in low_confidence:
            print(f"  ⚠ {author}: {title[:50]}")
            print(f"     Date: {pub_year} ({date_field}), Score: {max_score:.2f} (evidence: {ev_count})")
    else:
        print("  ✓ No low-confidence dates")

    # Check 4: Works with conflicting evidence (multiple different years)
    print("\n4. Works with CONFLICTING evidence (3+ different years):")
    print("-" * 60)

    conflicting = session.execute(
        select(
            Work.work_id,
            Work.title,
            Author.name_canonical,
            WorkDateDerived.display_year,
            func.count(func.distinct(WorkMetadataEvidence.extracted['year'])).label("year_count"),
            func.count(WorkMetadataEvidence.evidence_id).label("evidence_count")
        )
        .select_from(Work)
        .join(Author)
        .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
        .join(WorkMetadataEvidence, WorkMetadataEvidence.work_id == Work.work_id)
        .where(WorkDateDerived.display_date_field != "unknown")
        .where(WorkMetadataEvidence.extracted['year'].isnot(None))
        .group_by(Work.work_id, Work.title, Author.name_canonical, WorkDateDerived.display_year)
        .having(func.count(func.distinct(WorkMetadataEvidence.extracted['year'])) >= 3)
        .order_by(func.count(func.distinct(WorkMetadataEvidence.extracted['year'])).desc())
        .limit(20)
    ).all()

    if conflicting:
        for work_id, title, author, pub_year, year_count, ev_count in conflicting:
            print(f"  ⚠ {author}: {title[:50]}")
            print(f"     Chosen date: {pub_year}, but evidence has {year_count} different years ({ev_count} evidence rows)")

            # Get the actual years
            years = session.execute(
                select(func.distinct(WorkMetadataEvidence.extracted['year']))
                .where(WorkMetadataEvidence.work_id == work_id)
                .where(WorkMetadataEvidence.extracted['year'].isnot(None))
            ).scalars().all()
            print(f"     Years found: {sorted(years)}")
    else:
        print("  ✓ No major conflicts found")

    # Check 5: Works with dates in the future (data error)
    print("\n5. Works with dates in the FUTURE:")
    print("-" * 60)

    future_dates = session.execute(
        select(
            Work.work_id,
            Work.title,
            Author.name_canonical,
            WorkDateDerived.display_year,
            func.array_agg(WorkMetadataEvidence.source_name.distinct()).label("sources")
        )
        .select_from(Work)
        .join(Author)
        .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
        .outerjoin(WorkMetadataEvidence, WorkMetadataEvidence.work_id == Work.work_id)
        .where(WorkDateDerived.display_year > now_year)
        .group_by(Work.work_id, Work.title, Author.name_canonical, WorkDateDerived.display_year)
        .order_by(WorkDateDerived.display_year.desc())
    ).all()

    if future_dates:
        for work_id, title, author, pub_year, sources in future_dates:
            print(f"  ⚠ {author}: {title[:50]}")
            print(f"     Future date: {pub_year} (current year: {now_year})")
            print(f"     Sources: {sources}")
    else:
        print("  ✓ No future dates")

    # Check 6: Recently dated works that might be mislabeled (modern dates for classical authors)
    print("\n6. CLASSICAL authors with MODERN dates (post-1950):")
    print("-" * 60)

    classical_authors = ["Marx", "Engels", "Lenin", "Trotsky", "Luxemburg", "Bakunin", "Kautsky"]
    modern_classical = session.execute(
        select(
            Work.work_id,
            Work.title,
            Author.name_canonical,
            Author.death_year,
            WorkDateDerived.display_year,
            WorkDateDerived.display_date_field
        )
        .select_from(Work)
        .join(Author)
        .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
        .where(WorkDateDerived.display_year >= 1950)
        .where(Author.name_canonical.in_(classical_authors))
        .where(Author.death_year < 1925)  # Author died before 1925
        .order_by(WorkDateDerived.display_year.desc())
        .limit(20)
    ).all()

    if modern_classical:
        for work_id, title, author, death_year, pub_year, date_field in modern_classical:
            print(f"  ⚠ {author}: {title[:50]}")
            print(f"     Author died: {death_year}, Work dated: {pub_year} ({date_field})")
            print(f"     Likely: edition/translation date, not original publication")
    else:
        print("  ✓ No mislabeled classical works found")

print(f"\n{'='*80}")
print("AUDIT COMPLETE")
print("="*80)
